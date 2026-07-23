[返回上级文档](../../README.md)

# Conclave 插件框架

## 1. 模块概述

Conclave 插件框架是一个**基于 Hook 的事件驱动插件系统**，为 Conclave 后端提供可扩展的模块化能力。它允许将横切关注点（认证、审计、计费、团队协作等）以独立插件的形式解耦到核心业务逻辑之外，通过声明式 Mixin 协议参与系统生命周期、拦截关键操作、并通过事件总线进行插件间通信。

框架设计遵循 ADR-003（插件分级），核心特性包括：

- **三层插件分级**：CORE / CROSSCUTTING / OPTIONAL，按层级区分故障影响范围
- **Kahn 拓扑排序**：自动解析插件依赖，支持硬依赖与软依赖（`name?` 后缀）
- **拦截型 + 观察型双模式 Hook**：拦截型可阻断/改写主流程，观察型仅做旁路审计
- **插件间事件总线**：`PluginEventBus` 提供轻量 pub/sub，解耦插件间通信
- **健康检查与热开关**：后台任务每 30 秒并发检查插件健康，支持运行时禁用/启用
- **超时与异常隔离**：单插件钩子超时默认 200ms，非 CORE 插件异常不影响整体稳定性

---

## 2. 插件分级（PluginTier）

插件分为三个层级，定义在 `core/types.py` 的 `PluginTier` 枚举中。层级决定了插件故障时系统的容错策略。

| 层级 | 枚举值 | 启动失败后果 | 钩子异常行为 | 可热禁用 | 典型示例 |
|---|---|---|---|---|---|
| **CORE** | `PluginTier.CORE` | 阻止服务启动（异常上抛） | 异常上抛，中断钩子链 | 否 | auth（JWT + CSRF + RBAC） |
| **CROSSCUTTING** | `PluginTier.CROSSCUTTING` | 标记为 `DEGRADED`，服务继续运行 | 异常被捕获并记录 WARNING，跳过该插件 | 是 | 审计日志、用量计量 |
| **OPTIONAL** | `PluginTier.OPTIONAL` | 标记为 `DISABLED`，对应 API 返回 503 | 异常被捕获并记录 WARNING，跳过该插件 | 是 | 计费、品牌定制、数据驻留 |

### 依赖声明

插件通过 `dependencies` 类属性声明对其他插件的依赖：

- **硬依赖**：`dependencies = ["auth"]` —— 被依赖插件不存在时启动失败
- **软依赖**：`dependencies = ["billing?"]` —— 被依赖插件不存在时仅记 WARNING，继续加载

---

## 3. Hook 分类与可用钩子

插件通过**继承 Mixin Protocol** 来声明自己支持哪些钩子。所有钩子均为 `async` 方法，定义在 `core/hooks/` 目录下。

### 3.1 生命周期钩子（`core/hooks/lifecycle.py`）

| Mixin | 钩子方法 | 类型 | 说明 |
|---|---|---|---|
| `LifecycleMixin` | `on_startup(ctx)` | 生命周期 | 插件启动，用于 DB 初始化、建表、缓存加载等。CORE 抛异常阻止启动 |
| `LifecycleMixin` | `on_shutdown(ctx)` | 生命周期 | 插件关闭，用于资源清理。异常仅记 WARNING |
| `LifecycleMixin` | `health_check()` | 生命周期 | 健康检查，返回 `PluginHealth(healthy, message)` |
| `RouterMixin` | `register_routers(app)` | 同步注册 | 将 FastAPI 路由挂载到 app（`app.include_router(...)`） |
| `MiddlewareMixin` | `register_middlewares(app)` | 同步注册 | 注册 HTTP 中间件到 app（`app.middleware(...)`） |

### 3.2 LLM 调用钩子（`core/hooks/llm.py`）

| Mixin | 钩子方法 | 类型 | 说明 |
|---|---|---|---|
| `LLMPreCallMixin` | `on_llm_pre_call(ctx, req)` | **拦截型** | LLM 调用前拦截，可返回 `LLMOverride`（替换参数）/`Fallback`（拒绝）/`Next`（弃权） |
| `LLMObserverMixin` | `on_llm_post_call(ctx, req, resp, usage)` | **观察型** | LLM 调用后观察，用于用量统计、成本审计、日志记录 |
| `LLMErrorMixin` | `on_llm_error(ctx, req, err)` | **拦截型** | LLM 调用错误时拦截，可返回 `LLMFallback`（切换 Key/Model 重试）/`Next`（弃权上抛） |

相关数据结构：`LLMRequest`、`LLMResponse`、`LLMUsage`、`LLMErrorInfo`、`LLMOverride`、`LLMFallback`。

### 3.3 会议生命周期钩子（`core/hooks/meeting.py`）

| Mixin | 钩子方法 | 类型 | 说明 |
|---|---|---|---|
| `MeetingCreatingMixin` | `on_meeting_creating(ctx, payload)` | **拦截型** | 会议创建前拦截，可返回 `Fallback`（阻止创建，返回 HTTP 错误）或通过 `ctx.extra['metadata_patch']` 注入 metadata |
| `MeetingCreatedMixin` | `on_meeting_created(ctx, meeting_id, metadata)` | **观察型** | 会议创建后观察，用于审计日志、通知推送 |
| `MeetingAccessMixin` | `on_meeting_accessing(ctx, meeting)` | **拦截型** | 会议访问拦截，返回 `Fallback` 拒绝访问 |

### 3.4 拦截型 vs 观察型钩子的返回值约定

**拦截型钩子**（`fire_interceptor`）按 tier → priority → name 顺序串行调用：

| 返回值 | 效果 |
|---|---|
| `Override(value)` | 终止链，使用 `value` 作为钩子结果 |
| `Fallback(reason, code, status_code)` | 终止链，转换为 `HTTPException` 抛出（也可直接 `raise Fallback(...)`） |
| `Next()` 或 `None` | 弃权，交给下一个插件 |
| 超时（默认 200ms） | 跳过该插件，继续下一个 |
| 异常 | CORE 插件异常上抛；非 CORE 插件异常记 WARNING 后跳过 |

**观察型钩子**（`fire_observer`）调用所有 READY/DEGRADED 插件：

- 支持 `concurrent=True` 并发执行
- 所有异常均被隔离，不影响主流程
- 返回值被忽略

---

## 4. 插件生命周期

```
注册 (register) → 拓扑排序 (topo_sort) → Bootstrap (路由/中间件注册)
     ↓
初始化 (on_startup) → READY → 钩子订阅/事件处理 → 健康检查循环 (30s)
     ↓
关闭 (on_shutdown) → STOPPED
```

### 4.1 注册阶段

在 `create_app()` 中通过 `registry.register(plugin_instance)` 逐个注册插件。注册时校验 `name`（全局唯一）、`tier`、`version`，缺失 `dependencies`/`priority` 时填充默认值（`[]` / `100`）。

### 4.2 Bootstrap 阶段（同步）

调用 `registry.bootstrap(app)` 时：

1. 执行 Kahn 拓扑排序确定加载顺序（同层按 `(tier, priority, name)` 排序）
2. 注册全局异常处理器（`AppException` → JSON 响应）
3. 按序调用 `register_middlewares(app)` 注册中间件
4. 按序调用 `register_routers(app)` 注册路由

### 4.3 初始化阶段（异步）

调用 `await registry.initialize_all(app)` 时：

1. 构造 `PluginContext(app, registry, event_bus)`
2. 按拓扑序串行调用每个插件的 `on_startup(ctx)`，超时 30 秒
3. 根据 tier 处理启动失败（见第 2 节分级表）
4. 启动后台健康检查任务（每 30 秒并发检查，单次超时 5 秒）

### 4.4 运行阶段

- 插件通过 Hook 参与业务流程（拦截型/观察型）
- 插件间通过 `PluginEventBus` 发布/订阅事件解耦通信
- 健康检查持续运行，CORE 插件连续 3 次失败记 CRITICAL
- 支持 `disable_plugin(name)` / `enable_plugin(name)` 热开关（内存版）

### 4.5 关闭阶段

调用 `await registry.shutdown_all()` 时：

1. 停止健康检查后台任务
2. 按拓扑序**逆序**调用每个插件的 `on_shutdown(ctx)`，超时 10 秒
3. 清空事件总线所有订阅

### 4.6 插件状态机

```
DISCOVERED → LOADED → INITIALIZING → READY ⇄ DEGRADED
                                    ↓            ↓
                              (DISABLED)    SHUTTING_DOWN → STOPPED
                                    ↓
                                 FAILED（仅 CORE）
```

---

## 5. 插件间事件总线（PluginEventBus）

`PluginEventBus`（`core/event_bus.py`）提供插件间的**轻量异步 pub/sub**，与系统级 `app/events.py`（用于 WebSocket 实时推送的 InMemoryEventBus）是两个独立总线，互不干扰。

```python
from app.plugins import get_registry

registry = get_registry()
bus = registry.event_bus

# 订阅事件
unsub = bus.subscribe("meeting.exported", on_meeting_exported)

# 发布事件
await bus.publish(PluginEvent(
    type="meeting.exported",
    payload={"meeting_id": mid, "format": "pdf"},
    source_plugin="my_plugin",
    request_id=ctx.request_id,
))

# 取消订阅
unsub()
```

### 关键特性

- **异步并发派发**：`publish()` 使用 `asyncio.gather` 并发通知所有订阅者
- **异常隔离**：单个 handler 失败不影响其他订阅者，仅记 WARNING
- **不持久化**：纯内存总线，进程重启后丢失
- **自动清理**：`shutdown_all()` 时调用 `unsubscribe_all()` 清空所有订阅

---

## 6. 内置插件

### auth（CORE）

位置：`builtin/auth/`

认证 CORE 插件，提供 JWT 认证、CSRF 防护和多租户 RBAC。

| 组件 | 文件 | 职责 |
|---|---|---|
| 插件主类 | `plugin.py` | `AuthPlugin(LifecycleMixin, RouterMixin, MiddlewareMixin)` |
| 路由 | `router.py` | 挂载 `/auth/*` 端点（登录、注册、Token 刷新等） |
| Setup 路由 | `setup.py` | 挂载 `/setup/*` 端点（首次管理员创建，Setup Token 机制） |
| 租户路由 | `tenants_router.py` | 挂载租户管理端点 |
| 中间件 | `middleware.py` | 认证中间件 + CSRF 中间件 |
| CSRF | `csrf.py` | CSRF Token 生成与校验 |

`on_startup` 执行顺序：
1. 初始化 JWT secret、建 users 表、加载用户缓存、创建默认管理员
2. 建 tenants 表 + users.tenant_id 外键约束
3. 创建默认租户并关联历史用户
4. 为核心业务表添加 `tenant_id` 列并回填
5. 重新加载用户缓存（确保 tenant_id 已填充）
6. 生成 Setup Token（若无用户时提示通过 `/setup` 创建管理员）

---

## 7. 关键文件索引

| 文件路径 | 说明 |
|---|---|
| `__init__.py` | 模块入口，导出 `PluginRegistry`、`get_registry`、`set_global_registry` |
| `core/__init__.py` | 核心模块统一导出（类型、Hook Mixin、注册中心、事件总线、异常） |
| `core/types.py` | 基础类型：`PluginTier`、`PluginState`、`PluginHealth`、`PluginBase` Protocol、`PluginContext`、`Override/Next/Fallback`、`LLMOverride/LLMFallback` |
| `core/registry.py` | `PluginRegistry`：注册、拓扑排序、Bootstrap、生命周期管理、钩子调度（`fire_interceptor`/`fire_observer`）、健康检查、热开关 |
| `core/event_bus.py` | `PluginEventBus` + `PluginEvent`：插件间异步 pub/sub 事件总线 |
| `core/context.py` | `plugin_scope` 上下文管理器 + ContextVar 工具（`get/set/reset_plugin_name`） |
| `core/exceptions.py` | 异常类：`PluginDependencyError`、`PluginLoadError`、`PluginRejected`、`QuotaExceeded`、`AccessDenied`、`SetupRequired` 等 |
| `core/hooks/__init__.py` | Hook Mixin 统一导出 |
| `core/hooks/lifecycle.py` | 生命周期 Mixin：`LifecycleMixin`、`RouterMixin`、`MiddlewareMixin` |
| `core/hooks/llm.py` | LLM Mixin：`LLMPreCallMixin`、`LLMObserverMixin`、`LLMErrorMixin` + 数据结构 |
| `core/hooks/meeting.py` | 会议 Mixin：`MeetingCreatingMixin`、`MeetingCreatedMixin`、`MeetingAccessMixin` |
| `builtin/__init__.py` | 内置插件包（Phase 1a 起扩展） |
| `builtin/auth/` | auth CORE 插件（JWT + CSRF + 多租户 RBAC） |

---

## 8. 如何创建一个新插件

### 步骤 1：创建插件目录

在 `backend/app/plugins/builtin/` 下创建插件子目录（以插件名命名）：

```
builtin/
  my_plugin/
    __init__.py
    plugin.py      # 插件主类（必需）
    router.py      # 路由（可选）
    middleware.py  # 中间件（可选）
    # ...其他模块
```

### 步骤 2：编写插件主类

`plugin.py` 示例骨架：

```python
"""MyPlugin 示例插件。"""

from __future__ import annotations

import logging
from typing import ClassVar

from fastapi import FastAPI

from app.plugins.core.hooks import (
    LifecycleMixin,
    LLMObserverMixin,
    MiddlewareMixin,
    MeetingCreatedMixin,
    RouterMixin,
)
from app.plugins.core.types import (
    LLMRequest,
    LLMResponse,
    LLMUsage,
    Next,
    PluginContext,
    PluginHealth,
    PluginTier,
)

logger = logging.getLogger(__name__)


class MyPlugin(
    LifecycleMixin,
    RouterMixin,
    MiddlewareMixin,      # 可选
    LLMObserverMixin,    # 可选
    MeetingCreatedMixin, # 可选
):
    """我的自定义插件。"""

    name: str = "my_plugin"
    version: str = "1.0.0"
    tier: PluginTier = PluginTier.OPTIONAL  # 或 CORE / CROSSCUTTING
    dependencies: ClassVar[list[str]] = ["auth"]  # 硬依赖 auth；软依赖用 "billing?"
    priority: int = 100  # 同 tier 内排序，数值越小越先执行

    def __init__(self) -> None:
        self._call_count: int = 0

    # ---- 生命周期 ----

    async def on_startup(self, ctx: PluginContext) -> None:
        """插件启动：初始化资源、建表、加载缓存等。"""
        logger.info("my_plugin 启动中...")
        # ctx.app: FastAPI 实例
        # ctx.registry: PluginRegistry 实例
        # ctx.event_bus: PluginEventBus 实例

        # 订阅其他插件的事件
        if ctx.event_bus:
            ctx.event_bus.subscribe("meeting.exported", self._on_meeting_exported)

    async def on_shutdown(self, ctx: PluginContext) -> None:
        """插件关闭：清理资源。"""
        logger.info("my_plugin 关闭")

    async def health_check(self) -> PluginHealth:
        """健康检查。"""
        return PluginHealth(healthy=True, message="ok")

    # ---- 路由注册 ----

    def register_routers(self, app: FastAPI) -> None:
        """挂载插件路由。"""
        from app.plugins.builtin.my_plugin.router import router
        app.include_router(router, prefix="/api/my-plugin", tags=["my-plugin"])

    # ---- 中间件注册（可选）----

    def register_middlewares(self, app: FastAPI) -> None:
        """注册 HTTP 中间件（如需要）。"""
        # from app.plugins.builtin.my_plugin.middleware import MyMiddleware
        # app.add_middleware(MyMiddleware)
        pass

    # ---- LLM 观察钩子（可选）----

    async def on_llm_post_call(
        self,
        ctx: PluginContext,
        req: LLMRequest,
        resp: LLMResponse,
        usage: LLMUsage,
    ) -> None:
        """记录 LLM 调用用量。"""
        self._call_count += 1
        logger.debug(
            "LLM 调用: model=%s input_tokens=%d cost=%.4f",
            req.model, usage.input_tokens, usage.cost_usd,
        )

    # ---- 会议观察钩子（可选）----

    async def on_meeting_created(
        self,
        ctx: PluginContext,
        meeting_id: str,
        metadata: dict,
    ) -> None:
        """会议创建后处理（如发送通知）。"""
        logger.info("会议已创建: %s", meeting_id)

    # ---- 事件处理 ----

    async def _on_meeting_exported(self, event) -> None:
        """处理其他插件发布的事件。"""
        logger.info("收到事件: %s payload=%s", event.type, event.payload)
```

### 步骤 3：注册插件

在应用启动入口（如 `backend/app/main.py` 的 `create_app()` 中）注册并加载：

```python
from app.plugins import get_registry, set_global_registry, PluginRegistry
from app.plugins.builtin.auth.plugin import AuthPlugin
from app.plugins.builtin.my_plugin.plugin import MyPlugin

def create_app() -> FastAPI:
    app = FastAPI()

    # 1. 创建注册中心
    registry = PluginRegistry(hook_timeout_ms=200)
    set_global_registry(registry)

    # 2. 注册插件
    registry.register(AuthPlugin())
    registry.register(MyPlugin())

    # 3. Bootstrap（同步注册路由、中间件）
    registry.bootstrap(app)

    # 4. 注册 startup 事件中异步初始化
    @app.on_event("startup")
    async def _startup():
        await registry.initialize_all(app)

    @app.on_event("shutdown")
    async def _shutdown():
        await registry.shutdown_all()

    return app
```

### 步骤 4：在业务代码中触发钩子

```python
from app.plugins import get_registry
from app.plugins.core.types import PluginContext
from app.plugins.core.hooks.llm import LLMRequest

registry = get_registry()
ctx = PluginContext(app=app, registry=registry, event_bus=registry.event_bus, request_id=req_id)

# 触发拦截型钩子
result = await registry.fire_interceptor(
    "on_llm_pre_call", ctx, llm_request, default=None
)

# 触发观察型钩子（并发执行）
await registry.fire_observer(
    "on_llm_post_call", ctx, llm_request, llm_response, usage, concurrent=True
)
```

---

## 9. 插件隔离与错误处理

### 9.1 隔离机制

| 维度 | 策略 |
|---|---|
| **启动隔离** | CORE 失败阻止启动；CROSSCUTTING 标记 DEGRADED；OPTIONAL 标记 DISABLED |
| **钩子超时** | 单个钩子默认 200ms 超时（`hook_timeout_ms`），超时后跳过该插件；1 分钟内超时 ≥10 次标记 DEGRADED |
| **异常隔离** | 拦截型钩子中，CORE 插件异常上抛中断链；非 CORE 插件异常记 WARNING 后跳过。观察型钩子所有异常均被隔离 |
| **事件总线隔离** | `asyncio.gather(return_exceptions=True)` 保证单个 handler 失败不影响其他订阅者 |
| **热开关** | `disable_plugin()` / `enable_plugin()` 可在运行时禁用/启用非 CORE 插件 |
| **健康检查隔离** | 后台任务并发检查各插件健康，单个插件检查异常不影响其他插件 |

### 9.2 异常类型

| 异常类 | 用途 | HTTP 状态码 |
|---|---|---|
| `PluginDependencyError` | 插件依赖缺失、循环依赖、重复注册 | 500（启动期） |
| `PluginLoadError` | 插件加载失败 | 500 |
| `PluginRejected` | 插件拒绝操作（通用） | 403 |
| `AccessDenied` / `AccessDeniedError` | 访问被拒绝 | 403 |
| `QuotaExceeded` | 配额超限 | 429 |
| `SetupRequired` | 系统未完成初始化设置 | 503 |
| `Fallback` | 拦截型钩子返回/抛出，转换为 HTTPException | 可指定（默认 403） |

### 9.3 使用 Fallback 拒绝操作

拦截型钩子中通过返回或抛出 `Fallback` 来拒绝操作：

```python
from app.plugins.core.types import Fallback, Next, PluginContext

async def on_meeting_creating(self, ctx: PluginContext, payload: dict):
    if not self._check_quota():
        return Fallback(
            reason="配额已耗尽，请升级套餐",
            code="QUOTA_EXCEEDED",
            status_code=429,
            details={"limit": 100, "current": 100},
        )
    return Next()
```

`PluginRegistry.fire_interceptor` 会将 `Fallback` 自动转换为 `HTTPException` 返回给客户端。

### 9.4 健康快照

通过 `registry.get_health_snapshot()` 可获取所有插件的当前状态：

```python
snapshot = registry.get_health_snapshot()
# {
#   "auth": {"state": "ready", "tier": "core", "version": "1.0.0", "healthy": true, ...},
#   "my_plugin": {"state": "ready", "tier": "optional", ...},
# }
```
