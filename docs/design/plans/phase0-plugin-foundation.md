# Conclave Phase 0 + 1 实施计划：插件框架 + Auth 重构 + 核心钩子植入

> 目标：在不破坏现有功能的前提下，建立插件化架构地基
> 预计工期：3周（Phase 0: 1周, Phase 1a: 1周, Phase 1b: 1周）
> 前置依赖：无（从当前代码状态开始）
> 参考文档：
> - `docs/design/team-management-design.md` (v0.4 Final Draft)
> - ADR-001 插件化架构
> - ADR-002 JSONB metadata 扩展槽
> - ADR-003 插件三层分级 (CORE/CROSSCUTTING/OPTIONAL)
> - ADR-004 钩子二分法 (Interceptor/Observer)
> - ADR-006 JWT HttpOnly Cookie
> - ADR-007 配额父池切分
> - ADR-008 配额耗尽 BYOK Fallback

---

## 现有代码结构盘点

在动手之前，明确当前代码现状，避免路径假设错误：

### 后端关键文件现状

| 文件 | 现状摘要 |
|------|----------|
| `backend/app/main.py` | `create_app()` 直接硬编码挂载 13 个 router；`lifespan()` 中硬编码调用 `init_db()`, `init_auth_table()`, `init_jwt_auth()`, `memory_store.init()`, `init_redis()`, `recover_crashed_meetings()`, metrics/sandbox/pricing/key-loader 等 6 个后台任务；CORS、body-size、auth-middleware、trace-middleware 均在 `create_app()` 内直接注册；`/health` 端点内联定义 |
| `backend/app/auth.py` | 自建 JWT (HMAC-SHA256, 标准库 hmac+hashlib, 非 PyJWT)；PBKDF2 密码哈希 (600,000 次迭代)；`users` 表通过 `text()` DDL 创建 (非 SQLAlchemy ORM)；内存 `_users_cache`；`create_access_token()`/`decode_token()`/`authenticate_user()`/`init_auth()` 等全局函数；JWT secret 持久化到 `.jwt_secret` 文件 |
| `backend/app/middleware.py` | `setup_auth_middleware()` 注册 HTTP middleware 做认证（从 `Authorization: Bearer` 读 JWT，同时支持 dev token 比对）；`setup_trace_middleware()` 做 request_id 注入与访问日志；速率限制（内存 dict + 定期清理）；`_PUBLIC_PATHS` 硬编码免认证路径；WS 认证 `verify_ws_token()` 单独实现 |
| `backend/app/context.py` | 已有 7 个 ContextVar：`_request_id`, `_meeting_id`, `_runner_session_id`, `_agent_role`, `_user_id`, `_username`, `_user_role`；带 get/set/reset 函数 |
| `backend/app/routers/auth.py` | 两个端点：`POST /auth/login`（返回 JSON access_token）、`GET /auth/me`；依赖 `request.state.auth_user` |
| `backend/app/routers/metrics.py` | `/metrics`, `/metrics/history`, `/metrics/health`；内联调用 `get_cost_tracker().summary()` 和 `get_metrics_store()` |
| `backend/app/agents/llm.py` | `RealLLM.complete()` 是核心 LLM 调用入口；`_resolve_config()` 从 `llm_providers.get_meeting_llm_config(mid)` 获取会议级 key/model 覆盖；`_call_api()` 发 httpx 请求、解析 token 用量、调用 `record_call()` 写 trace、调用 `get_cost_tracker().record_llm()` 记成本；内置熔断器 `CircuitBreaker`；provider 回退链 `get_fallback_chain()`；StubLLM 降级 |
| `backend/app/observability/cost_tracker.py` | `CostTracker` 单例（进程级全局变量 `_cost_tracker`）；`record_llm()`/`record_tool()`/`summary()`；异步刷盘到 `CostRecordModel` |
| `backend/app/events.py` | 已有 `InMemoryEventBus`（内存 + PG 持久化）和 `DomainEvent`；用于 WS 推送，非插件间通信 |
| `backend/app/services/key_store.py` | 使用 `cryptography.Fernet` 做 AES 加密；密钥从 `CONCLAVE_SECRET_KEY` 环境变量或 `.secret_key` 文件派生；`encrypt_key()`/`decrypt_key()`；CRUD 操作 `api_keys` 表（`ApiKeyModel` 在 `db/models/user.py`） |
| `backend/app/db/models/meeting.py` | `MeetingModel`：字段 id/topic/owner_username/status/stage/created_at/payload/schema_version；无 metadata 列；关系包含 messages/events/tags；有 `meeting_aux` 大字段分离表 |
| `backend/app/db/models/user.py` | 含 `UserPreferenceModel`（user_id+key 主键）和 `ApiKeyModel`（BYOK 全局 key，非按用户归属）——**注意**：当前 `ApiKeyModel` 无 user_id 外键，是全局 provider key 存储，不是用户个人 BYOK |
| `backend/app/db/models/observability.py` | 含 `CostRecordModel`（成本记录持久化） |
| `backend/alembic/versions/` | 已有 4 个迁移：0001_initial_schema, 0002_add_aux_api_keys_docs_cost, 0003_drop_cost_records_fk, 0004_add_memory_tables |
| 前端（`archive/frontend-react-original/src/`） | `lib/api.ts` 使用 axios；`store/AuthContext.tsx` 管理 token（存储在 localStorage）；拦截器在 header 注入 `Authorization: Bearer`；`pages/LoginPage.tsx` 登录后保存 token |

---

## Phase 0: 插件框架地基（第1周）

Phase 0 的核心原则：**只新增文件，不修改任何现有业务文件**（`main.py` 除外，它是唯一需要改动的入口）。所有插件能力通过新目录 `backend/app/plugins/` 承载，注册逻辑在 `create_app()` 中以"无插件时等价于旧行为"的方式接入。

### P0.1 项目结构准备

**新增目录结构**：

```
backend/app/plugins/
├── __init__.py                    # 导出 get_registry() 等便捷函数
├── core/
│   ├── __init__.py
│   ├── registry.py                # PluginRegistry 实现
│   ├── event_bus.py               # 插件间 EventBus（与现有 events.py 的 DomainEvent 总线分离）
│   ├── context.py                 # 插件级 ContextVar 扩展（在现有 app/context.py 基础上追加）
│   ├── exceptions.py              # ConclaveException 基类 + 错误码
│   ├── hooks/
│   │   ├── __init__.py            # Interceptor/Observer/Override/Fallback/Next/hook 装饰器
│   │   ├── llm.py                 # LLMPreCallMixin / LLMObserverMixin / LLMErrorMixin
│   │   ├── meeting.py             # MeetingCreateMixin / MeetingAccessMixin
│   │   └── lifecycle.py           # LifecycleMixin / RouterMixin / MiddlewareMixin
│   └── types.py                   # PluginTier, PluginState, PluginHealth, HookResult 类型
└── builtin/                       # 内置插件目录（Phase 1a/1b 才填充）
    └── __init__.py
```

**创建 `__init__.py` 文件**：所有 `__init__.py` 均为初始空文件（或仅导出后续会用到的公共符号），不导入任何现有业务模块。

**验证**：新增目录不应导致任何 import 副作用，`python -c "from app.plugins.core import registry"` 应可无异常执行（即使 registry 模块此时为空）。

### P0.2 插件基础类型定义

**文件**：`backend/app/plugins/core/types.py`

```python
from __future__ import annotations
import enum
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable
from datetime import datetime

class PluginTier(str, enum.Enum):
    CORE = "core"
    CROSSCUTTING = "crosscutting"
    OPTIONAL = "optional"

class PluginState(str, enum.Enum):
    DISCOVERED = "discovered"
    LOADED = "loaded"
    INITIALIZING = "initializing"
    READY = "ready"
    DEGRADED = "degraded"
    SHUTTING_DOWN = "shutting_down"
    FAILED = "failed"
    STOPPED = "stopped"
    DISABLED = "disabled"

@dataclass
class PluginHealth:
    healthy: bool
    message: str = ""
    last_check: datetime | None = None
    details: dict[str, Any] = field(default_factory=dict)

# ---- Hook 返回值类型 ----
@dataclass
class Override:
    """拦截型钩子返回：使用此值，终止调用链"""
    value: Any
_NEXT = object()
@dataclass
class Next:
    """拦截型钩子返回：弃权，交给下一个插件"""
    pass
@dataclass
class Fallback:
    """拦截型钩子返回：阻断操作，抛出错误"""
    reason: str
    code: str = "PLUGIN_REJECTED"
    status_code: int = 403
    details: dict[str, Any] = field(default_factory=dict)

@dataclass
class LLMOverride:
    """on_llm_pre_call 返回：替换 LLM 调用参数"""
    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None
    extra_headers: dict[str, str] | None = None

@dataclass
class LLMFallback:
    """on_llm_error 返回：切换 Key 重试"""
    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None
    reason: str = ""

@dataclass
class PluginContext:
    """传递给插件钩子的上下文对象"""
    app: Any                   # FastAPI 实例
    registry: Any             # PluginRegistry 实例
    request_id: str = ""
    extra: dict[str, Any] = field(default_factory=dict)
```

**Mixin 定义文件**：`backend/app/plugins/core/hooks/` 下分文件定义

`hooks/__init__.py` 导出 Override/Fallback/Next 以及 hook 装饰器标记。

`hooks/lifecycle.py`：
```python
from typing import Protocol, runtime_checkable
from fastapi import FastAPI

@runtime_checkable
class LifecycleMixin(Protocol):
    async def on_startup(self, ctx: "PluginContext") -> None: ...
    async def on_shutdown(self, ctx: "PluginContext") -> None: ...
    async def health_check(self) -> "PluginHealth": ...

@runtime_checkable
class RouterMixin(Protocol):
    def register_routers(self, app: FastAPI) -> None: ...

@runtime_checkable
class MiddlewareMixin(Protocol):
    def register_middlewares(self, app: FastAPI) -> None: ...
```

`hooks/llm.py`：
```python
from typing import Protocol, runtime_checkable
from dataclasses import dataclass

@dataclass
class LLMRequest:
    prompt: str
    schema_hint: str
    model: str
    base_url: str
    api_key: str
    agent_role: str
    stage: str
    meeting_id: str
    request_id: str

@dataclass
class LLMResponse:
    content: str
    parsed: dict | None
    model: str
    provider: str

@dataclass
class LLMUsage:
    input_tokens: int
    output_tokens: int
    total_tokens: int
    latency_ms: int
    cost_usd: float

@dataclass
class LLMErrorInfo:
    error_type: str     # connection | http | validation | quota | timeout | unknown
    status_code: int | None
    message: str
    raw_error: Exception | None

@runtime_checkable
class LLMPreCallMixin(Protocol):
    async def on_llm_pre_call(self, ctx: "PluginContext", req: LLMRequest) -> "LLMOverride | Next | Fallback | None": ...

@runtime_checkable
class LLMObserverMixin(Protocol):
    async def on_llm_post_call(self, ctx: "PluginContext", req: LLMRequest, resp: LLMResponse, usage: LLMUsage) -> None: ...

@runtime_checkable
class LLMErrorMixin(Protocol):
    async def on_llm_error(self, ctx: "PluginContext", req: LLMRequest, err: LLMErrorInfo) -> "LLMFallback | Next | None": ...
```

`hooks/meeting.py`：
```python
from typing import Protocol, runtime_checkable, Any

@runtime_checkable
class MeetingCreatingMixin(Protocol):
    async def on_meeting_creating(self, ctx: "PluginContext", payload: dict) -> "Next | Fallback | None":
        """可返回 Fallback 阻止创建；可通过 ctx.extra['metadata_patch'] 注入 metadata 片段"""
        ...

@runtime_checkable
class MeetingCreatedMixin(Protocol):
    async def on_meeting_created(self, ctx: "PluginContext", meeting_id: str, metadata: dict) -> None: ...

@runtime_checkable
class MeetingAccessMixin(Protocol):
    async def on_meeting_accessing(self, ctx: "PluginContext", meeting: Any) -> "Next | Fallback | None":
        """可返回 Fallback 拒绝访问"""
        ...
```

**PluginBase Protocol**：
```python
@runtime_checkable
class PluginBase(Protocol):
    name: str
    version: str
    tier: PluginTier
    dependencies: list[str]   # ["auth"] 或 ["billing?"] 软依赖
    priority: int            # 同 tier 内排序，默认 100，数值越小越先执行
```

### P0.3 PluginRegistry 实现

**文件**：`backend/app/plugins/core/registry.py`

核心设计要点：

1. **实例化而非类变量单例**：在 `create_app()` 中 `registry = PluginRegistry()`，通过 `app.state.plugin_registry` 挂载。提供模块级 `_current_registry` 全局引用（通过 `set_global_registry()` / `get_registry()` 访问），便于非请求路径（如后台任务）获取，但不作为单例模式强制使用。

2. **注册方法**：
   ```python
   class PluginRegistry:
       def __init__(self, hook_timeout_ms: int = 200): ...
       def register(self, plugin: PluginBase) -> None: ...
       def unregister(self, name: str) -> None: ...
       def is_registered(self, name: str) -> bool: ...
       def get_plugin(self, name: str) -> PluginBase | None: ...
   ```

3. **依赖解析（拓扑排序）**：
   - 实现 Kahn 算法（BFS 拓扑排序）；
   - 同层级内按 `(priority, name)` 排序保证确定性；
   - 软依赖（`"billing?"` 后缀）缺失时仅记录 WARNING，不阻断；
   - 循环依赖检测：排序后节点数 < 注册数 → 存在环，启动失败并打印环路。

4. **钩子触发方法**（核心）：
   ```python
   async def fire_interceptor(
       self, hook_name: str, ctx: PluginContext, *args,
       default: Any = None,
       aggregate: bool = False,
   ) -> Any:
       """拦截型：按 tier+priority 顺序调用，第一个 Override/Fallback 终止链"""
       # 1. 收集实现了 hook_name 的插件（跳过 DISABLED/FAILED 的非 CORE 插件）
       # 2. 按 CORE → CROSSCUTTING → OPTIONAL 排序，同 tier 按 priority 升序
       # 3. 逐个 asyncio.wait_for(plugin.method(...), timeout=hook_timeout/1000)
       # 4. 返回 Override.value 或 raise Fallback 对应的 HTTPException
       # 5. 超时或异常：CORE 插件异常向上抛；CROSSCUTTING/OPTIONAL 异常记录 WARNING 继续
       # 6. aggregate=True 模式：收集所有 Fallback reason 列表返回

   async def fire_observer(
       self, hook_name: str, ctx: PluginContext, *args,
       concurrent: bool = False,
   ) -> None:
       """观察型：所有健康插件都执行，返回值全部忽略，异常隔离"""
       # 1. 收集所有实现了 hook_name 的插件（含 DEGRADED 插件，best-effort）
       # 2. 逐个 asyncio.wait_for(...) 超时即跳过
       # 3. concurrent=True 时用 asyncio.gather(return_exceptions=True) 并发
       # 4. 单个插件异常不影响其他插件
   ```

5. **钩子超时处理**：
   - 默认 200ms（`hook_timeout_ms` 可配置，通过 `CONCLAVE_PLUGIN_HOOK_TIMEOUT_MS` 环境变量覆盖）；
   - `asyncio.wait_for` 包裹每个插件的钩子调用；
   - 超时后：Interceptor 视为 Next（弃权），Observer 直接跳过；
   - 超时事件记 WARNING 日志，包含 plugin_name、hook_name、elapsed_ms；
   - 同一插件 1 分钟内超时超过 10 次，将其标记为 DEGRADED（仅 CROSSCUTTING/OPTIONAL）。

6. **健康检查集成**：
   - 后台任务：每 30 秒对所有实现 `LifecycleMixin` 的插件并发调用 `health_check()`；
   - 结果更新到 `self._health: dict[str, PluginHealth]`；
   - CORE 插件健康检查连续 3 次失败 → 记录 CRITICAL 日志（但不自动重启进程，由 K8s liveness probe 处理）；
   - 提供 `get_health_snapshot() -> dict[str, PluginHealth]`。

7. **热开关支持**：
   - 启动时从 Redis 读取 `conclave:plugins:disabled` Set（若 Redis 不可用，降级为空集并记 WARNING）；
   - 订阅 Redis Pub/Sub `conclave:plugins:control` 频道实时更新禁用列表；
   - 无 Redis 时：提供内存版 API `disable_plugin(name)`/`enable_plugin(name)`（测试和无 Redis 部署使用）；
   - CORE 插件禁用请求被拒绝并记录 ERROR；
   - 钩子触发前检查禁用列表，被禁用插件的拦截器跳过、观察器不触发。

8. **生命周期管理**：
   ```python
   async def resolve_and_load(self, ctx: PluginContext) -> None:
       """拓扑排序 → 按序调用 on_startup → 注册路由/中间件"""
       # 1. 拓扑排序
       # 2. 按序调用 on_startup（CORE 失败抛异常阻断启动，CROSSCUTTING 失败标 DEGRADED，OPTIONAL 失败标 DISABLED）
       # 3. 标记状态为 READY
       # 4. 启动健康检查后台任务
   
   async def shutdown_all(self, ctx: PluginContext) -> None:
       """按拓扑序逆序调用 on_shutdown"""
   
   def register_all_routers(self, app: FastAPI) -> None:
       """对所有 READY 插件调用 register_routers"""
   
   def register_all_middlewares(self, app: FastAPI) -> None:
       """对所有 READY 插件调用 register_middlewares"""
   ```

### P0.4 EventBus 实现

**文件**：`backend/app/plugins/core/event_bus.py`

注意：此 EventBus 与现有的 `backend/app/events.py`（`InMemoryEventBus` + `DomainEvent`，用于 WS 推送）是**两个独立的总线**。现有 events.py 继续服务 WebSocket 实时推送；新 EventBus 专门用于插件间解耦通信。两者未来可以桥接，但 Phase 0 不做。

```python
from __future__ import annotations
import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable
import logging

logger = logging.getLogger("plugins.event_bus")

@dataclass
class PluginEvent:
    type: str
    payload: dict[str, Any] = field(default_factory=dict)
    ts: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    source_plugin: str = ""
    request_id: str = ""

EventHandler = Callable[[PluginEvent], Awaitable[None]]

class PluginEventBus:
    """插件间事件总线：简单 pub/sub，异步派发，不持久化"""
    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler]] = {}
    
    def subscribe(self, event_type: str, handler: EventHandler) -> Callable[[], None]:
        """订阅事件，返回取消订阅函数"""
        self._handlers.setdefault(event_type, []).append(handler)
        def _unsub():
            try: self._handlers[event_type].remove(handler)
            except ValueError: pass
        return _unsub
    
    async def publish(self, event: PluginEvent) -> None:
        """发布事件：并发通知所有订阅者，异常隔离"""
        handlers = list(self._handlers.get(event.type, []))
        if not handlers:
            return
        results = await asyncio.gather(*[h(event) for h in handlers], return_exceptions=True)
        for h, r in zip(handlers, results):
            if isinstance(r, Exception):
                logger.warning("Plugin event handler %s for %s failed: %s", h, event.type, r)
```

EventBus 实例由 PluginRegistry 持有（`registry.event_bus`），通过 PluginContext 传递给插件。

### P0.5 ContextVar 定义

**文件**：`backend/app/context.py`（**追加而非重写**）

在现有 7 个 ContextVar 基础上追加以下变量：

```python
# ---- 插件系统 ContextVar（追加到现有文件末尾） ----
_plugin_name: contextvars.ContextVar[str] = contextvars.ContextVar(
    "plugin_name", default="-"
)

def get_plugin_name() -> str:
    return _plugin_name.get()

def set_plugin_name(name: str) -> contextvars.Token[str]:
    return _plugin_name.set(name)

def reset_plugin_name(token: contextvars.Token[str]) -> None:
    _plugin_name.reset(token)
```

同时在现有文件的 `get_trace_context()` 返回 dict 中追加 `"plugin_name"` 字段。

**ContextVar 访问工具**：在 `backend/app/plugins/core/context.py` 中提供便捷函数，供插件内部使用：

```python
from app.context import (
    get_request_id, set_request_id, reset_request_id,
    get_meeting_id, set_meeting_id, reset_meeting_id,
    get_user_id, get_username, get_user_role,
    get_plugin_name, set_plugin_name, reset_plugin_name,
)

def plugin_context(plugin_name: str):
    """上下文管理器：在插件钩子调用期间设置 plugin_name ContextVar"""
    from contextlib import contextmanager
    @contextmanager
    def _ctx():
        token = set_plugin_name(plugin_name)
        try:
            yield
        finally:
            reset_plugin_name(token)
    return _ctx()
```

### P0.6 集成到 create_app()

**修改文件**：`backend/app/main.py`

这是 Phase 0 唯一修改的现有业务文件。改造策略：**插件加载逻辑嵌入到现有流程中，不注册任何插件时行为与之前完全等价**。

具体修改点：

1. **文件顶部新增 import**（不删除任何现有 import）：
   ```python
   from app.plugins.core.registry import PluginRegistry
   from app.plugins.core.context import PluginContext
   from app.plugins.core.event_bus import PluginEventBus
   from app.plugins.core.types import PluginTier
   ```

2. **在 `create_app()` 函数开头构造 PluginRegistry**：
   ```python
   def create_app() -> FastAPI:
       # ---- 新增：插件系统初始化 ----
       _hook_timeout = int(os.environ.get("CONCLAVE_PLUGIN_HOOK_TIMEOUT_MS", "200"))
       plugin_registry = PluginRegistry(hook_timeout_ms=_hook_timeout)
       plugin_event_bus = PluginEventBus()
       plugin_registry.event_bus = plugin_event_bus
       # 从环境变量读取要加载的插件列表（逗号分隔），空字符串表示不加载任何插件
       _plugins_env = os.environ.get("CONCLAVE_PLUGINS", "")
       _enabled_plugins = [p.strip() for p in _plugins_env.split(",") if p.strip()]
       # Phase 0 没有内置插件，这里预留加载入口
       _loaded = _load_plugins_from_env(plugin_registry, _enabled_plugins)
       if _loaded:
           logger.info("已启用插件: %s", ", ".join(_loaded))
       # ---- 原有代码继续 ----
       app = FastAPI(...)
       # ... CORS, body-size middleware ...
       # 将 registry 挂载到 app.state
       app.state.plugin_registry = plugin_registry
       app.state.plugin_event_bus = plugin_event_bus
   ```

3. **新增辅助函数 `_load_plugins_from_env()`**（在 `create_app()` 之前定义，或放在 `app/plugins/loader.py`）：
   - Phase 0 阶段：此函数为空实现，返回空列表（不加载任何插件）；
   - Phase 1a 阶段：此函数根据名称 import 对应内置插件模块（`app.plugins.builtin.auth` 等），实例化并注册；
   - 未来支持第三方插件：通过 `entry_points` 或配置的模块路径加载。

4. **修改 `lifespan()` 上下文管理器**：在现有初始化逻辑**之后**、`yield` **之前**，调用插件启动；在 `yield` 之后、现有清理逻辑**之前**调用插件关闭：
   ```python
   @asynccontextmanager
   async def lifespan(app: FastAPI):
       # ---- 原有初始化全部保留 ----
       await init_db()
       await init_auth_table()
       await init_jwt_auth()
       # ... memory_store.init(), init_redis(), recover_crashed_meetings() ...
       # ... 后台任务启动 ...
       start_rate_limit_cleanup()
       
       # ---- 新增：插件启动（在所有核心初始化完成后） ----
       registry: PluginRegistry = app.state.plugin_registry
       if registry.has_plugins():
           ctx = PluginContext(app=app, registry=registry, event_bus=app.state.plugin_event_bus)
           try:
               await registry.resolve_and_load(ctx)
               registry.register_all_middlewares(app)
               registry.register_all_routers(app)
               logger.info("插件系统初始化完成，共 %d 个插件 READY", len(registry.ready_plugins()))
           except Exception as e:
               # CORE 插件失败会抛出异常，此处不做捕获，让进程退出
               logger.critical("插件初始化失败（CORE 插件异常）: %s", e)
               raise
       
       yield
       
       # ---- 新增：插件关闭（在现有清理逻辑之前） ----
       if registry.has_plugins():
           try:
               await registry.shutdown_all(ctx)
           except Exception as e:
               logger.warning("插件关闭异常: %s", e)
       
       # ---- 原有清理逻辑继续 ----
       stop_rate_limit_cleanup()
       # ... get_metrics_store().stop(), close_redis(), cleanup_all_services() ...
   ```

5. **插件失败处理逻辑**（在 `resolve_and_load` 内部实现）：
   - CORE 插件 `on_startup` 抛异常 → 捕获后 log CRITICAL → 重新 raise，触发进程退出（`sys.exit(1)` 由 lifespan 异常导致 uvicorn 终止）；
   - CROSSCUTTING 插件 `on_startup` 抛异常 → 标记为 DEGRADED，继续启动其他插件，记录 ERROR + 告警；
   - OPTIONAL 插件 `on_startup` 抛异常 → 标记为 DISABLED/DISABLED，不注册其路由，记录 WARN；
   - 被依赖的 CORE 插件失败 → 依赖它的所有插件标记为 FAILED；
   - 被依赖的 CROSSCUTTING 插件失败（软依赖）→ 依赖者收到 DEGRADED 通知，自行决定降级行为。

6. **验证要求**：
   - 当 `CONCLAVE_PLUGINS=""`（默认值，Phase 0 期间始终如此）时，`_load_plugins_from_env` 返回空列表，`registry.has_plugins()` 返回 False；
   - 此时 `lifespan()` 中的插件初始化/关闭分支都跳过，应用行为与改动前**逐行等价**；
   - 现有所有测试应不加修改全部通过。

### P0.7 单元测试

**新增目录**：`backend/tests/test_plugin_framework/`

测试文件：

1. **`test_registry.py`**：
   - 注册/注销插件；
   - 插件元数据校验（缺 name/tier 时报错）；
   - get_plugin() 返回正确实例。

2. **`test_dependency_resolution.py`**：
   - 线性依赖 A→B→C 正确排序；
   - 菱形依赖 A→B,A→C,B→D,C→D 正确排序；
   - 循环依赖检测（A→B, B→A 抛出明确错误）；
   - 软依赖缺失不报错；
   - 同 tier 内按 priority 排序。

3. **`test_hook_timeout.py`**：
   - Interceptor 钩子中某个插件 sleep 500ms → 200ms 超时后跳过，后续插件继续执行；
   - Observer 钩子中某个插件超时 → 其他插件正常执行；
   - 超时后不影响最终结果（走默认值）。

4. **`test_interceptor_observer.py`**：
   - Interceptor: Override 终止链，后续插件不执行；
   - Interceptor: Fallback 抛出 HTTPException；
   - Interceptor: 所有插件 Next() 返回默认值；
   - Interceptor: aggregate 模式收集所有 Fallback；
   - Observer: 所有插件都执行，即使其中一个抛异常；
   - Observer: 并发模式 (concurrent=True) 正确 gather。

5. **`test_health_check.py`**：
   - 健康检查后台任务启动/停止；
   - 插件 health_check 返回 False 时标记为不健康；
   - get_health_snapshot() 返回正确状态。

6. **`test_hot_disable.py`**：
   - 热禁用 OPTIONAL 插件后其钩子不再被调用；
   - 禁用 CORE 插件被拒绝；
   - Redis 不可用时降级到内存集合。

7. **`test_no_plugins.py`**（关键回归测试）：
   - 不加载任何插件时，PluginRegistry 不注册任何路由/中间件；
   - fire_interceptor/fire_observer 调用安全（空插件列表时返回默认值/立即返回）；
   - EventBus 发布/订阅在无订阅者时不报错。

8. **`test_event_bus.py`**：
   - 订阅/取消订阅；
   - 事件广播到多个订阅者；
   - 订阅者异常不影响其他订阅者。

### Phase 0 验收标准

- [ ] 所有新增文件创建完毕（见 P0.1 目录结构）
- [ ] PluginRegistry 能注册/注销插件，能按拓扑序加载
- [ ] 钩子超时机制工作（200ms 超时跳过，不影响其他插件）
- [ ] Interceptor/Observer 两种钩子语义正确（Override/Fallback/Next、广播/异常隔离）
- [ ] EventBus pub/sub 工作正常
- [ ] 不加载任何插件时（默认配置），现有所有测试通过（`pytest backend/tests/` 全绿）
- [ ] 单元测试覆盖率（新增 `plugins/core/` 目录）> 80%
- [ ] create_app() 集成 PluginRegistry 后，`/health` 端点、所有现有路由行为不变
- [ ] 启动日志中可见"插件系统初始化完成"或"未启用任何插件"的明确信息

---

## Phase 1a: Auth 插件重构 + Setup 流程（第2周）

Phase 1a 的目标：将现有 `app/auth.py` + `app/middleware.py` 中的认证逻辑提取为 `auth` CORE 插件；同时实现首次部署的 `/setup` 流程；迁移到 HttpOnly Cookie + CSRF 方案。

### P1a.1 提取现有认证逻辑

**现有认证代码位置盘点**：

| 位置 | 功能 | 处理方式 |
|------|------|----------|
| `app/auth.py` | JWT 签发/验证、PBKDF2 密码哈希、用户 CRUD（内存+PG text() DDL）、`init_auth()`、`authenticate_user()`、`create_access_token()`、`decode_token()` | **迁移到 auth 插件**，核心工具函数（hash_password/verify_password/create_jwt/verify_jwt）可保留在 `app/auth.py` 作为底层库，插件调用它们 |
| `app/middleware.py` → `setup_auth_middleware()` | HTTP 中间件：从 Authorization header 提取 Bearer token → decode_token() → 设置 request.state.auth_user + ContextVars；同时支持 dev token；速率限制 | **认证部分迁移到 auth 插件的中间件**；速率限制逻辑保留在 middleware.py（后续可独立为 ratelimit CORE 插件，Phase 1a 不动） |
| `app/middleware.py` → `verify_ws_token()` | WebSocket token 验证 | 迁移到 auth 插件，改为从 Cookie 读取 |
| `app/routers/auth.py` | `/auth/login`、`/auth/me` | **迁移到 auth 插件**，原文件保留 re-export 或改为重定向（过渡期） |
| `app/db/models/user.py` | `UserPreferenceModel`、`ApiKeyModel`（全局 BYOK） | 保留在原位，但 auth 插件新增 `users` 表 ORM 模型（替代 auth.py 中的 text() DDL） |
| `app/auth.py` → `_init_users_table()` | text() DDL 建 users 表 | 替换为 SQLAlchemy ORM 模型 + Alembic 迁移 |

**依赖和引用分析**：grep 全项目中对 `from app.auth import` 的引用：
- `app/main.py` → `init_auth`（lifespan 中调用）
- `app/middleware.py` → `decode_token`（auth_middleware 中调用）
- `app/routers/auth.py` → `authenticate_user`, `create_access_token`, `get_user_by_username`, `JWT_EXPIRE_SECONDS`
- 以及 `verify_ws_token` 中动态 import

**策略**：Phase 1a 期间不删除 `app/auth.py` 中的任何函数，auth 插件内部 import 并复用它们。Phase 1a 完成后再做一次清理 PR 将底层函数移到插件内部（不在本阶段范围）。

### P1a.2 实现 AuthPlugin

**新增目录**：`backend/app/plugins/builtin/auth/`

```
backend/app/plugins/builtin/auth/
├── __init__.py              # from .plugin import AuthPlugin
├── plugin.py                # AuthPlugin 主类
├── models.py                # UserModel ORM（替代 text() DDL）
├── router.py                # /auth/* 路由
├── middleware.py            # Cookie+CSRF 认证中间件
├── setup.py                 # /setup 端点逻辑
├── password.py              # 复用 app/auth.py 的 hash/verify，或升级到 bcrypt
├── jwt_utils.py             # JWT 签发/验证（复用 app/auth.py 的 create_jwt/verify_jwt）
├── csrf.py                  # CSRF token 生成/验证
└── migrations/
    └── 0005_add_user_columns_setup.py  # Alembic 迁移
```

**AuthPlugin 类实现**：

```python
# plugin.py
from app.plugins.core.types import (
    PluginBase, PluginTier, PluginContext, PluginHealth,
    LifecycleMixin, RouterMixin, MiddlewareMixin,
)
from app.plugins.core.hooks.lifecycle import LifecycleMixin as _LM, RouterMixin as _RM, MiddlewareMixin as _MM

class AuthPlugin(PluginBase, _LM, _RM):
    name = "auth"
    version = "1.0.0"
    tier = PluginTier.CORE
    dependencies = []   # auth 是最基础的 CORE 插件，无依赖
    priority = 0       # 最先加载
    
    def __init__(self):
        self._users_cache: dict[str, dict] = {}
        self._jwt_secret: str = ""
        self._setup_token_hash: str | None = None
        self._setup_token_expires_at: float = 0
    
    async def on_startup(self, ctx: PluginContext) -> None:
        """初始化：建表、加载用户、确保 JWT secret、处理 setup token"""
        await self._ensure_schema()           # 用 SQLAlchemy ORM create_all 或 Alembic
        await self._load_users_from_db()
        self._jwt_secret = self._ensure_jwt_secret()
        await self._check_initial_setup(ctx)  # 无用户时生成 setup token 并打印到 stdout
    
    async def on_shutdown(self, ctx: PluginContext) -> None:
        """清理资源（当前无需要清理的）"""
        pass
    
    async def health_check(self) -> PluginHealth:
        """简单检查：能否查询 users 表"""
        try:
            from app.db.engine import async_session_factory
            from sqlalchemy import text
            async with async_session_factory() as s:
                await s.execute(text("SELECT 1"))
            return PluginHealth(healthy=True)
        except Exception as e:
            return PluginHealth(healthy=False, message=str(e))
    
    def register_routers(self, app: FastAPI) -> None:
        """挂载 /auth/* 和 /setup 路由"""
        from .router import router as auth_router
        from .setup import setup_router
        app.include_router(auth_router)
        app.include_router(setup_router)
    
    def register_middlewares(self, app: FastAPI) -> None:
        """注册认证中间件（替代 app/middleware.py 中的 JWT Bearer 部分）"""
        from .middleware import setup_auth_cookie_middleware
        setup_auth_cookie_middleware(app, self)
```

**JWT 签发/验证**：
- Phase 1a 初期复用 `app/auth.py` 中的 `create_jwt()`/`verify_jwt()`（HMAC-SHA256）；
- 不急于切换到 bcrypt——现有 PBKDF2-600000 已符合 OWASP 标准，保持现有密码哈希不变，避免强制用户重置密码；
- 如果后续要切换到 bcrypt，可在登录时做透明升级（类似现有 PBKDF2 迭代次数升级机制）。

**中间件逻辑**（`middleware.py`）：
- 替换现有 `setup_auth_middleware()` 中从 `Authorization: Bearer` 读 JWT 的部分；
- Phase 1a 过渡期：**同时支持** Cookie 和 Authorization header（见 P1a.3）；
- 中间件在认证成功后设置 `request.state.auth_user` + ContextVars（`set_user_id`/`set_username`/`set_user_role`）——与现有行为一致，下游代码无感；
- 公开路径列表 `_PUBLIC_PATHS` 从硬编码迁移到 auth 插件中，并新增 `/setup`、`/setup/status` 为公开路径；
- dev token 兼容逻辑保留（`CONCLAVE_API_TOKEN`/`.dev_token`），在 auth 插件中实现；
- 速率限制（`_check_rate_limit`）继续在 `app/middleware.py` 中，不迁移到 auth 插件（它是独立的横切关注点，未来属于 ratelimit 插件）。

### P1a.3 HttpOnly Cookie 迁移

**JWT 签发逻辑修改**（在 auth 插件的 `router.py` 登录端点中）：

登录成功后，不再在 JSON 响应体中返回 `access_token`，改为通过 `Set-Cookie` 响应头设置：

```python
from fastapi import Response

@router.post("/login")
async def login(req: LoginRequest, request: Request, response: Response):
    user = await authenticate_user(req.username, req.password)
    if not user:
        # ... 失败处理（记审计日志、记录失败速率）...
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    
    # 签发 token
    access_token = create_access_token(user, expires_in=900)   # 15 分钟短期 access
    refresh_token = create_access_token(user, expires_in=2592000, token_type="refresh")  # 30 天 refresh
    csrf_token = secrets.token_urlsafe(32)
    
    # 设置 Cookie
    secure = not _is_dev_env()
    response.set_cookie(
        key="access_token", value=access_token,
        httponly=True, secure=secure, samesite="strict",
        path="/", max_age=900,
    )
    response.set_cookie(
        key="refresh_token", value=refresh_token,
        httponly=True, secure=secure, samesite="strict",
        path="/api/auth", max_age=2592000,
    )
    response.set_cookie(
        key="csrf_token", value=csrf_token,
        httponly=False, secure=secure, samesite="strict",
        path="/", max_age=2592000,
    )
    
    # 重置失败计数、审计日志...
    return {"success": True, "user": {...}}
```

**CSRF 中间件**（在 auth 插件的 `middleware.py` 中）：
- 对 POST/PUT/PATCH/DELETE 请求，校验 Header `X-CSRF-Token` 与 Cookie `csrf_token` 一致；
- GET/HEAD/OPTIONS 请求跳过 CSRF 校验；
- 公开路径（/auth/login、/setup 等）跳过 CSRF 校验；
- CSRF 失败返回 403。

**认证中间件 Token 提取优先级**（过渡期）：
1. 从 Cookie `access_token` 读取（新方式）；
2. 从 Header `Authorization: Bearer <token>` 读取（旧方式，兼容未更新的前端/API 调用）；
3. 从 Header `Authorization: Token <token>` 读取（dev token 兼容）；
4. WebSocket 握手从 Cookie 读取（替代 URL query 参数）。

**配置开关**：
- `CONCLAVE_AUTH_COOKIE_ONLY=1`：禁用 Bearer header 兼容（生产环境推荐）；
- 默认（未设置）：同时支持 Cookie 和 Bearer header（过渡期）。

**前端 axios 拦截器修改**（前端项目在 `archive/frontend-react-original/src/lib/api.ts`）：
- 移除 `headers.Authorization = \`Bearer ${token}\`` 注入逻辑；
- 请求拦截器：从 `document.cookie` 解析 `csrf_token`，对非 GET 请求设置 `X-CSRF-Token` header；
- 响应拦截器：捕获 401 → 尝试 `POST /api/auth/refresh`（浏览器自动携带 refresh_token Cookie）→ 重试原请求；
- 使用"刷新锁"（Promise 单例）防止并发请求触发多次 refresh；
- refresh 也失败 → 清除本地状态、跳转登录页。

**登出端点**：
```python
@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/api/auth")
    response.delete_cookie("csrf_token", path="/")
    return {"success": True}
```

**Token 刷新端点**：
```python
@router.post("/auth/refresh")
async def refresh(request: Request, response: Response):
    """从 refresh_token Cookie 读取并签发新 access_token"""
    # 验证 refresh_token → 签发新 access_token（15min）→ Set-Cookie
    # 可选：refresh token 轮换（每次刷新签发新 refresh_token，旧的加入黑名单）
```

### P1a.4 Setup 流程实现

**端点设计**：

1. **`GET /api/setup/status`**（公开，无需认证）：
   ```json
   {
     "has_admin": false,
     "setup_required": true,
     "setup_token_hint": "stk_***"  // 仅在 dev 环境返回部分提示，生产不返回
   }
   ```
   实现：查询 users 表是否存在 role='admin' 的用户。

2. **`POST /api/setup`**（公开，速率限制）：
   请求体：`{ "setup_token": "stk_xxx", "username": "admin", "password": "xxx", "display_name": "系统管理员" }`
   - 验证 setup_token（哈希比对 + 过期检查）；
   - 创建首个 admin 用户；
   - 立即签发 session（Set-Cookie），返回 `{ "success": true, "user": {...} }`；
   - setup token 立即失效。

**Setup Token 逻辑**：

- **生成时机**：`AuthPlugin.on_startup()` 中，检测到 users 表无 admin 用户时：
  1. 生成 `stk_` + 32字节 urlsafe 随机值；
  2. 计算 SHA-256 哈希存入 `self._setup_token_hash`；
  3. 设置过期时间 `time.time() + 86400`（24小时）；
  4. **同时打印到 stdout**（logger.warning 级别醒目标记）：
     ```
     ============================================================
     ⚠️  Conclave 首次启动，未检测到管理员用户
     ⚠️  Setup Token: stk_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
     ⚠️  请在 24 小时内访问 /setup 页面完成初始化
     ⚠️  此 Token 仅显示一次，请妥善保存
     ============================================================
     ```
  5. 同时写入数据库 `plugin_states` 表（见下文）使多副本部署一致。

- **环境变量覆盖**：
  - `CONCLAVE_SETUP_ADMIN_TOKEN=stk_xxx`：直接使用指定的 token（适合自动化部署脚本）；
  - `CONCLAVE_SETUP_ADMIN_USERNAME=admin` / `CONCLAVE_SETUP_ADMIN_PASSWORD=xxx`：如果同时提供，启动时自动创建管理员（跳过交互式 setup，适合 CI/Docker 初始化）；
  - 自动创建成功后在日志中提示"已通过环境变量创建默认管理员"。

- **速率限制**：`/api/setup` 端点使用独立于登录的速率限制——同一 IP 10 分钟内最多 5 次尝试（可复用 `app/middleware.py` 的 `_check_rate_limit` 模式，但用独立的计数器）。

- **Setup Token 24h 过期**：过期后拒绝使用，运维需重启服务或通过 DB 操作重新生成。也提供管理员重新生成的 API（`POST /api/admin/setup-token/regenerate`，Phase 1a 可选实现）。

- **存储**：Phase 1a 先用内存存储（`self._setup_token_hash` + `self._setup_token_expires_at`），单实例部署足够。后续 Phase 2 可持久化到 `plugin_states` 表（team-management-design.md §3.1 已规划此表）。

**前端 /setup 页面**（`archive/frontend-react-original/src/pages/SetupPage.tsx`）：
- 应用加载时先调 `GET /api/setup/status`；
- 如果 `setup_required === true`，跳转 `/setup` 页面（不经过登录守卫）；
- 页面包含：Token 输入框、用户名、密码、确认密码、显示名称；
- 提交后调 `POST /api/setup`；
- 成功后自动登录并跳转 Dashboard；
- 如果已有 admin，访问 `/setup` 直接跳首页。

### P1a.5 User 模型和 BYOK 表

**新建 Auth 插件的 ORM 模型**（`plugin.py` 同目录的 `models.py`，但使用核心 `Base`）：

**注意**：当前 `app/auth.py` 中 `_init_users_table()` 通过 `text()` DDL 建表，字段为：
```sql
id SERIAL PRIMARY KEY,
username VARCHAR(64) UNIQUE NOT NULL,
password_hash VARCHAR(256) NOT NULL,
role VARCHAR(32) NOT NULL DEFAULT 'user',
display_name VARCHAR(128),
is_active BOOLEAN NOT NULL DEFAULT TRUE,
created_at TIMESTAMP NOT NULL DEFAULT NOW(),
last_login_at TIMESTAMP
```

Auth 插件不新建 `users` 表（表已存在），而是**创建对应的 SQLAlchemy ORM 模型**映射到现有表，并通过 Alembic 迁移添加新列：

```python
# plugins/builtin/auth/models.py
from sqlalchemy import String, Boolean, DateTime, Integer, Text, BigInteger
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base
from datetime import datetime, timezone

class UserModel(Base):
    __tablename__ = "users"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="user")
    display_name: Mapped[str | None] = mapped_column(String(128))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Phase 1a 新增：个人 BYOK 字段（ADR-008）
    personal_llm_provider: Mapped[str | None] = mapped_column(String(50))
    personal_llm_base_url: Mapped[str | None] = mapped_column(String(500))
    personal_llm_model: Mapped[str | None] = mapped_column(String(100))
    personal_llm_key_encrypted: Mapped[str | None] = mapped_column(Text)  # Fernet 加密
    byok_auto_fallback: Mapped[bool] = mapped_column(Boolean, default=True)
    byok_allow_others_meetings: Mapped[bool] = mapped_column(Boolean, default=False)
    email: Mapped[str | None] = mapped_column(String(255))  # Setup 流程可选用
```

**关于独立 `user_api_keys` 表的决策**：

查看 design doc §3.1，用户个人 BYOK 是作为 `users` 表的列（`personal_llm_api_key_encrypted` 等）存储的，而不是独立表。现有 `api_keys` 表（`ApiKeyModel` in `db/models/user.py`）是全局 provider key 表（无 user_id 外键）。为保持简洁并与 design doc 一致，Phase 1a 采用 design doc 的方案：个人 BYOK 字段直接加在 users 表上。全局 provider key 表（`api_keys`）继续保留供管理员配置系统级 key。

**Alembic 迁移**（`backend/alembic/versions/0005_auth_upgrade.py`）：
```python
"""auth plugin upgrade: users 表扩展 + setup 状态列
"""
from alembic import op
import sqlalchemy as sa

def upgrade():
    # 为现有 users 表添加新列（IF NOT EXISTS 防止重复）
    op.add_column('users', sa.Column('email', sa.String(255), nullable=True))
    op.add_column('users', sa.Column('personal_llm_provider', sa.String(50), nullable=True))
    op.add_column('users', sa.Column('personal_llm_base_url', sa.String(500), nullable=True))
    op.add_column('users', sa.Column('personal_llm_model', sa.String(100), nullable=True))
    op.add_column('users', sa.Column('personal_llm_key_encrypted', sa.Text, nullable=True))
    op.add_column('users', sa.Column('byok_auto_fallback', sa.Boolean, nullable=False, server_default=sa.text('true')))
    op.add_column('users', sa.Column('byok_allow_others_meetings', sa.Boolean, nullable=False, server_default=sa.text('false')))

def downgrade():
    op.drop_column('users', 'byok_allow_others_meetings')
    op.drop_column('users', 'byok_auto_fallback')
    op.drop_column('users', 'personal_llm_key_encrypted')
    op.drop_column('users', 'personal_llm_model')
    op.drop_column('users', 'personal_llm_base_url')
    op.drop_column('users', 'personal_llm_provider')
    op.drop_column('users', 'email')
```

**KeyEncryption 类**：
- Phase 1a **复用现有的** `app/services/key_store.py` 中的 `encrypt_key()`/`decrypt_key()`（Fernet 对称加密）；
- 不新建 AES-256-GCM 实现——Fernet 内部使用 AES-128-CBC + HMAC-SHA256，安全性足够，且避免维护两套加密体系；
- 个人 Key 加密复用同一个 `CONCLAVE_SECRET_KEY` 派生的密钥；
- 日志中禁止打印明文 Key，统一通过 `_mask_key()` 脱敏显示。

**主密钥加载逻辑**：现有 key_store.py 已实现：环境变量 `CONCLAVE_SECRET_KEY` → 数据目录 `.secret_key` 文件 → 自动生成。Auth 插件直接复用，无需重复实现。

### P1a.6 重构现有认证引用

**策略**：Auth 插件注册后，通过中间件和路由"吸收"认证职责，但**不删除** `app/auth.py` 和 `app/routers/auth.py`，改为薄包装层。

1. **`app/routers/auth.py`**：删除原有路由定义，改为从 auth 插件 re-export：
   ```python
   # 过渡期：从 auth 插件导入 router，保持 include_router 路径不变
   from app.plugins.builtin.auth.router import router
   ```
   这样 `main.py` 中现有的 `app.include_router(auth_router.router)` 不需要修改。后续 Phase 2 再移除这些 shim。

2. **`app/middleware.py`**：在 `setup_auth_middleware()` 中，检测 auth 插件是否已加载：
   ```python
   def setup_auth_middleware(app: FastAPI) -> None:
       # 如果 auth 插件已加载并注册了中间件，跳过内置认证中间件
       registry = getattr(app.state, "plugin_registry", None)
       if registry and registry.is_registered("auth") and registry.get_plugin("auth").state == PluginState.READY:
           # Auth 插件会注册自己的中间件，这里只保留速率限制和公开路径定义
           _register_rate_limit_only_middleware(app)
           return
       # 否则走原有完整认证逻辑（向后兼容）
       _register_legacy_auth_middleware(app)
   ```
   但这会增加复杂度。Phase 1a 更简单的做法：**保留 `setup_auth_middleware` 不动**，auth 插件的中间件在它之后注册（FastAPI 中间件栈是后注册先执行），auth 插件中间件优先从 Cookie 认证并设置 `request.state.auth_user`；如果 Cookie 不存在，旧中间件继续从 Bearer header 认证。两套中间件并存，通过 `getattr(request.state, "auth_user", None)` 检查——如果已经设置了用户，旧中间件直接放行。

3. **`app/auth.py` 中的 `init_auth()`**：
   - 当 auth 插件启用时，`init_auth()` 中的建表逻辑被插件的 ORM 迁移替代；
   - 但为安全起见，保留 `init_auth()` 函数调用（在 lifespan 中），内部检测 users 表是否已由插件创建——如果已存在则跳过。
   - 更简单的方式：auth 插件 `on_startup()` 调用现有的 `init_auth()` 复用其逻辑（加载用户到内存缓存、创建默认管理员——但默认管理员逻辑在 setup 流程存在时不执行）。

4. **验证所有现有功能**：
   - 现有测试 `tests/test_middleware_security.py` 应继续通过；
   - 登录流程（用 Bearer token 方式）仍可工作（过渡期兼容）；
   - WebSocket 连接（`routers/ws.py` 中使用 `verify_ws_token()`）应继续工作。

### P1a.7 前端适配

前端代码位于 `archive/frontend-react-original/src/`（当前主前端）。修改清单：

1. **axios 拦截器**（`lib/api.ts`）：
   - 删除 `localStorage.getItem('token')` 读取和 Authorization header 注入；
   - 添加 CSRF token 读取和注入（从 cookie 解析 `csrf_token`，加到 `X-CSRF-Token` header）；
   - 添加 401 响应拦截：自动 refresh token 流程（带刷新锁）；
   - withCredentials: true（允许跨域携带 Cookie）。

2. **AuthContext**（`store/AuthContext.tsx`）：
   - 不再在 localStorage 存储 token；
   - 登录成功后不需要保存 token（浏览器自动管理 Cookie）；
   - 初始化时调用 `GET /api/auth/me` 检查是否已有 session；
   - logout 调用 `POST /api/auth/logout`。

3. **导航栏适配**：
   - 根据 AuthContext 的 user 状态显示登录/登出按钮；
   - 未登录时显示"登录"按钮跳登录页；
   - 已登录显示用户菜单（个人设置/BYOK/登出）。

4. **BYOK 设置页面**：
   - 新增"个人设置 → API Key"页面；
   - 表单：Provider 选择、API Key 输入、Base URL（可选）、模型（可选）；
   - 两个开关："配额耗尽时自动使用我的 Key"、"允许我的 Key 为他人会议兜底"；
   - 调用 `PUT /api/auth/me/byok`（auth 插件新增端点）。

5. **/setup 初始化页面**（`pages/SetupPage.tsx`）：
   - 简洁的管理员创建表单；
   - 从 URL query 或手动输入 setup token（首次启动时终端会显示）；
   - 密码强度校验；
   - 成功后自动跳转到 Dashboard。

6. **CORS 配置确认**：
   - 后端 `create_app()` 中 CORS `allow_credentials=True` 已设置（见现有代码 `_allow_credentials = _cors_origins != ["*"]`）；
   - 确保 `allow_origins` 列表显式包含前端地址，不用 `*`；
   - `allow_headers` 添加 `X-CSRF-Token`。

### Phase 1a 验收标准

- [ ] 登录/登出/注册正常工作（Cookie 方式）
- [ ] JWT 存储在 HttpOnly Cookie 中（access_token=15min, refresh_token=30d）
- [ ] CSRF double-submit cookie 防护工作（POST 无 CSRF token 返回 403）
- [ ] 过渡期 Bearer header 认证仍可工作（配置开关控制）
- [ ] /setup 流程完整可走通（无管理员时访问 /setup 创建管理员）
- [ ] Setup Token 24h 过期、一次性使用、速率限制 5次/10分钟/IP
- [ ] 环境变量 `CONCLAVE_SETUP_ADMIN_PASSWORD` 可自动创建管理员
- [ ] BYOK 加密存储可存取（个人 Key 用 Fernet 加密存入 users 表新列）
- [ ] 前端登录状态持久化（刷新页面不需要重新登录，直到 Cookie 过期）
- [ ] 前端 401 自动 refresh token 流程工作
- [ ] 现有所有功能（会议 CRUD、WS 连接、成本统计等）不受影响
- [ ] 不加载 team/billing 插件时系统正常运行（auth 独立可用）

---

## Phase 1b: 核心钩子植入 + Billing 插件提取（第3周）

Phase 1b 的目标：在核心 LLM 调用链和会议生命周期中植入钩子点；给 meetings 表加 metadata 列；将 CostTracker 提取为 billing 插件；标准化错误处理；添加插件健康检查端点。

### P1b.1 meetings 表添加 metadata 列

**Alembic 迁移**（`backend/alembic/versions/0006_meetings_metadata.py`）：

```python
"""meetings 表添加 metadata JSONB 列
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

def upgrade():
    op.add_column('meetings', sa.Column(
        'metadata', JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
    ))
    # GIN 索引（核心只创建一个通用 GIN 索引，插件按需自建 Partial Index）
    op.execute('CREATE INDEX IF NOT EXISTS idx_meetings_metadata_gin ON meetings USING GIN (metadata)')

def downgrade():
    op.execute('DROP INDEX IF EXISTS idx_meetings_metadata_gin')
    op.drop_column('meetings', 'metadata')
```

**修改 MeetingModel**（`backend/app/db/models/meeting.py`）：
```python
# 在 MeetingModel 类中添加字段：
from sqlalchemy.dialects.postgresql import JSONB
metadata: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
```

**修改 MeetingState 领域模型**（`backend/app/domain/meeting.py`，如有）：添加 `metadata: dict[str, Any] = field(default_factory=dict)`。

**修改会议创建/加载逻辑**：
- 创建会议时：初始化 `metadata={}`；
- 从 DB 加载时：读取 metadata 列并注入 MeetingState（核心不解读内容，仅透传）；
- 序列化/反序列化 payload 时：metadata 作为独立列，不放入 payload JSON（与 ADR-002 一致：payload 存 MeetingState 的其他字段，metadata 独立）；
- 需要检查当前 MeetingState 的序列化逻辑——当前所有 MeetingState 都存在 `payload` TEXT 列中（JSON 字符串）。Phase 1b 不重构 payload，仅在 MeetingModel 层面增加 metadata 列，MeetingState 对象增加 metadata 字段，创建/加载时读写 metadata 列。

**验证**：
- 现有会议数据不受影响（新列默认 `'{}'::jsonb`）；
- 现有查询（SELECT meetings）不需要修改，ORM 自动包含 metadata 列；
- 不加载任何插件时，metadata 始终为空对象 `{}`；
- 回滚迁移（downgrade）后系统仍可运行（metadata 列被删除）。

### P1b.2 LLM 调用链钩子植入

**修改文件**：`backend/app/agents/llm.py`

这是 Phase 1b 最敏感的修改。核心原则：**无插件时钩子调用开销可忽略（<1ms），行为逐行等价于修改前**。

**植入点 1：`RealLLM.complete()` 方法开头（熔断器检查之后、模型解析之前）——触发 `on_llm_pre_call` 拦截型钩子**：

```python
async def complete(self, prompt: str, schema_hint: str = "",
                   model_override: str = "", agent_role: str = "") -> dict[str, Any]:
    # 熔断器检查（保持原样）
    if not _circuit_breaker.can_call():
        # ... 原有降级逻辑不变 ...
        return await StubLLM().complete(prompt, schema_hint)
    
    # ===== 新增：插件钩子 on_llm_pre_call =====
    from app.plugins import get_registry
    from app.plugins.core.types import PluginContext
    from app.plugins.core.hooks.llm import LLMRequest, LLMOverride
    registry = get_registry()
    active_overrides: dict = {}  # 记录钩子返回的 override
    if registry and registry.has_plugins():
        from app.context import get_request_id, get_meeting_id
        _base, _key, _model = self._resolve_config()
        llm_req = LLMRequest(
            prompt=prompt, schema_hint=schema_hint,
            model=model_override or _model or self.model,
            base_url=_base or self.base_url,
            api_key=_key or self.api_key,
            agent_role=agent_role, stage=schema_hint,
            meeting_id=get_meeting_id(), request_id=get_request_id(),
        )
        ctx = PluginContext(app=None, registry=registry, request_id=get_request_id())
        try:
            result = await registry.fire_interceptor(
                "on_llm_pre_call", ctx, llm_req, default=None
            )
            if isinstance(result, LLMOverride):
                if result.api_key: llm_req.api_key = result.api_key
                if result.base_url: llm_req.base_url = result.base_url
                if result.model: llm_req.model = result.model
                active_overrides = {"source": "plugin_override"}
                logger.debug("LLM pre_call override applied: model=%s", llm_req.model)
        except Exception as e:
            from fastapi import HTTPException
            if isinstance(e, HTTPException):
                raise
            logger.warning("on_llm_pre_call hook error (continuing with defaults): %s", e)
        # 用（可能被覆盖的）参数继续后续流程
        _effective_base = llm_req.base_url
        _effective_key = llm_req.api_key
        _effective_model = llm_req.model
    else:
        _effective_base, _effective_key, _effective_model = self._resolve_config()
    # ===== 钩子植入结束 =====
    
    # ... 原有代码继续（schema_desc、stage、temp 等保持不变）...
    # 注意：后续 _resolve_config() 调用点需要改为使用 _effective_* 变量
    # （或者封装 _resolve_config 检查插件 override）
```

为最小化对现有代码的侵入，采用更保守的方案：**不修改后续的 provider fallback 链逻辑**，而是修改 `_resolve_config()` 方法本身：

```python
def _resolve_config(self) -> tuple[str, str, str]:
    """解析当前调用应使用的 (base_url, api_key, model)"""
    # 1. 原有逻辑：会议级覆盖
    try:
        from app.context import get_meeting_id
        from app.llm_providers import get_meeting_llm_config
        mid = get_meeting_id()
        if mid and mid != "-":
            base_url, api_key, model, _pid = get_meeting_llm_config(mid)
            if base_url and api_key and model:
                base, key, mdl = base_url, api_key, model
            else:
                base, key, mdl = self.base_url, self.api_key, self.model
        else:
            base, key, mdl = self.base_url, self.api_key, self.model
    except Exception:
        base, key, mdl = self.base_url, self.api_key, self.model
    
    # 2. 新增：插件 override（通过 ContextVar 在 pre_call 中设置）
    try:
        override = _get_llm_override()  # ContextVar
        if override:
            if override.get("api_key"): key = override["api_key"]
            if override.get("base_url"): base = override["base_url"]
            if override.get("model"): mdl = override["model"]
    except Exception:
        pass
    return base, key, mdl
```

这样 `on_llm_pre_call` 钩子的结果通过 ContextVar 传递给 `_resolve_config()`，避免在 `complete()` 方法中大范围重构。

**植入点 2：`_call_api()` 方法中，成功获得 LLM 响应、解析 token 用量之后——触发 `on_llm_post_call` 观察型钩子**：

在 `_call_api()` 末尾（return content 之前），在现有 `record_call()` 和 `get_cost_tracker().record_llm()` 之后：

```python
# ===== 新增：插件钩子 on_llm_post_call（观察型）=====
try:
    from app.plugins import get_registry
    from app.plugins.core.hooks.llm import LLMResponse, LLMUsage
    registry = get_registry()
    if registry and registry.has_plugins():
        from app.observability.cost_tracker import estimate_llm_cost
        from app.context import get_request_id, get_meeting_id
        cost = estimate_llm_cost(model, input_tokens, output_tokens)
        llm_resp = LLMResponse(
            content=content, parsed=None,
            model=model, provider=provider_id or "default",
        )
        llm_usage = LLMUsage(
            input_tokens=input_tokens, output_tokens=output_tokens,
            total_tokens=total_tokens, latency_ms=latency_ms,
            cost_usd=cost,
        )
        llm_req = LLMRequest(
            prompt=user_prompt, schema_hint=stage,
            model=model, base_url=base_url, api_key="***",  # 不传递明文 key
            agent_role=agent_role, stage=stage,
            meeting_id=get_meeting_id(), request_id=get_request_id(),
        )
        ctx = PluginContext(app=None, registry=registry, request_id=get_request_id())
        # 观察型钩子：不阻塞，不抛异常
        import asyncio
        asyncio.create_task(
            registry.fire_observer("on_llm_post_call", ctx, llm_req, llm_resp, llm_usage)
        )
except Exception:
    pass  # 钩子异常绝不影响主流程
```

Wait——`_call_api` 是 async 函数，可以直接 await observer 而不用 create_task。但 Observer 钩子设计上不阻塞主流程，且 `fire_observer` 内部已有超时保护，所以直接 await 即可（超时 200ms 后自动跳过）：

```python
await registry.fire_observer("on_llm_post_call", ctx, llm_req, llm_resp, llm_usage)
```

但 `_call_api` 的调用方 `complete()` 中，对每个 attempt 都会调用 `_call_api`，在重试循环中 await observer 会增加 200ms 潜在延迟。因此改为 **asyncio.create_task**（在 complete() 的成功路径中 await 更合适）。

更简洁的方案：在 `complete()` 方法中，`_call_api` 成功并解析 validated 之后（`_circuit_breaker.record_success()` 之后）触发 `on_llm_post_call`。这样只在最终成功时触发一次，不在重试中重复触发。

**植入点 3：`complete()` 方法中，LLM 调用失败（异常捕获块）——触发 `on_llm_error` 拦截型钩子**：

在 `complete()` 的 provider 回退循环中，当捕获到可降级错误（HTTP 402/429 配额相关）时：

```python
except (httpx.ConnectError, httpx.TimeoutException) as conn_err:
    # ===== 新增：插件钩子 on_llm_error =====
    try:
        from app.plugins import get_registry
        registry = get_registry()
        if registry and registry.has_plugins():
            from app.plugins.core.hooks.llm import LLMErrorInfo, LLMFallback
            err_info = LLMErrorInfo(
                error_type="connection", status_code=None,
                message=str(conn_err)[:200], raw_error=conn_err,
            )
            ctx = PluginContext(app=None, registry=registry, request_id=get_request_id())
            fallback = await registry.fire_interceptor(
                "on_llm_error", ctx, llm_req, err_info, default=None
            )
            if isinstance(fallback, LLMFallback) and (fallback.api_key or fallback.base_url or fallback.model):
                # 用 fallback 提供的 key/model 重试当前 provider 迭代
                # 将 fallback 参数构造为新的 config_override 并继续循环
                config_override = (
                    fallback.base_url or _p_url,
                    fallback.api_key or _p_key,
                    fallback.model or _p_model,
                )
                provider_id = "fallback"
                continue  # 重试当前 attempt 编号（或重置 attempt）
    except Exception as hook_err:
        logger.warning("on_llm_error hook failed: %s", hook_err)
    # 原有连接错误处理（break 到下一个 provider）
    last_error = f"{_p_id}: {type(conn_err).__name__}: {conn_err}"
    break
```

对于 HTTP 429/402 配额错误（在 `httpx.HTTPError` 捕获块中），类似地触发 `on_llm_error` 并检查 LLMFallback。

**钩子超时处理**：所有钩子调用都经过 `fire_interceptor`/`fire_observer`，默认 200ms 超时，超时后走默认行为（继续原有逻辑）。

**验证**：
- 无插件时（registry.has_plugins() 返回 False），新增的 import 和 if 分支开销 <0.1ms（属性检查 + 分支预测）；
- LLM 调用行为与修改前完全一致（同样的重试、同样的 fallback 到 StubLLM、同样的熔断器逻辑）；
- 现有 LLM 测试（`tests/test_llm_temperature.py`、`tests/test_real_llm_e2e.py` 等）全部通过。

### P1b.3 会议生命周期钩子植入

**修改文件**：`backend/app/routers/meetings.py`（会议 CRUD 端点）、`backend/app/dao/meeting_dao.py`（会议创建 DAO）

**植入点 1：创建会议端点——`on_meeting_creating` 拦截型钩子**

在创建会议的 POST 端点中，在会议持久化之前：

```python
@router.post("")
async def create_meeting(req: CreateMeetingRequest, request: Request):
    # ... 参数解析、auth_user 获取 ...
    
    # ===== 新增：插件钩子 on_meeting_creating =====
    registry = get_registry()
    metadata_patch: dict = {}
    if registry and registry.has_plugins():
        ctx = PluginContext(app=request.app, registry=registry, request_id=get_request_id())
        payload_dict = req.model_dump()
        # 为钩子提供 metadata_patch 通道
        ctx.extra["metadata_patch"] = metadata_patch
        try:
            await registry.fire_interceptor("on_meeting_creating", ctx, payload_dict)
        except HTTPException:
            raise  # Fallback 直接抛出
        except Exception as e:
            logger.warning("on_meeting_creating hook error: %s", e)
    
    # ... 原有会议创建逻辑 ...
    # 创建 MeetingModel 时，metadata = metadata_patch 或 {}
    meeting = MeetingModel(
        id=new_id,
        topic=req.topic,
        owner_username=auth_user["username"],
        # ... 其他字段 ...
        metadata=metadata_patch or {},
    )
```

**植入点 2：会议访问端点（GET /meetings/{id}、WS 连接等）——`on_meeting_accessing` 拦截型钩子**

在获取会议对象之后、返回/使用之前：

```python
# 加载会议后
meeting = await meeting_dao.get_meeting(meeting_id)
if not meeting:
    raise HTTPException(404, "会议不存在")

# ===== 新增：插件钩子 on_meeting_accessing =====
if registry and registry.has_plugins():
    ctx = PluginContext(app=request.app, registry=registry, request_id=get_request_id())
    try:
        await registry.fire_interceptor("on_meeting_accessing", ctx, meeting)
    except HTTPException:
        raise
```

植入位置：
- `GET /meetings/{id}`（获取会议详情）
- `POST /meetings/{id}/run`（开始会议）
- `POST /meetings/{id}/control`（会议控制）
- WebSocket `WS /ws/meetings/{id}` 连接建立时
- 以及所有访问会议的关键端点（documents、workspace 等）

**植入点 3：会议创建成功后——`on_meeting_created` 观察型钩子**

在会议持久化并提交事务后：

```python
await session.commit()
# ===== 新增：插件钩子 on_meeting_created =====
if registry and registry.has_plugins():
    ctx = PluginContext(app=request.app, registry=registry, request_id=get_request_id())
    asyncio.create_task(
        registry.fire_observer("on_meeting_created", ctx, meeting.id, dict(meeting.metadata))
    )
```

注意使用 `asyncio.create_task` 避免阻塞创建响应。

**验证**：
- 无插件时，metadata 默认为 `{}`，钩子分支跳过，会议创建/访问行为与之前完全一致；
- 现有会议 CRUD 测试（`tests/test_core_flow.py`、`tests/test_e2e.py`）全部通过。

### P1b.4 提取 Billing 插件

**新增目录**：`backend/app/plugins/builtin/billing/`

```
backend/app/plugins/builtin/billing/
├── __init__.py
├── plugin.py            # BillingPlugin 主类
├── router.py            # /metrics/cost 相关路由（从 app/routers/metrics.py 中提取成本部分）
├── cost_service.py      # 成本记录逻辑（从 CostTracker 迁移）
└── models.py            # 成本记录模型（复用现有 CostRecordModel）
```

**BillingPlugin 类**：

```python
class BillingPlugin(PluginBase, LLMObserverMixin, _LM, _RM):
    name = "billing"
    version = "1.0.0"
    tier = PluginTier.CROSSCUTTING   # 横切关注点：失败可降级
    dependencies = ["auth?"]         # 软依赖 auth：auth 不存在时仍可记录成本但不关联用户
    priority = 50
    
    def __init__(self):
        self._tracker: CostTracker | None = None
    
    async def on_startup(self, ctx: PluginContext) -> None:
        # 复用现有 CostTracker，但由插件持有引用
        from app.observability.cost_tracker import get_cost_tracker
        self._tracker = get_cost_tracker()
    
    async def on_shutdown(self, ctx: PluginContext) -> None:
        # 异步刷盘剩余记录
        pass
    
    async def health_check(self) -> PluginHealth:
        # 检查成本记录 DB 写入是否正常
        return PluginHealth(healthy=True)
    
    async def on_llm_post_call(self, ctx: PluginContext, req: LLMRequest, resp: LLMResponse, usage: LLMUsage) -> None:
        """观察型钩子：记录 LLM 调用用量"""
        if not self._tracker:
            return
        await self._tracker.record_llm(
            node=req.stage,
            model=req.model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            latency_ms=usage.latency_ms,
            agent_role=req.agent_role,
        )
    
    def register_routers(self, app: FastAPI) -> None:
        from .router import router as billing_router
        app.include_router(billing_router)
```

**重构现有 `/metrics/cost` 路由**：
- 现有 `app/routers/metrics.py` 中的成本相关部分（`total_tokens`、`total_cost_usd`、`by_node`、`by_tool`）迁移到 billing 插件的 `router.py`（路径保持 `/metrics/cost` 或改为 `/billing/cost`）；
- 系统资源指标（CPU/内存/请求数等）保留在核心 `routers/metrics.py`，不属于任何插件；
- 过渡期：`routers/metrics.py` 的 `/metrics` 端点同时返回核心指标和从 billing 插件获取的成本数据（如果插件加载了）；如果 billing 插件未加载，成本部分返回空值。

**修改现有 CostTracker 直接调用点**：
- `app/agents/llm.py` 的 `_call_api()` 中直接调用 `get_cost_tracker().record_llm()` 的代码**保留不变**（作为核心内置的成本记录路径）；
- BillingPlugin 的 `on_llm_post_call` 钩子作为**补充**，未来可扩展（按团队/用户聚合、配额检查等）；
- Phase 2 再将 `llm.py` 中的直接调用改为通过钩子，移除核心对 CostTracker 的硬依赖；
- Phase 1b 期间两者并存不冲突（但会双重记录——需要避免）。

**避免双重记录**：在 BillingPlugin 的 `on_llm_post_call` 中检查一个标志位（ContextVar `_billing_recorded`），如果已在核心记录则跳过；或者反过来：在 `llm.py` 中检测 billing 插件是否已加载，如果已加载则不在 `_call_api` 中直接 record_llm，改由钩子统一处理。后者更干净：

```python
# 在 _call_api 中，原有的 cost tracker 调用改为：
try:
    from app.plugins import get_registry
    registry = get_registry()
    billing_loaded = registry and registry.has_plugins() and registry.get_plugin("billing") and registry.get_plugin("billing").state == PluginState.READY
except Exception:
    billing_loaded = False

if not billing_loaded:
    # Billing 插件未加载，核心直接记录成本
    from app.observability.cost_tracker import get_cost_tracker
    await get_cost_tracker().record_llm(...)
# else: billing 插件的 on_llm_post_call 会记录，不重复
```

**验证**：
- 加载 billing 插件后，`/metrics` 端点的成本数据与重构前一致；
- 不加载 billing 插件时，核心直接记录成本，功能正常（退化到现有行为）；
- 成本记录持久化到 DB（CostRecordModel）正常。

### P1b.5 错误处理标准化

**新增文件**：`backend/app/plugins/core/exceptions.py`

```python
from __future__ import annotations
from typing import Any
from fastapi import HTTPException

class ConclaveException(Exception):
    """Conclave 统一异常基类"""
    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 500,
        details: dict[str, Any] | None = None,
    ):
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        super().__init__(message)

class PluginRejectedError(ConclaveException):
    """插件拦截器 Fallback 转换而来"""
    def __init__(self, fallback):
        super().__init__(
            code=fallback.code,
            message=fallback.reason,
            status_code=fallback.status_code,
            details=fallback.details,
        )

class SetupRequiredError(ConclaveException):
    def __init__(self):
        super().__init__(code="SETUP_REQUIRED", message="系统尚未初始化", status_code=403)

class QuotaExceededError(ConclaveException):
    def __init__(self, message: str = "配额不足", details: dict | None = None):
        super().__init__(code="QUOTA_EXCEEDED", message=message, status_code=402, details=details)

class AccessDeniedError(ConclaveException):
    def __init__(self, message: str = "访问被拒绝", details: dict | None = None):
        super().__init__(code="ACCESS_DENIED", message=message, status_code=403, details=details)
```

**标准错误响应格式**：

```json
{
  "error": {
    "code": "QUOTA_EXCEEDED",
    "message": "团队配额不足，剩余 0 tokens",
    "details": { "team_id": "...", "remaining": 0 },
    "request_id": "req-abc123"
  }
}
```

**全局异常处理器注册**（在 `create_app()` 中或 auth 插件/核心中）：

```python
@app.exception_handler(ConclaveException)
async def conclave_exception_handler(request: Request, exc: ConclaveException):
    from app.context import get_request_id
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
                "request_id": get_request_id(),
            }
        },
    )

# 同时为 HTTPException 做适配，保持 response 格式一致（现有 FastAPI 默认格式是 {"detail": "..."}）
# 过渡期：保留现有 {"detail": "..."} 格式，新代码使用 ConclaveException
```

**插件钩子中异常的统一处理**：在 PluginRegistry 的 `fire_interceptor`/`fire_observer` 中：
- CORE 插件抛出的 `ConclaveException` 直接向上传播；
- CORE 插件抛出的其他 Exception：包装为 `ConclaveException(code="PLUGIN_ERROR", status_code=500)`；
- CROSSCUTTING/OPTIONAL 插件的异常：捕获并记录日志，不传播（Interceptor 视为 Next，Observer 跳过）。

### P1b.6 插件健康检查端点

**新增端点**（在核心 `main.py` 的 `/health` 旁边，或由 PluginRegistry 自动注册）：

```python
@app.get("/api/health/plugins", tags=["meta"])
async def health_plugins(request: Request) -> dict[str, Any]:
    registry: PluginRegistry | None = getattr(request.app.state, "plugin_registry", None)
    if not registry:
        return {"plugins": {}, "status": "no_plugin_system"}
    
    plugins: dict[str, Any] = {}
    for name, plugin in registry.get_all_plugins().items():
        health = registry.get_health(name)
        plugins[name] = {
            "tier": plugin.tier.value,
            "state": plugin.state.value if hasattr(plugin, 'state') else "unknown",
            "healthy": health.healthy if health else None,
            "message": health.message if health else "",
            "version": plugin.version,
        }
    
    # 整体状态：CORE 插件全部 healthy 才是 ok
    core_unhealthy = [
        name for name, p in plugins.items()
        if p["tier"] == "core" and p["healthy"] is False
    ]
    return {
        "status": "ok" if not core_unhealthy else "degraded",
        "plugins": plugins,
        "unhealthy_core": core_unhealthy,
    }
```

**健康检查周期**：PluginRegistry 内部每 30 秒执行一次健康检查（后台 asyncio Task），结果缓存到内存，端点直接返回缓存结果（不做实时检查，避免拖慢响应）。

**不健康插件告警日志**：
- CORE 插件不健康 → CRITICAL 级别日志，每 5 分钟重复告警一次（避免日志洪水）；
- CROSSCUTTING 插件不健康 → ERROR 级别日志；
- OPTIONAL 插件不健康 → WARN 级别日志；
- 健康状态从 healthy 变为 unhealthy 时立即记录一次；从 unhealthy 恢复为 healthy 时记录 INFO。

将此端点的健康信息也合并到现有 `/health` 端点的 `checks` 字典中（添加 `plugins` 键），方便运维监控。

### Phase 1b 验收标准

- [ ] meetings 表有 metadata JSONB 列，默认 `'{}'`，GIN 索引存在
- [ ] 现有会议数据不受影响（metadata 为空对象），现有会议 CRUD 测试全部通过
- [ ] LLM 调用链钩子植入完成：on_llm_pre_call（拦截）、on_llm_post_call（观察）、on_llm_error（拦截）
- [ ] 无插件时 LLM 调用行为与之前完全一致（重试、熔断、降级到 StubLLM、CostTracker 记录）
- [ ] 钩子超时（200ms）不导致 LLM 调用失败
- [ ] 会议钩子植入完成：on_meeting_creating、on_meeting_created、on_meeting_accessing
- [ ] 无插件时会议创建/访问/删除不受影响
- [ ] Billing 插件从核心提取为 CROSSCUTTING 插件，通过 on_llm_post_call 记录用量
- [ ] 加载 billing 插件时成本统计数据与重构前一致
- [ ] 不加载 billing 插件时核心回退到直接 CostTracker 记录，成本统计正常
- [ ] ConclaveException 基类定义，标准错误响应格式 `{error:{code,message,details,request_id}}`
- [ ] 全局异常处理器注册，插件钩子异常统一处理
- [ ] `/api/health/plugins` 端点返回各插件健康状态
- [ ] 健康检查后台任务 30 秒周期执行，不健康插件产生告警日志
- [ ] 所有现有测试通过（`pytest backend/tests/` 全绿）

---

## 跨阶段验证清单

在所有三个阶段完成后，进行端到端验证：

- [ ] **零插件模式**：`CONCLAVE_PLUGINS=""` 启动时：
  - 系统能正常启动；
  - 无认证插件时，所有 API 端点应返回 401（此时 auth 中间件会拒绝所有请求）——或通过 `CONCLAVE_DISABLE_AUTH=1` 环境变量开放（开发模式）；
  - 注意：实际零插件模式在生产中不可用，因为 auth 是 CORE 插件；Phase 0 期间零插件是合法状态（认证由原 middleware 处理）。
- [ ] **仅 auth 插件**：`CONCLAVE_PLUGINS="auth"` 启动时：
  - 登录/注册/logout/me 正常工作；
  - 会议 CRUD 正常；
  - LLM 调用正常（无 billing 时核心直接 CostTracker 记录）；
  - WebSocket 连接正常（Cookie 认证）。
- [ ] **auth + billing 插件**：`CONCLAVE_PLUGINS="auth,billing"` 启动时：
  - 成本统计正常（billing 插件接管记录）；
  - `/metrics` 端点显示成本数据；
  - LLM 调用不产生双重记录。
- [ ] **插件钩子超时保护**：
  - 模拟一个慢插件（钩子内 sleep 1s），验证 LLM 调用不失败；
  - 慢插件被标记为 DEGRADED。
- [ ] **插件卸载**：
  - 禁用 billing 插件后，metadata 列和 CostRecordModel 表保留不删除；
  - 系统回退到核心内置成本记录。
- [ ] **Setup 流程**：
  - 清空 users 表后重启，系统打印 setup token；
  - 通过 /setup 页面创建管理员成功；
  - setup token 一次性使用，过期后失效。
- [ ] **Cookie 认证**：
  - 登录后 Cookie 正确设置（HttpOnly、Secure、SameSite=Strict）；
  - CSRF 防护有效（无 CSRF token 的 POST 返回 403）；
  - 前端刷新页面后仍保持登录状态。

---

## 风险与缓解

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| 钩子植入破坏现有 LLM 重试/熔断逻辑 | 中 | 高 | 每个钩子点加单元测试（mock 插件返回 Override/Fallback/超时/异常）；无插件时走原有代码路径（if registry.has_plugins() 分支）；在 staging 环境对比重构前后 LLM 调用成功率、延迟分布 |
| Auth 迁移期间用户 session 失效 | 高 | 中 | 过渡期同时支持 Cookie 和 Bearer token（`CONCLAVE_AUTH_COOKIE_ONLY` 默认关闭）；前端发布分两次：先部署后端（兼容双模式），再部署前端（使用 Cookie）；提供"退出重新登录"的友好提示 |
| CostTracker 重构导致双重记录或漏记 | 中 | 中 | 重构前后对比：记录相同 prompt、相同模型下的 token 计数和 cost_usd；添加断言测试：billing 插件加载后 `_call_api` 中不直接调用 record_llm |
| metadata 迁移锁定 meetings 表 | 低 | 中 | `ALTER TABLE ADD COLUMN ... DEFAULT '{}'` 在 PostgreSQL 中是轻量操作（不会重写全表，因为默认值是常量）；GIN 索引创建使用 `CONCURRENTLY`（如果需要）；在低峰期执行迁移 |
| PluginRegistry 实例化与现有全局单例模式冲突 | 低 | 中 | PluginRegistry 本身是实例，但提供 `set_global_registry()`/`get_registry()` 便捷函数；不强制使用 DI 容器；现有代码通过 `get_registry()` 获取实例，返回 None 时安全降级 |
| 钩子超时 200ms 对某些需要 I/O 的插件不够 | 中 | 低 | 超时可配置（`CONCLAVE_PLUGIN_HOOK_TIMEOUT_MS`）；需要长耗时操作的 Observer 插件应在钩子内部使用 asyncio.create_task 异步处理，而非在钩子内 await |
| 前端 axios 拦截器改造引入无限 refresh 循环 | 中 | 中 | 使用"刷新锁"（Promise 单例）；refresh 失败后不重试；添加重试次数上限（最多 1 次）；测试覆盖：token 过期时只发起一次 refresh 请求 |
| Setup token 在多副本部署时不一致 | 低 | 中 | Phase 1a 先用内存存储（单实例部署足够），并在日志中提示"多副本部署请使用 CONCLAVE_SETUP_ADMIN_PASSWORD 环境变量"；Phase 2 持久化到 plugin_states 表 |

---

## 文件变更清单

### Phase 0 新增文件（第1周）

```
backend/app/plugins/__init__.py                                        # 新增
backend/app/plugins/core/__init__.py                                   # 新增
backend/app/plugins/core/types.py                                      # 新增：PluginTier/State/Health/Override/Fallback/Next/LLMOverride/LLMFallback/PluginContext
backend/app/plugins/core/exceptions.py                                 # 新增：ConclaveException 基类（P0 可只创建空文件，P1b.5 填充）
backend/app/plugins/core/registry.py                                   # 新增：PluginRegistry 实现
backend/app/plugins/core/event_bus.py                                  # 新增：PluginEventBus
backend/app/plugins/core/context.py                                    # 新增：插件 ContextVar 工具
backend/app/plugins/core/hooks/__init__.py                             # 新增
backend/app/plugins/core/hooks/lifecycle.py                            # 新增：LifecycleMixin/RouterMixin/MiddlewareMixin
backend/app/plugins/core/hooks/llm.py                                  # 新增：LLMPreCall/Observer/Error Mixin + LLMRequest/Response/Usage/ErrorInfo
backend/app/plugins/core/hooks/meeting.py                              # 新增：MeetingCreating/Created/Access Mixin
backend/app/plugins/builtin/__init__.py                                # 新增
backend/tests/test_plugin_framework/__init__.py                        # 新增
backend/tests/test_plugin_framework/test_registry.py                   # 新增
backend/tests/test_plugin_framework/test_dependency_resolution.py      # 新增
backend/tests/test_plugin_framework/test_hook_timeout.py               # 新增
backend/tests/test_plugin_framework/test_interceptor_observer.py       # 新增
backend/tests/test_plugin_framework/test_health_check.py               # 新增
backend/tests/test_plugin_framework/test_hot_disable.py                # 新增
backend/tests/test_plugin_framework/test_no_plugins.py                 # 新增
backend/tests/test_plugin_framework/test_event_bus.py                  # 新增
```

### Phase 0 修改文件

```
backend/app/main.py                       # 修改：在 create_app() 中构造 PluginRegistry，lifespan 中调用插件启动/关闭
backend/app/context.py                    # 修改：追加 plugin_name ContextVar
```

### Phase 1a 新增文件（第2周）

```
backend/app/plugins/builtin/auth/__init__.py
backend/app/plugins/builtin/auth/plugin.py            # AuthPlugin 类
backend/app/plugins/builtin/auth/models.py            # UserModel ORM（映射现有 users 表+新列）
backend/app/plugins/builtin/auth/router.py            # /auth/login, /auth/logout, /auth/me, /auth/refresh, /auth/me/byok
backend/app/plugins/builtin/auth/middleware.py        # Cookie+CSRF 认证中间件
backend/app/plugins/builtin/auth/setup.py             # /setup/status, /setup 端点 + setup token 逻辑
backend/app/plugins/builtin/auth/csrf.py              # CSRF token 生成/校验
backend/app/plugins/builtin/auth/jwt_utils.py         # JWT 工具（可从 app/auth.py re-export）
backend/app/plugins/builtin/auth/password.py          # 密码哈希（可从 app/auth.py re-export）
backend/alembic/versions/0005_auth_upgrade.py        # users 表添加个人 BYOK 列
```

前端新增/修改：
```
archive/frontend-react-original/src/pages/SetupPage.tsx          # 新增
archive/frontend-react-original/src/pages/ByokSettingsPage.tsx   # 新增（或在 SettingsPanel 中扩展）
archive/frontend-react-original/src/lib/api.ts                   # 修改：axios 拦截器
archive/frontend-react-original/src/store/AuthContext.tsx        # 修改：移除 localStorage token
archive/frontend-react-original/src/components/DrawerMenu.tsx   # 修改：导航栏登录状态
```

### Phase 1a 修改文件

```
backend/app/routers/auth.py                # 修改：改为从 auth 插件 re-export router
backend/app/middleware.py                  # 修改：认证中间件兼容 Cookie 和 Bearer，或在 auth 插件就绪时跳过
backend/app/main.py                        # 修改：在 _load_plugins_from_env 中注册 auth 插件
backend/app/auth.py                        # 修改：init_auth() 与 auth 插件协作（避免重复建表/创建管理员）
backend/app/routers/ws.py                  # 修改：WebSocket 认证从 Cookie 读取（替代 query token）
backend/app/db/models/__init__.py          # 修改：导出 Auth 插件的 UserModel（或在插件中独立导入 Base）
```

### Phase 1b 新增文件（第3周）

```
backend/app/plugins/builtin/billing/__init__.py
backend/app/plugins/builtin/billing/plugin.py         # BillingPlugin 类
backend/app/plugins/builtin/billing/router.py         # /billing/cost 等端点
backend/app/plugins/builtin/billing/cost_service.py   # 成本服务（包装 CostTracker）
backend/alembic/versions/0006_meetings_metadata.py  # meetings 表添加 metadata JSONB + GIN 索引
```

### Phase 1b 修改文件

```
backend/app/db/models/meeting.py           # 修改：MeetingModel 添加 metadata JSONB 列
backend/app/agents/llm.py                  # 修改：植入 on_llm_pre_call/on_llm_post_call/on_llm_error 钩子
backend/app/routers/meetings.py            # 修改：植入 on_meeting_creating/on_meeting_created/on_meeting_accessing 钩子
backend/app/dao/meeting_dao.py             # 修改：创建/加载会议时透传 metadata
backend/app/routers/metrics.py             # 修改：成本数据改为从 billing 插件获取（插件未加载时走原有逻辑）
backend/app/main.py                        # 修改：注册 /api/health/plugins 端点；注册 ConclaveException 全局处理器
backend/app/plugins/core/exceptions.py     # 填充 ConclaveException 和子类定义（如果 P0 只建了空文件）
backend/app/plugins/core/registry.py       # 修改：健康检查后台任务、热开关、插件状态管理
```

### 不修改/不删除的文件（Phase 0-1 范围外）

```
backend/app/auth.py                # 保留作为底层库，插件复用其函数（不在 Phase 0-1 删除）
backend/app/events.py              # 保留（WS 事件总线，非插件 EventBus）
backend/app/observability/cost_tracker.py  # 保留，被 billing 插件和核心回退路径使用
backend/app/services/key_store.py  # 保留，auth 插件复用其加密函数
backend/app/middleware.py 中的速率限制部分  # 保留，未来提取为 ratelimit 插件
backend/app/routers/*.py（除 auth.py/metrics.py/meetings.py 外）  # 不修改
backend/app/orchestrator/**        # 不修改（会议运行时核心，Phase 2 再植入钩子）
```

---

## 实施顺序建议

1. **Day 1-2**：完成 P0.1-P0.5（目录结构 + 类型定义 + Registry + EventBus + ContextVar）
2. **Day 3**：完成 P0.6（集成到 create_app）+ P0.7（单元测试）
3. **Day 4-5**：Phase 0 验收 + 代码审查 → 合入主干（不破坏任何功能）
4. **Day 6-7**：P1a.1-P1a.3（Auth 插件骨架 + Cookie 迁移 + 过渡期兼容）
5. **Day 8**：P1a.4-P1a.5（Setup 流程 + User 模型/BYOK 表）
6. **Day 9-10**：P1a.6-P1a.7（重构引用 + 前端适配）+ Phase 1a 验收
7. **Day 11-12**：P1b.1-P1b.3（metadata 迁移 + LLM 钩子 + 会议钩子）
8. **Day 13**：P1b.4（Billing 插件提取）
9. **Day 14**：P1b.5-P1b.6（错误标准化 + 健康检查端点）
10. **Day 15**：跨阶段验证 + Phase 1b 验收 + 文档更新

每个阶段结束时保持 `main` 分支可发布状态（green trunk）。
