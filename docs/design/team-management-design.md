# Conclave 团队管理与多租户设计文档

> 版本: v0.4 (Final Draft for Implementation)
> 状态: 所有架构决策已定稿，可进入实施
> 适用范围: Conclave 核心服务（FastAPI + PostgreSQL + Redis）
> 上一版本: v0.3（已根据多模型审计反馈完成全面重构）

---

## 0. 架构原则

本节定义贯穿整个插件体系与多租户实现的底层约束。所有后续章节均不得违反本节原则。

### 0.1 核心与插件分离（JSONB metadata 方案）

核心代码（core）对多租户、计费、审计等业务概念**零感知**。核心仅维护：

- 用户与认证会话（由 auth 插件提供，但核心通过标准协议消费）
- 会议的生命周期与 LLM 调用
- 插件注册中心与钩子调度

对 `meetings` 表的多租户扩展采用**单一 JSONB 列**方案：

```sql
ALTER TABLE meetings ADD COLUMN metadata JSONB NOT NULL DEFAULT '{}';
CREATE INDEX idx_meetings_metadata_gin ON meetings USING GIN (metadata);
```

核心代码**永远不**读取或写入 `metadata` 内的业务字段；该列对核心而言是不透明的扩展槽位。插件自行读写自己的命名空间，例如 team 插件约定 `meeting.metadata["team"] = {...}`，billing 插件可写入 `meeting.metadata["billing"] = {...}`。插件之间互不假设对方在 metadata 中的结构。

这一设计确保：
- 核心表结构稳定，新增业务维度无需 DDL
- 回滚时 metadata 列可保留（旧代码自动忽略）
- 插件可独立演进而不触发核心迁移

### 0.2 插件分层（3 个 Tier）

每个插件在 `PluginBase` 中声明自己的 tier，决定其失败时的系统行为：

| Tier | 语义 | 加载失败行为 | 运行期失败行为 | 示例 |
|------|------|-------------|---------------|------|
| `CORE` | 系统必须依赖 | **阻止服务启动**（`sys.exit(1)`） | 拦截器钩子被跳过并记录 CRITICAL，服务进入维护模式 | auth |
| `CROSSCUTTING` | 横切关注点 | 记录 ERROR，服务继续启动但标记该插件为 unhealthy | 影响所有请求的横切能力降级（如无审计日志、无限额检查但仍可用） | billing, audit |
| `OPTIONAL` | 可选功能 | 记录 WARN，服务继续启动，该插件的路由不注册 | 该插件的 API 返回 503，核心与其他插件不受影响 | team, notification |

Tier 声明必须在插件类属性中硬编码，禁止运行期动态修改。

### 0.3 插件接口定义（Mixin 组合式）

不使用单一臃肿的 `ConclavePlugin` Protocol，而采用**Mixin 组合**模式。插件按需实现 Mixin，未实现的钩子不会被调度。

```python
class PluginBase(Protocol):
    name: str                     # 全局唯一，如 "auth", "team", "billing"
    version: str                  # semver，如 "1.0.0"
    tier: PluginTier              # CORE / CROSSCUTTING / OPTIONAL
    dependencies: list[str]       # 所依赖的其他插件 name 列表

class LifecycleMixin(Protocol):
    async def on_startup(self, ctx: "AppContext") -> None: ...
    async def on_shutdown(self, ctx: "AppContext") -> None: ...
    async def health_check(self) -> bool: ...

class RouterMixin(Protocol):
    def register_routers(self, app: FastAPI) -> None: ...
    def register_middlewares(self, app: FastAPI) -> None: ...

class LLMPreCallMixin(Protocol):
    async def on_llm_pre_call(self, ctx: "CallContext", req: "LLMRequest") -> "LLMOverride | None": ...

class LLMObserverMixin(Protocol):
    async def on_llm_post_call(self, ctx: "CallContext", req: "LLMRequest", resp: "LLMResponse", usage: "Usage") -> None: ...

class LLMErrorMixin(Protocol):
    async def on_llm_error(self, ctx: "CallContext", req: "LLMRequest", err: "LLMError") -> "LLMFallback | None": ...

class MeetingCreateMixin(Protocol):
    async def on_meeting_creating(self, ctx: "CallContext", payload: dict) -> None:
        """可抛 AccessDeniedError 阻止创建"""
    async def on_meeting_created(self, ctx: "CallContext", meeting_id: str, metadata_snapshot: dict) -> None:
        """观察型：审计/通知"""

class MeetingAccessMixin(Protocol):
    async def on_meeting_accessing(self, ctx: "CallContext", meeting: "MeetingRow") -> None:
        """可抛 AccessDeniedError 拒绝访问"""
```

插件示例：

```python
class TeamPlugin(PluginBase, LifecycleMixin, RouterMixin,
                 MeetingCreateMixin, MeetingAccessMixin,
                 LLMPreCallMixin, LLMErrorMixin):
    name = "team"
    version = "1.0.0"
    tier = PluginTier.OPTIONAL
    dependencies = ["auth", "billing"]
    # ... 实现所需方法
```

### 0.4 钩子分类：拦截型 vs 观察型

钩子分为两类，调度语义严格区分：

**拦截型钩子（Interceptor）**
- 签名允许返回非 None 值（Override / Fallback）或抛出异常
- 按插件优先级顺序调用，**第一个非 None 返回值短路后续插件**
- 若抛出异常，传播至调用方（例如拒绝访问、阻止创建）
- 若前一个插件返回 None，继续调用下一个；所有插件均返回 None 时执行核心默认行为

**观察型钩子（Observer）**
- 签名返回值为 None（或返回值被忽略）
- **所有健康插件均被调用**，不短路；单个插件异常不影响其他插件
- 采用 fire-and-forget 语义，异常仅记录日志

具体钩子分类：

| 钩子 | 类型 | 作用 |
|------|------|------|
| `on_startup` / `on_shutdown` | 观察型 | 生命周期通知 |
| `health_check` | 特殊（主动拉取） | 返回 bool |
| `on_llm_pre_call` | 拦截型 | 返回 `LLMOverride(api_key, model, base_url)` 可替换密钥/模型/端点 |
| `on_llm_post_call` | 观察型 | 记录用量、写入审计 |
| `on_llm_error` | 拦截型 | 返回 `LLMFallback(api_key, model, base_url)` 触发降级重试 |
| `on_meeting_creating` | 拦截型 | 抛异常阻止创建；可注入 metadata 片段（通过 ctx） |
| `on_meeting_created` | 观察型 | 审计日志、通知 |
| `on_meeting_accessing` | 拦截型 | 抛异常拒绝访问 |
| `resolve_api_key`（内部） | 拦截型 | 选择本次调用使用的 API Key |
| `resolve_quota`（内部） | 拦截型 | 返回可用配额；None 表示使用默认 |
| `resolve_access`（内部） | 拦截型 | 返回访问许可；抛异常拒绝 |
| `resolve_model`（内部） | 拦截型 | 返回可使用的模型列表/映射 |

### 0.5 插件注册与加载（拓扑排序、依赖声明）

`PluginRegistry` 是**实例**（非类变量单例），在 `create_app()` 工厂中构造并通过依赖注入（FastAPI `Depends` 或 AppContext）传递：

```python
async def create_app() -> FastAPI:
    registry = PluginRegistry()
    registry.register(AuthPlugin())
    registry.register(BillingPlugin())
    registry.register(AuditPlugin())
    registry.register(TeamPlugin())
    await registry.resolve_and_load()   # 拓扑排序 + 按序启动
    app = FastAPI()
    registry.register_routers(app)
    registry.register_middlewares(app)
    # ... 将 registry 挂载到 app.state
    return app
```

加载顺序算法：
1. 收集所有已注册插件的 `dependencies` 列表
2. 执行 Kahn 拓扑排序（按插件 name 字典序作为同层 tiebreaker，保证确定性）
3. 若存在循环依赖，启动失败并打印环路
4. 按拓扑序依次调用 `on_startup`
5. 若某 CORE 插件 `on_startup` 抛异常：阻止启动
6. 若某 CROSSCUTTING 插件失败：标记 unhealthy，继续
7. 若某 OPTIONAL 插件失败：标记 disabled，不注册其路由，继续

依赖失败传播规则：
- 被依赖的 CORE 插件失败 → 依赖者视为失败（CORE/CROSSCUTTING/OPTIONAL 均不可用）
- 被依赖的 CROSSCUTTING 插件失败 → 依赖者可选择在 `dependencies` 中标记为软依赖（字符串后缀 `?`，如 `"billing?"`），未标记则视为硬依赖并失败
- 被依赖的 OPTIONAL 插件失败 → 依赖者可继续运行，但功能降级（由依赖者自行处理，例如 team 插件在 billing 不可用时禁用配额检查但保留成员管理）

### 0.6 插件健康检查与超时

**健康检查**
- 每个实现 `LifecycleMixin` 的插件必须实现 `health_check() -> bool`
- 核心每 30 秒对所有已加载插件执行一次健康检查（异步并发）
- 健康状态缓存到 `plugin_states` 表与内存
- 拦截型钩子调用前检查插件健康状态：unhealthy 的插件**跳过其拦截器**，记录 WARNING；观察型钩子仍 best-effort 触发（异常被吞掉）

**钩子超时**
- 每次钩子调用强制 **200ms 超时**（通过 `asyncio.wait_for`）
- 超时后：
  - 拦截型：视为返回 None（继续下一个插件或走默认行为），记录 WARNING（含插件名、钩子名、耗时）
  - 观察型：记录 WARNING 并跳过
- 超时阈值通过配置 `plugin.hook_timeout_ms` 调整，默认 200ms
- 防止一个行为异常的插件阻塞所有 LLM 调用或所有请求

### 0.7 插件间通信规则（禁止直接引用）

插件之间**严禁**：
- 直接 `import` 其他插件模块
- 通过 `ctx.get_plugin("auth")` 获取其他插件实例
- 在代码中硬编码其他插件的类名或模块路径

插件仅允许通过以下三种机制通信：

1. **ContextVar（请求作用域状态）**
   - 每个插件拥有自己的命名空间，例如 `auth.current_user`、`team.current_team`、`billing.current_quota`
   - 通过类型化的 getter/setter 访问，避免 key 冲突
   - 请求结束时自动清理

2. **EventBus（事件总线）**
   - fire-and-forget 语义
   - 插件可订阅 `user.created`、`team.member_added`、`quota.exhausted` 等事件
   - 事件投递是 best-effort，不保证顺序（同插件内按订阅顺序）

3. **钩子参数中的类型化数据对象**
   - 通过 `CallContext`、`LLMRequest` 等标准对象传递数据
   - 插件可通过 ctx.metadata 字典写入自己的命名空间数据供后续钩子读取（但不得读取其他插件的私有字段）

### 0.8 热开关（无需重启禁用插件）

- Redis 配置键 `conclave:plugins:disabled` 存储禁用插件列表（Set 结构，如 `SADD conclave:plugins:disabled team`）
- 核心在每次钩子调用前检查该键；若插件在禁用列表中，其拦截器被跳过、观察器不触发、路由返回 503
- 变更通过 Redis Pub/Sub `conclave:plugins:control` 频道实时广播到所有实例，无需重启
- 启动时从 Redis 加载初始禁用集合；Redis 不可用时回退到内存空集合（即所有插件启用），并记录 WARNING
- CORE 插件不可被热禁用（配置会被拒绝并记录 ERROR）

### 0.9 钩子 SLO

- 单次拦截型钩子调用 p50 < 10ms，p99 < 50ms（不含网络 IO 的纯计算场景）
- 全部拦截器链总耗时 p99 < 100ms（LLM 调用前的插件开销）
- 超过 200ms 触发超时保护
- 观察型钩子不阻塞主流程，通过后台任务执行

---

## 1. 核心概念

### 1.1 双角色模型

Conclave 中的用户在不同 Namespace 下可拥有不同角色，角色仅在所属 Namespace 内生效：

- **System Admin（系统管理员）**：全局唯一或少量，负责实例级配置、插件管理、系统监控。独立于团队角色。
- **Team Owner（团队所有者）**：团队的最高权限者，可转让。每个团队至少一名。
- **Team Admin（团队管理员）**：管理成员、规则、密钥、配额等。
- **Team Member（团队成员）**：普通成员，可在团队配额内使用资源。
- **Anonymous Viewer（匿名围观者）**：只读访问被公开的会议，无成员身份。

个人空间（Personal Namespace）下，用户即自己的 Owner，拥有全部个人资源的控制权。

### 1.2 Namespace 模型（树形）

资源（API Key、会议、配额）在逻辑上从属于 Namespace：

- **个人 Namespace**：每个用户自动拥有，`team_id` 使用哨兵 UUID `00000000-0000-0000-0000-000000000000`（禁止使用 NULL，避免 UNIQUE 约束问题）。该哨兵在代码中以常量 `PERSONAL_NAMESPACE_ID` 引用。
- **团队 Namespace**：由团队创建，组织成员、共享密钥、共享配额。
- **团队树**：团队支持层级结构（Phase 4 实现），通过 `teams.path LTREE` 实现祖先/后代查询。子团队可从父团队池切分配额。

每个 Namespace 拥有：
- 独立的 API Key 集合（pool key 或 personal key）
- 独立的配额账本（quota_snapshots）
- 独立的规则集（resource_rules）
- 独立的成员列表（个人空间隐式只有自己）

### 1.3 资源来源双轨制

用户在发起 LLM 调用时，token 来源按以下优先级解析（由 `resolve_api_key` 拦截器链决定）：

1. **请求显式指定**：Header `X-Conclave-Key-Id` 指定使用某把 key
2. **团队 Pool Key**：当前上下文属于团队且团队配置了统一付费池，使用 pool key
3. **个人 Key**：使用用户个人配置的 key（user_api_keys 中 `is_default = TRUE` 的那条，或用户自选）
4. **系统默认 Key**：若管理员配置了兜底 key（例如免费试用场景）

配额扣减跟随 key 的归属：使用 pool key 则扣减团队池配额，使用 personal key 则扣减个人配额。

### 1.4 公开会议

会议可被设置为公开（visibility），支持匿名围观：

- 公开会议的围观通过独立 WebSocket 端点 `/ws/anon/{meeting_id}` 接入
- 匿名连接只能接收 `agent.message` 类事件，所有 `user.*`、`intervene`、`control`、`file.*` 事件在服务端被过滤
- 围观人数在 Redis 中计数，按会议设上限（默认 100）
- 围观会话记录 IP、User-Agent 到 audit_logs
- 可选开启 CAPTCHA（hCaptcha / Cloudflare Turnstile），在 WS 升级前验证

---

## 2. System Admin 初始化

首次部署 Conclave 时，不存在任何用户。系统通过一次性 `/setup` 流程创建首个 System Admin。

**Setup Token 生成**
- 服务启动时检测到无 System Admin 用户，生成一次性 setup token
- Token 通过以下方式之一呈现给运维人员：
  - 写入启动日志（仅在 stdout 是安全通道时）
  - 写入 `plugin_states` 表中 `key = 'setup_token'` 的记录，由运维通过 DB 控制台读取
- Token 格式：`stk_` 前缀 + 32 字节随机值（urlsafe base64），存储时使用 SHA-256 哈希

**`/setup` 端点（POST /api/setup）**
- 请求体：`{ "token": "...", "username": "...", "password": "...", "email": "..." }`
- 响应：成功时返回 `{ "success": true }` 并签发管理员会话
- 保护措施：
  1. **24 小时过期**：token 创建超过 24 小时自动失效，需重新生成
  2. **速率限制**：同一 IP 10 分钟内最多 5 次尝试（基于 Redis 或内存计数器）
  3. **一次性使用**：成功后立即从 `plugin_states` 中删除 token 记录
  4. **多副本安全**：setup 状态存储在 DB `plugin_states` 表，非文件系统，多副本部署一致
  5. **幂等性**：系统已存在 System Admin 时，`/setup` 端点立即返回 404（对外隐藏是否已初始化）

**Setup Token 重新生成**
- System Admin 登录后可通过 `POST /api/admin/setup-token/regenerate` 生成新 token（用于灾备或交接）
- 旧 token 立即失效

---

## 3. 数据模型

### 3.1 ER 图（文字描述）

```
users (uid, username, email, password_hash, is_system_admin, created_at, deleted_at)
  ├─< user_api_keys (id, uid, provider, key_enc, label, is_default, created_at)
  ├─< team_members (team_id, uid, role, joined_at)
  ├─< resource_rules (rule_id, team_id, match_conditions JSONB, priority, effect, created_at, created_by, deleted_at)
  └─< user_groups (group_id, team_id, name) ─< group_members (group_id, uid)

teams (team_id, name, slug, parent_id, path LTREE, created_at, created_by, deleted_at)
  ├─1 team_settings (team_id, join_policy, allowed_domains, allow_anon, anon_cap, captcha_required)
  ├─1 team_pool (team_id, monthly_token_budget, allocated_to_children, key_enc, provider, balance_cached, balance_updated_at)
  ├─< team_members
  ├─< resource_rules
  ├─< user_groups
  └─< quota_snapshots (snapshot_id, team_id, uid, period_month DATE, total_quota, used_tokens, updated_at)

token_usage (usage_id, uid, team_id, meeting_id, provider, model, tokens_in, tokens_out, cost_usd, created_at)
  └─ 按月分区（基于 created_at）

meetings (meeting_id, owner_uid, title, created_at, updated_at, metadata JSONB, ...)

audit_logs (id, actor_uid, action, target_type, target_id, metadata JSONB, ip, ua, created_at)

plugin_states (plugin_name, key, value JSONB, updated_at)
  └─ 复合主键 (plugin_name, key)
```

### 3.2 核心改造（metadata JSONB）

`meetings` 表仅增加一列，无其他核心列变更：

```sql
ALTER TABLE meetings
  ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}';
CREATE INDEX IF NOT EXISTS idx_meetings_metadata_gin ON meetings USING GIN (metadata);
```

核心 SQL 查询、ORM 模型、业务逻辑**不**对 `metadata` 字段做任何业务解读。所有 team/visibility/token_source 等信息均由插件自行在其 `metadata["team"]` 等子空间内维护。

### 3.3 插件表（全部 DDL）

以下 DDL 在 Phase 0/1b 迁移中执行。所有表均使用 `UUID` 主键（v4 或 v7），金额字段使用 `NUMERIC(20,10)`，时间字段使用 `TIMESTAMPTZ`。

```sql
-- ============ 扩展：LTREE（若未启用） ============
CREATE EXTENSION IF NOT EXISTS ltree;

-- ============ teams 主表 ============
CREATE TABLE IF NOT EXISTS teams (
    team_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name          VARCHAR(128) NOT NULL,
    slug          VARCHAR(64)  NOT NULL,
    parent_id     UUID REFERENCES teams(team_id) ON DELETE CASCADE,
    path          LTREE NOT NULL,
    created_by    UUID NOT NULL REFERENCES users(uid),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at    TIMESTAMPTZ,
    -- slug 在同级（同父节点）下唯一；根节点 parent_id 为 NULL 时全局唯一
    CONSTRAINT uq_teams_slug_per_parent UNIQUE NULLS NOT DISTINCT (parent_id, slug)
);
CREATE INDEX idx_teams_path ON teams USING GIST (path);
CREATE INDEX idx_teams_parent ON teams(parent_id) WHERE deleted_at IS NULL;

-- ============ team_settings ============
CREATE TABLE IF NOT EXISTS team_settings (
    team_id         UUID PRIMARY KEY REFERENCES teams(team_id) ON DELETE CASCADE,
    join_policy     VARCHAR(16) NOT NULL DEFAULT 'invite_only',  -- invite_only | request | open
    allowed_domains TEXT[] NOT NULL DEFAULT '{}',               -- 邮箱域名白名单，如 ['{example.com}']
    allow_anon      BOOLEAN NOT NULL DEFAULT FALSE,
    anon_cap        INTEGER NOT NULL DEFAULT 100 CHECK (anon_cap BETWEEN 0 AND 10000),
    captcha_required BOOLEAN NOT NULL DEFAULT FALSE
);

-- ============ team_pool（预算/密钥/余额缓存） ============
CREATE TABLE IF NOT EXISTS team_pool (
    team_id               UUID PRIMARY KEY REFERENCES teams(team_id) ON DELETE CASCADE,
    monthly_token_budget  BIGINT NOT NULL DEFAULT 0 CHECK (monthly_token_budget >= 0),
    allocated_to_children BIGINT NOT NULL DEFAULT 0 CHECK (allocated_to_children >= 0),
    provider              VARCHAR(32),
    key_enc               TEXT,               -- 加密后的 provider API key
    balance_cached        NUMERIC(20,10),     -- 最近一次查询到的余额（USD）
    balance_updated_at    TIMESTAMPTZ,
    CONSTRAINT chk_allocation_le_budget CHECK (allocated_to_children <= monthly_token_budget)
);

-- ============ team_members ============
CREATE TABLE IF NOT EXISTS team_members (
    team_id   UUID NOT NULL REFERENCES teams(team_id) ON DELETE CASCADE,
    uid       UUID NOT NULL REFERENCES users(uid) ON DELETE CASCADE,
    role      VARCHAR(16) NOT NULL DEFAULT 'member',  -- owner | admin | member
    joined_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (team_id, uid),
    CONSTRAINT chk_role CHECK (role IN ('owner','admin','member'))
);
CREATE INDEX idx_teammembers_uid ON team_members(uid);

-- ============ user_groups ============
CREATE TABLE IF NOT EXISTS user_groups (
    group_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    team_id   UUID NOT NULL REFERENCES teams(team_id) ON DELETE CASCADE,
    name      VARCHAR(128) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (team_id, name)
);
CREATE TABLE IF NOT EXISTS group_members (
    group_id UUID NOT NULL REFERENCES user_groups(group_id) ON DELETE CASCADE,
    uid      UUID NOT NULL REFERENCES users(uid) ON DELETE CASCADE,
    added_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (group_id, uid)
);

-- ============ resource_rules ============
CREATE TABLE IF NOT EXISTS resource_rules (
    rule_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    team_id          UUID NOT NULL REFERENCES teams(team_id) ON DELETE CASCADE,
    name             VARCHAR(128) NOT NULL,
    description      TEXT NOT NULL DEFAULT '',
    match_conditions JSONB NOT NULL,   -- { email_domains?: [...], groups?: [...], uids?: [...], labels?: [...] }
    priority         REAL NOT NULL DEFAULT 100.0,
    effect           JSONB NOT NULL,   -- { allow_models?: [...], deny_models?: [...], token_quota_multiplier?: number, max_meeting_length?: number, ... }
    enabled          BOOLEAN NOT NULL DEFAULT TRUE,
    created_by       UUID NOT NULL REFERENCES users(uid),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at       TIMESTAMPTZ
);
CREATE INDEX idx_rules_team_priority ON resource_rules(team_id, priority DESC)
    WHERE deleted_at IS NULL AND enabled = TRUE;

-- ============ user_api_keys 修正 ============
-- 个人 API Key（每个用户每个 provider 至多一把默认 key）
CREATE TABLE IF NOT EXISTS user_api_keys (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    uid         UUID NOT NULL REFERENCES users(uid) ON DELETE CASCADE,
    provider    VARCHAR(32) NOT NULL,
    key_enc     TEXT NOT NULL,
    label       VARCHAR(128) NOT NULL DEFAULT '',
    is_default  BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_user_default_key
    ON user_api_keys(uid, provider) WHERE is_default = TRUE;
CREATE INDEX IF NOT EXISTS idx_userapikeys_uid ON user_api_keys(uid);

-- ============ quota_snapshots ============
-- team_id 使用哨兵 UUID '00000000-0000-0000-0000-000000000000' 表示个人空间
CREATE TABLE IF NOT EXISTS quota_snapshots (
    snapshot_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    team_id      UUID NOT NULL,   -- 哨兵 UUID 代表个人；不使用 NULL
    uid          UUID NOT NULL REFERENCES users(uid) ON DELETE CASCADE,
    period_month DATE NOT NULL,   -- 每月第一天，例如 '2026-07-01'
    total_quota  BIGINT NOT NULL DEFAULT 0,
    used_tokens  BIGINT NOT NULL DEFAULT 0 CHECK (used_tokens >= 0),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (team_id, uid, period_month)
);
CREATE INDEX IF NOT EXISTS idx_quota_team_period ON quota_snapshots(team_id, period_month);

-- ============ token_usage（按月分区表） ============
CREATE TABLE IF NOT EXISTS token_usage (
    usage_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    uid         UUID NOT NULL REFERENCES users(uid),
    team_id     UUID NOT NULL,   -- 同上哨兵规则
    meeting_id  UUID REFERENCES meetings(meeting_id) ON DELETE SET NULL,
    provider    VARCHAR(32) NOT NULL,
    model       VARCHAR(64) NOT NULL,
    tokens_in   INTEGER NOT NULL DEFAULT 0,
    tokens_out  INTEGER NOT NULL DEFAULT 0,
    cost_usd    NUMERIC(20,10) NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
) PARTITION BY RANGE (created_at);

CREATE INDEX IF NOT EXISTS idx_tokenusage_uid_time ON token_usage(uid, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tokenusage_team_time ON token_usage(team_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tokenusage_meeting ON token_usage(meeting_id, created_at);

-- 初始分区：最近 3 个月 + 当前月 + 未来 1 个月（由迁移脚本自动创建，运维脚本按月滚动）
-- 示例（迁移时执行）：
-- CREATE TABLE token_usage_y2026m07 PARTITION OF token_usage
--   FOR VALUES FROM ('2026-07-01') TO ('2026-08-01');

-- ============ audit_logs ============
CREATE TABLE IF NOT EXISTS audit_logs (
    id          BIGSERIAL PRIMARY KEY,
    actor_uid   UUID REFERENCES users(uid),
    action      VARCHAR(64) NOT NULL,
    target_type VARCHAR(32),
    target_id   TEXT,
    metadata    JSONB NOT NULL DEFAULT '{}',
    ip          INET,
    ua          TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_audit_actor ON audit_logs(actor_uid, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_logs(action, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_target ON audit_logs(target_type, target_id);

-- ============ plugin_states ============
CREATE TABLE IF NOT EXISTS plugin_states (
    plugin_name VARCHAR(64) NOT NULL,
    key         VARCHAR(128) NOT NULL,
    value       JSONB NOT NULL DEFAULT '{}',
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (plugin_name, key)
);
```

### 3.4 索引策略

- 高频查询路径全部使用**复合索引**，避免多索引 bitmap scan
- `token_usage` 按月分区，保留 12 个月在线数据，更旧数据归档至冷存储
- GIN 索引仅用于 `meetings.metadata` 和 `resource_rules.match_conditions`（若需要），避免过度使用
- 软删除字段 `deleted_at` 均使用**部分索引**（`WHERE deleted_at IS NULL`）减小索引体积
- LTREE GIST 索引支持祖先/后代/子路径查询，例如 `path <@ 'root'::ltree`
- 外键字段（`parent_id`、`team_id`、`uid`、`meeting_id`）均建索引

### 3.5 软删除

- `users`、`teams`、`resource_rules` 均有 `deleted_at TIMESTAMPTZ` 字段
- 删除操作不删除行，仅设置 `deleted_at = now()`
- 查询默认带 `WHERE deleted_at IS NULL`（推荐在 ORM 层使用全局 query filter）
- 唯一约束在软删除场景下的处理：
  - `teams(slug, parent_id)`：使用 `NULLS NOT DISTINCT`，已删除团队的 slug 可被新团队复用（因为 deleted_at 行不会冲突，需要额外部分唯一索引，详见实现）
  - 实际实现：使用 `UNIQUE NULLS NOT DISTINCT (parent_id, slug)` 并在应用层阻止创建已存在但未删除的 slug；若历史同名团队已删除则允许复用
- 级联软删除：删除团队时，由应用层在事务中软删除相关 resource_rules、team_members 关系（保留审计）
- 硬删除（物理删除）仅在明确的管理操作下执行（`/api/admin/purge`），默认不暴露给普通用户

### 3.6 加密格式规范

**对称加密算法**：AES-256-GCM（提供机密性 + 完整性）
**密钥派生**：
- 主密钥（Master Key）从环境变量 `CONCLAVE_MASTER_KEY` 读取，32 字节 base64 编码
- Phase 5 前使用文件/环境变量存储；Phase 5+ 可接入 Vault/KMS
- 若未设置主密钥，启动时自动生成并写入 `plugin_states(key='master_key_fingerprint')` 记录，但生产环境必须显式配置

**密文格式**（版本化字符串）：

```
v{version}:{base64(nonce)}:{base64(ciphertext || tag)}
```

- `version`：当前为 `1`
- `nonce`：12 字节 GCM nonce（每次加密随机生成）
- `ciphertext`：AES-256-GCM 加密输出
- `tag`：16 字节 GCM 认证标签，**附加在 ciphertext 之后**（即 `ciphertext || tag` 整体 base64 编码为第三段）
- 字段分隔符为冒号 `:`
- 示例：`v1:base64nonceabc...:base64ciphertextWithTag...`

**用途**：
- `user_api_keys.key_enc`：用户个人 API Key 的加密存储
- `team_pool.key_enc`：团队池 API Key 的加密存储
- 其他敏感字段按需复用相同格式

---

## 4. 规则计算引擎

规则引擎决定"某个用户在某个团队下最终能使用什么模型、拥有多少配额、有哪些限制"。规则由 Team Admin 定义，作用于团队成员。

### 4.1 有效规则计算（含缓存策略）

当用户 `uid` 在团队 `team_id` 下发起操作时，需计算该用户的有效规则集（effective rules）。

**匹配流程**：
1. 加载该团队下所有 `enabled = TRUE AND deleted_at IS NULL` 的规则
2. 对每条规则，检查 `match_conditions` 是否命中当前用户：
   - `uids`：直接指定 uid 列表
   - `email_domains`：用户邮箱后缀匹配
   - `groups`：用户所属组 ID 列表
   - `labels`：用户元数据标签（Phase 4+）
3. 所有命中的规则按 `priority DESC` 排序（高优先级在前）
4. 按顺序合并 effect：
   - `allow_models` / `deny_models`：高优先级规则优先；deny 覆盖 allow
   - `token_quota_multiplier`：**乘法叠加**（见 §4.2）
   - 其他数值限制（max_meeting_length 等）：取所有命中规则中的**最严值**（min）
5. 未命中任何规则时使用团队默认值（effect 为空对象）

**缓存策略**：
- 计算结果缓存到 Redis，key 为 `rules:{uid}:{team_id}`，value 为合并后的 effect JSON
- TTL：**5 分钟**
- 失效条件（精确失效，不依赖 TTL）：
  - 该团队任意规则增删改
  - 该团队成员角色变更
  - 该团队组成员变更
  - 用户个人资料变更（email 等影响匹配的字段）
- 失效通过 EventBus 发布事件，订阅者删除对应 Redis key
- Redis 不可用时回退到内存 LRU 缓存（单实例场景）或每次实时计算（多实例无 Redis 场景，性能下降但功能正常）

### 4.2 配额计算公式（父池切分）

**总池 → 子团队/成员的分配**：

团队池的 `monthly_token_budget` 是该团队（含其所有子树）的月度总预算。
`allocated_to_children` 记录已显式切分给直接子团队的预算之和（受 `CHECK (allocated_to_children <= monthly_token_budget)` 约束）。

子团队从父团队切分到的预算 = 子团队的 `monthly_token_budget`（从父池扣减时累加到父的 `allocated_to_children`）。切分操作必须：
1. `SELECT ... FROM team_pool WHERE team_id = $1 FOR UPDATE`（行锁）
2. 校验 `allocated_to_children + new_child_budget <= monthly_token_budget`
3. 更新父 `allocated_to_children`
4. 插入/更新子团队 `team_pool`

**成员个人配额**：

成员在团队内的月度配额 = 该成员命中规则的 `token_quota_multiplier` 相乘 × 团队可分配给成员的预算池。

具体公式：
```
base_member_quota  = (team_pool.monthly_token_budget - team_pool.allocated_to_children) / active_member_count
multiplier         = Π (rule.effect.token_quota_multiplier for rule in matched_rules)
effective_quota    = base_member_quota * multiplier
```

- `active_member_count` 为当月内有过活动的成员数（按月统计缓存，Redis key `team:active_members:{team_id}:{month}`）
- `token_quota_multiplier` 乘法叠加：两条 multiplier=2 的规则最终为 4x（不是相加），这一语义在 UI 中明确展示并提供**实时预览**
- UI 实时预览：在规则编辑页面，管理员可选择一个测试用户，前端实时请求 `GET /api/teams/:id/rules/preview?uid=...` 返回最终 calculated_quota

### 4.3 自动打标与重评估

以下事件触发受影响用户的规则**重新评估**（后台异步执行，不阻塞请求）：

1. **用户加入团队**：为该用户计算规则并预热缓存
2. **用户邮箱变更**：重算该用户在所有所属团队的规则
3. **规则创建/修改/删除**：
   - 若规则包含 `uids` 条件：仅重算这些 uid
   - 若规则包含 `groups` 条件：重算这些组下所有成员
   - 若规则包含 `email_domains` 或无精确条件：重算团队内所有成员
   - 重算任务入队（AsyncIO task 或 Celery/RQ），批量执行，延迟不超过 10 秒
4. **组成员变更**：重算该组所有成员

重评估任务幂等：以 `(uid, team_id)` 为去重 key，避免重复计算。

### 4.4 优先级算法（REAL 中点法）

- 字段定义：`priority REAL NOT NULL DEFAULT 100.0`
- **无 UNIQUE 约束**，允许相同优先级
- 新规则默认 priority = 100.0
- 规则排序：前端提供拖拽排序，后端采用**中点插入算法**：
  - 在规则 A（priority=P_A）和规则 B（priority=P_B）之间插入新规则时，新 priority = (P_A + P_B) / 2
  - 由于 REAL（float8）有 52 位尾数精度，在正常使用下（几千次插入）不会出现精度不足
  - 当浮点精度不足（P_A == P_B 或差值小于 epsilon）时，触发批量重排：将该团队所有规则 priority 均匀重置为 100, 200, 300... 然后通知前端刷新
- 管理员也可手动输入 priority 值（高级模式）

### 4.5 冲突处理

当两条或多条规则 priority 完全相同（无法通过中点法避免，或管理员手动设置）：

- **不**抛数据库错误（无 UNIQUE 约束）
- 运行时规则引擎检测到同优先级规则：
  - 应用顺序按 `rule_id`（UUID v7 时间序或创建时间）升序，即**先创建的先应用**
  - 记录 WARNING 日志
  - 通过通知系统向 Team Admin 发送"规则优先级冲突"告警，列出冲突规则名，建议调整
- 前端规则列表中，同优先级规则显示"优先级冲突"黄色标记，提示管理员调整

---

## 5. LLM 错误检测与配额处理

### 5.1 错误码分类

LLM 调用失败时，`on_llm_error` 钩子收到标准化的 `LLMError`：

| 错误类型 | HTTP 状态（来自 provider） | 触发动作 |
|---------|---------------------------|---------|
| `AUTH_INVALID` | 401 | key 失效，触发 `LLMFallback` 切换到下一个可用 key（个人→团队池→系统兜底） |
| `RATE_LIMITED` | 429 | 退避重试（指数退避，最多 2 次），仍失败则触发 fallback 切换 key/模型 |
| `QUOTA_EXCEEDED` | 402/429 (insufficient_quota) | 标记当前 key 对应配额为耗尽，立即 fallback；同时触发 `quota.exhausted` 事件 |
| `MODEL_NOT_FOUND` | 404 | 从 allow_models 中移除该模型，fallback 到同 provider 的备选模型 |
| `OVERLOADED` | 500/503 | 退避重试 1 次，仍失败则 fallback |
| `TIMEOUT` | （客户端超时） | 退避重试 1 次，仍失败则 fallback |
| `UNKNOWN` | 其他 | 记录日志，向用户返回 502（不自动降级） |

所有 fallback 链路由 `on_llm_pre_call` 和 `on_llm_error` 协同实现，核心不内置任何 provider-specific 错误处理。

### 5.2 余额查询与超支容忍

**余额缓存**：
- 团队池/个人 key 的上游 provider 余额（若 provider 支持查询）通过后台任务每 5 分钟刷新一次，写入 `team_pool.balance_cached`
- 每次 LLM 调用前读取缓存，不实时查询（避免增加调用延迟）

**超支容忍（Grace Overshoot）**：
- 由于缓存存在 5 分钟延迟，可能出现"缓存显示余额充足但实际已耗尽"的时间窗
- 容忍额度：**$1.00 USD**（可通过配置 `billing.overshoot_tolerance_usd` 调整）
- 调用前检查：若 `balance_cached - estimated_cost < -overshoot_tolerance_usd`，拒绝调用
- 调用后检查：`on_llm_post_call` 记录实际 usage 后，若检测到实际超支（余额已为负且绝对值超过容忍额），立即将对应 pool 标记为"exhausted"（写入 Redis 标记位 `pool_exhausted:{team_id}`，TTL 到下一个余额刷新周期），后续请求快速失败
- 超支事件通过 EventBus 通知，Team Admin 收到"余额透支"通知

### 5.3 原子配额扣减

配额扣减必须原子，避免并发超扣：

```sql
UPDATE quota_snapshots
SET used_tokens = used_tokens + $1,
    updated_at = now()
WHERE team_id = $2
  AND uid = $3
  AND period_month = $4
RETURNING used_tokens, total_quota;
```

- 该语句是单次原子 UPDATE+RETURNING，无需事务中的 SELECT FOR UPDATE
- 返回后应用层判断：若 `used_tokens > total_quota`，说明本次调用已超配额
- 并发冲突：PostgreSQL 行级锁自动处理并发；若检测到序列化失败（极少数情况），乐观重试最多 3 次
- 若 `used_tokens > total_quota` 且超出量小于 `overshoot_tolerance_tokens`（对应 $1 容差换算），调用仍允许（因为 LLM 调用已发出，token 已消耗），但返回 `exceeded=true` 给调用方用于显示提示；若超量超过容差则**仅记录到审计**（因为是事后检测），并立即触发 pool 耗尽标记

配额重置：每月 1 日 UTC 00:00 由后台任务为所有活跃用户/团队创建新月份快照，used_tokens = 0，total_quota 按规则重新计算。

### 5.4 降级流程

完整的 LLM 调用降级链：

1. `on_llm_pre_call` 按插件顺序调用：
   - billing 插件检查配额，若已耗尽则抛出 `QuotaExceededError`（用户可见错误）
   - team 插件选择使用 pool key 还是 personal key，返回 `LLMOverride(api_key=...)` 若需要
   - auth 插件注入 trace 信息
2. 核心执行 LLM 调用
3. 若成功：
   - `on_llm_post_call` 观察型触发：billing 原子扣减配额、audit 记录日志、team 更新统计
4. 若失败：
   - `on_llm_error` 拦截型按顺序调用：
     - 第一个插件返回 `LLMFallback` → 核心使用新参数**重试一次**（重试不重新走 pre_call 链，直接调用；若需重新走链则返回特殊 `LLMFallback(reenter_pre_call=True)`）
     - 无插件返回 fallback → 向用户返回错误
   - 单次 LLM 请求最多触发 **1 次** fallback 重试（避免无限循环）
   - 所有 fallback 尝试均记录到 audit_logs

---

## 6. 权限矩阵

| 操作 | System Admin | Team Owner | Team Admin | Team Member | Anonymous |
|------|:---:|:---:|:---:|:---:|:---:|
| 创建团队 | ✓ | ✗ | ✗ | ✗ | ✗ |
| 删除团队 | ✓ | ✓（自己的） | ✗ | ✗ | ✗ |
| 转让团队所有权 | ✗ | ✓ | ✗ | ✗ | ✗ |
| 邀请/移除成员 | ✓（跨团队） | ✓ | ✓ | ✗ | ✗ |
| 修改成员角色 | ✓ | ✓ | ✓（不能设 Owner） | ✗ | ✗ |
| 创建/编辑规则 | ✗ | ✓ | ✓ | ✗ | ✗ |
| 删除规则 | ✗ | ✓ | ✓ | ✗ | ✗ |
| 配置团队池密钥 | ✗ | ✓ | ✓ | ✗ | ✗ |
| 设置团队月预算 | ✗ | ✓ | ✗ | ✗ | ✗ |
| 切分预算给子团队 | ✗ | ✓ | ✗ | ✗ | ✗ |
| 创建会议（团队内） | ✗ | ✓ | ✓ | ✓ | ✗ |
| 查看团队所有会议 | ✗ | ✓ | ✓ | ✗（仅自己的） | ✗ |
| 加入公开会议围观 | ✗ | ✓ | ✓ | ✓（同团队） | ✓（受 captcha/anon_cap 限制） |
| 在会议中发言/干预 | ✗ | ✓ | ✓ | ✓（自己创建的或受邀） | ✗ |
| 查看审计日志 | ✓ | ✓（自己团队） | ✓（自己团队） | ✗ | ✗ |
| 管理插件（启用/禁用） | ✓ | ✗ | ✗ | ✗ | ✗ |
| 查看系统监控 | ✓ | ✗ | ✗ | ✗ | ✗ |
| 重新生成 setup token | ✓ | ✗ | ✗ | ✗ | ✗ |
| 管理个人 API Key | ✓ | ✓ | ✓ | ✓ | ✗ |
| 管理个人配额使用 | ✓ | ✓ | ✓ | ✓ | ✗ |

特殊说明：
- System Admin 拥有跨团队只读审计能力，但不自动拥有团队内的操作权限（除非也是成员）
- Team Owner 是每个团队唯一能转让所有权、设置月预算总额的角色
- 子团队的 Owner 默认继承父团队的 Member 身份（可参与父团队会议），反之不成立

---

## 7. API 设计

### 7.1 通用约定

**基础路径**：所有 API 以 `/api` 开头

**鉴权**：
- 除 `/api/setup`、`/api/auth/login`、`/api/auth/csrf`、`/ws/anon/*` 外，所有端点要求有效 JWT
- JWT 通过 httpOnly Secure Cookie 传递（见 §11.1）
- 状态变更请求（POST/PUT/PATCH/DELETE）需要 CSRF token（见 §11.5）

**分页**：所有列表端点统一使用**游标分页**：
- 请求参数：`?limit=20&cursor=<opaque_cursor>`
  - `limit` 默认 20，最大 100
  - `cursor` 首次请求不传，后续请求传上一次响应中的 `next_cursor`
- 响应格式：
  ```json
  {
    "data": [ ... ],
    "pagination": {
      "next_cursor": "opaque_string_or_null",
      "has_more": true
    }
  }
  ```
- 游标基于排序键的不透明 base64 编码（如 `base64("1700000000000:uuid")`），防止客户端解析构造

**标准错误响应**：

```json
{
  "error": {
    "code": "string_code",
    "message": "human readable message",
    "details": {}
  }
}
```

**HTTP 状态码使用规范**：

| 状态码 | 含义 | 典型 code |
|--------|------|-----------|
| 200 | 成功 | - |
| 201 | 创建成功 | - |
| 204 | 删除成功（无 body） | - |
| 400 | 请求校验失败 | `validation_error` |
| 401 | 未认证 | `unauthenticated` |
| 403 | 已认证但无权限 | `forbidden`, `team_required` |
| 404 | 资源不存在 | `not_found` |
| 409 | 资源冲突 | `slug_taken`, `member_already_exists` |
| 413 | 请求体过大 | `payload_too_large` |
| 429 | 限流 | `rate_limited` |
| 503 | 所需插件未启用 | `plugin_unavailable:team` |

### 7.2 核心 API 列表

**Auth（由 auth 插件注册）**
- `POST /api/auth/register` — 自助注册（若开启）
- `POST /api/auth/login` — 登录，Set-Cookie JWT
- `POST /api/auth/logout` — 登出，清除 Cookie
- `GET  /api/auth/me` — 当前用户信息
- `GET  /api/auth/csrf` — 获取 CSRF token（double-submit）
- `POST /api/setup` — 初始化首个管理员（见 §2）

**Teams**
- `POST /api/teams` — 创建团队
- `GET  /api/teams` — 列出我加入的团队（支持游标分页）
- `GET  /api/teams/:id` — 团队详情
- `PATCH /api/teams/:id` — 修改团队基础信息（name, slug）
- `DELETE /api/teams/:id` — 删除团队（软删除，Owner 仅可）
- `GET  /api/teams/:id/tree` — 子团队树（Phase 4）
- `GET  /api/teams/:id/settings` — 团队设置
- `PATCH /api/teams/:id/settings` — 更新设置（Admin+）
- `GET  /api/teams/:id/pool` — 团队池信息（余额、预算）
- `PATCH /api/teams/:id/pool` — 更新池配置（密钥、预算；Owner 可改预算，Admin 可改密钥）

**Members**
- `GET  /api/teams/:id/members` — 列出成员（分页）
- `POST /api/teams/:id/members/invite` — 邀请成员（by email）
- `PATCH /api/teams/:id/members/:uid` — 修改角色
- `DELETE /api/teams/:id/members/:uid` — 移除成员
- `PATCH /api/teams/:id/members/batch` — 批量修改角色
  - 请求体：`{ "uids": ["..."], "role": "admin" }`
  - 最多 100 人/次
- `POST /api/teams/:id/members/leave` — 当前用户主动退出（Owner 不能直接退出，须先转让）

**Groups（Phase 4）**
- CRUD `/api/teams/:id/groups`
- `PUT /api/teams/:id/groups/:gid/members` — 批量设置组成员

**Rules**
- `GET  /api/teams/:id/rules` — 列出规则（按 priority 排序）
- `POST /api/teams/:id/rules` — 创建规则
- `PATCH /api/teams/:id/rules/:rid` — 更新规则
- `DELETE /api/teams/:id/rules/:rid` — 删除规则
- `POST /api/teams/:id/rules/reorder` — 批量重新排序（传入有序 rule_id 列表，后端重新赋 priority）
- `GET  /api/teams/:id/rules/preview?uid=...` — 规则效果实时预览

**API Keys**
- `GET  /api/user/api-keys` — 列出个人 key
- `POST /api/user/api-keys` — 添加个人 key
- `PATCH /api/user/api-keys/:id` — 修改 label/default
- `DELETE /api/user/api-keys/:id` — 删除个人 key
- `POST /api/teams/:id/pool/rotate-key` — 轮换团队池 key（Owner/Admin）

**Meetings（核心提供，team 插件通过钩子扩展）**
- 现有会议 API 路径保持不变
- 新增查询参数：`?team_id=...` 过滤团队下的会议（team 插件在 `on_meeting_creating` 时写入 metadata）
- 团队会议列表：`GET /api/teams/:id/meetings`（team 插件注册）

**Anonymous**
- `WS   /ws/anon/:meeting_id` — 匿名围观 WebSocket（只读）
- `GET  /api/public/meetings/:id/meta` — 公开会议元信息（标题、创建者昵称、围观人数），用于围观入口页面
- `POST /api/public/meetings/:id/verify-captcha` — （可选）验证 CAPTCHA，返回一次性围观 token

**Admin（System Admin）**
- `GET  /api/admin/plugins` — 列出插件状态（健康度、版本、tier）
- `POST /api/admin/plugins/:name/disable` — 热禁用插件（CORE 拒绝）
- `POST /api/admin/plugins/:name/enable` — 热启用
- `GET  /api/admin/stats` — 系统级统计
- `POST /api/admin/setup-token/regenerate` — 重新生成 setup token

### 7.3 WebSocket 协议（匿名）

`/ws/anon/:meeting_id` 连接建立后：
- 服务端仅下行推送 `agent.message` 类型事件
- 客户端发送的任何消息被忽略并记录审计
- 服务端过滤掉所有上行控制类事件：
  - 过滤 `user.*`、`intervene`、`control`、`file.*`、`admin.*` 命名空间
  - 仅放行（下行）：`agent.message`、`meeting.meta`（标题变更等公开信息）、`meeting.end`
- 连接建立时：
  1. 校验 meeting 是否存在且 `metadata["team"].visibility == "public"`（或 legacy 公开标记）
  2. 检查 anon_cap 是否已满（Redis 计数 `anon:meeting:{mid}`）
  3. 若 captcha_required，要求查询参数 `?captcha_token=...` 有效
  4. 速率限制：同一 IP 每分钟最多 10 个匿名连接（Redis 滑动窗口）
  5. 记录 audit_logs（IP、UA、meeting_id）
  6. 连接建立后 INCR Redis 计数；断开 DECR

---

## 8. 前端页面结构

前端按 Namespace 切换上下文，UI 分为以下主要页面/模块：

**全局层**
- 登录/注册页
- Setup 页（首次初始化，无导航）
- 顶部导航：当前 Namespace 切换器（个人 / 团队 A / 团队 B）、用户菜单（个人设置、API Key 管理、登出）、通知中心
- System Admin 额外入口：系统管理后台（插件、监控、统计）

**个人空间（默认）**
- 仪表盘：本月个人 token 用量、最近会议、个人 API Key 状态
- 会议列表
- 会议详情（与现有一致）
- 个人设置：个人资料、密码、个人 API Key 管理、用量统计

**团队空间（选中某团队时）**
- 团队仪表盘：本月团队池用量、余额、活跃成员数、告警
- 成员管理：成员列表、邀请、角色变更、批量操作
- 组管理（Phase 4）
- 规则管理：规则列表（支持拖拽排序）、规则编辑器（含实时预览面板）、冲突提示
- 密钥与预算：池密钥配置、月预算设置、向子团队切分预算（Phase 4）
- 团队会议列表
- 审计日志
- 团队设置：join policy、允许域名、匿名围观开关、围观人数上限、CAPTCHA 开关
- 团队树视图（Phase 4）

**公开围观页面**
- 会议元信息页（无需登录）
- 围观直播间：实时 agent 消息流，无输入框/控制按钮
- CAPTCHA 验证组件（若开启）

**设计要点**
- 所有列表页统一使用游标分页组件（infinite scroll 或"加载更多"按钮）
- 规则编辑器提供实时预览侧栏：输入测试用户邮箱/ID，即时显示最终配额和可用模型
- 配额/用量展示使用进度条，接近上限时变色（黄→红）
- 通知中心使用 WebSocket 推送，展示配额预警、余额不足、规则冲突、成员邀请等

---

## 9. 关键流程

### 9.1 用户发起 LLM 调用（完整路径）

```
HTTP Request
  → Auth Middleware（auth 插件中间件）
      验证 Cookie JWT；设置 ContextVar auth.current_user
  → Team Middleware（team 插件，若启用）
      根据请求上下文（X-Conclave-Team-Id 或 meeting 归属）解析当前团队；
      验证成员身份；设置 ContextVar team.current_team
  → Core: create_llm_task()
      构造 CallContext
      → [Interceptor] on_llm_pre_call 链：
          billing:  检查配额/余额 → 若不足抛 QuotaExceededError
          team:     根据当前团队/规则选择 key → 返回 LLMOverride(api_key=pool_key) 或 None
          auth:     注入 trace_id 等
      → Core: 调用 LLM provider
          成功 → [Observer] on_llm_post_call 链：
              billing: 原子扣减配额；检测超支 → 若超支标记 pool exhausted
              audit:   写 token_usage + audit_logs
              team:    更新团队统计缓存
          失败 → [Interceptor] on_llm_error 链：
              billing: 若 QUOTA_EXCEEDED，标记 exhausted 并返回 None（不 fallback）
              team:    若 AUTH_INVALID with pool key，fallback 到 personal key（若用户有）
              最多 1 次 fallback 重试
      → 返回流式响应给用户
```

### 9.2 创建团队会议

```
POST /api/meetings  (带 X-Conclave-Team-Id)
  → Auth Middleware: 识别用户
  → Team Middleware: 校验团队成员身份
  → Core: meeting_service.create()
      构造 meeting 对象（此时 metadata = '{}'）
      → [Interceptor] on_meeting_creating 链：
          team:  校验用户在该团队的创建权限；
                 检查规则 max_meeting_length；
                 在 ctx 中设置 metadata_patch["team"] = { team_id, visibility: "private", ... }
          billing: 检查团队池/个人配额状态
      → Core: INSERT meetings（metadata 由核心从 ctx.metadata_patch 合并后写入；核心不解读内容）
      → [Observer] on_meeting_created 链：
          audit: 写审计
          team:  更新团队最近会议统计
          notification: 通知相关成员
```

### 9.3 访问会议

```
WS /ws/meetings/:id   （已认证用户）
  → Auth Middleware
  → Core: 加载 meeting
  → [Interceptor] on_meeting_accessing 链：
      team:
        若 meeting.metadata["team"] 存在：
          - 校验当前用户是团队成员，或会议是公开的
          - 校验规则中是否允许该用户访问该模型/会议
          - 抛 AccessDeniedError 拒绝
  → 通过 → 建立 WS 连接，加入会议房间

WS /ws/anon/:id       （匿名围观）
  → 独立端点，不经过 Auth Middleware
  → Anon rate limit + captcha 校验 + anon_cap 检查
  → [Interceptor] on_meeting_accessing 链：
      team: 校验会议 metadata["team"].visibility == "public"
  → 通过 → 建立只读连接，事件过滤器激活（仅下行 agent.message）
```

### 9.4 配额扣减（原子）

```
on_llm_post_call(ctx, req, resp, usage):
  tokens = usage.total_tokens
  team_id = ctx.team_id or PERSONAL_NAMESPACE_ID
  period = first_day_of_month(now())

  for attempt in range(3):
      row = await db.fetch_one(
          "UPDATE quota_snapshots SET used_tokens = used_tokens + $1, updated_at = now() "
          "WHERE team_id = $2 AND uid = $3 AND period_month = $4 "
          "RETURNING used_tokens, total_quota",
          tokens, team_id, ctx.uid, period
      )
      if row is None:
          # 本月快照不存在，创建（可能是月初一瞬间）
          await create_snapshot(team_id, ctx.uid, period)
          continue
      if row.used_tokens > row.total_quota:
          if row.used_tokens - tokens <= row.total_quota:
              # 本次调用跨过了配额线，标记 exceeded
              await redis.setex(f"quota_exceeded:{team_id}:{ctx.uid}:{period}",
                                ttl_remaining_in_month(), "1")
              await eventbus.publish("quota.exhausted", {...})
          # 不回滚（token 已消耗）
      break
  else:
      logger.error("quota update failed after 3 retries", uid=ctx.uid, team_id=team_id)
```

### 9.5 插件降级与 fallback

```
场景：team 插件配置了 pool key，但该 key 被上游吊销（401 AUTH_INVALID）

1. Core 调用 LLM → 收到 401
2. on_llm_error 触发：
   - billing 插件：识别为 AUTH_INVALID，不处理（不是配额问题）
   - team 插件：
     * 识别当前使用的是 pool key
     * 检查用户是否配置了个人 key
     * 若有 → 返回 LLMFallback(api_key=user_personal_key, model=req.model, base_url=None, reenter_pre_call=False)
     * 若无 → 返回 None
3. Core 收到 fallback → 使用新参数直接重试（不再走 pre_call）
4. 若重试成功 → post_call 链记录用量（注意：这次扣减应到个人配额，billing 插件根据实际使用的 key 判断扣减对象）
5. 若仍失败 → 向用户返回 401 + "当前团队密钥已失效，请联系管理员"
6. 异步：audit 记录；notification 通知 Team Admin "团队池密钥失效"
```

---

## 10. 代码改造点

以下列出核心代码需要改动的具体位置与内容。

### 10.1 新增：`conclave/plugins/` 包

```
conclave/plugins/
  __init__.py
  base.py              # PluginBase、PluginTier、所有 Mixin、LLMOverride/LLMFallback 数据类
  registry.py          # PluginRegistry（实例）、拓扑排序、钩子调度、超时/健康检查
  context.py           # ContextVar 容器（namespaced）、CallContext、AppContext
  eventbus.py          # EventBus（内存/Redis 可选）
  hooks.py             # HookName 枚举
  exceptions.py        # PluginError、PluginUnavailable、QuotaExceededError、AccessDeniedError
```

### 10.2 新增：`conclave/plugins/builtin/` 内置插件

```
conclave/plugins/builtin/
  auth/                # Phase 1a：从核心抽出
    __init__.py
    plugin.py          # AuthPlugin(CORE, dependencies=[])
    routes.py
    middleware.py
    jwt.py
    password.py
    models.py
  billing/             # Phase 1b：新建
    __init__.py
    plugin.py          # BillingPlugin(CROSSCUTTING, dependencies=["auth"])
    quota.py
    balance.py
    models.py
  audit/               # Phase 1b：新建
    __init__.py
    plugin.py          # AuditPlugin(CROSSCUTTING, dependencies=["auth"])
    middleware.py
  team/                # Phase 2：核心多租户插件
    __init__.py
    plugin.py          # TeamPlugin(OPTIONAL, dependencies=["auth","billing?"])
    routes/
      teams.py
      members.py
      rules.py
      groups.py
      pool.py
      anon.py
    services/
      rules_engine.py
      quota_calc.py
      key_selector.py
      tree.py
    models.py
    encryption.py
    migrations/        # SQL 迁移脚本
```

### 10.3 核心改造点

**`conclave/app.py`（create_app 工厂）**
- 初始化 PluginRegistry
- 注册内置插件
- 调用 `await registry.resolve_and_load()`
- 通过 `registry.register_routers(app)` / `register_middlewares(app)` 挂载
- 将 registry 挂到 `app.state.registry`

**`conclave/db/` 迁移**
- 新增 `meetings.metadata JSONB NOT NULL DEFAULT '{}'` 列 + GIN 索引
- 新增插件表（§3.3 所有 DDL）
- 修正 `user_api_keys` 部分唯一索引
- 启用 LTREE 扩展
- 创建 token_usage 初始分区

**`conclave/llm.py`（LLM 调用入口）**
- 调用 provider 前：执行 `registry.call_interceptors("on_llm_pre_call", ctx, req)`，根据返回的 LLMOverride 修改请求参数
- 成功后：`registry.call_observers("on_llm_post_call", ctx, req, resp, usage)`（通过 asyncio.create_task，不阻塞响应流结束）
- 失败后：`registry.call_interceptors("on_llm_error", ctx, req, err)`，最多 1 次 fallback 重试
- 所有钩子调用包装 200ms 超时

**`conclave/runner.py`（会议/任务执行）**
- meeting 创建前：`registry.call_interceptors("on_meeting_creating", ctx, payload)`
- meeting 插入后：`registry.call_observers("on_meeting_created", ctx, meeting_id, metadata_snapshot)`
- WebSocket 接入会议时：`registry.call_interceptors("on_meeting_accessing", ctx, meeting)`

**`conclave/auth/` 重构**
- 现有认证逻辑从核心迁移到 `plugins/builtin/auth/`
- 核心通过标准 Mixin 协议消费，不再直接 import auth 实现

**配置加载**
- 新增配置节：`[plugins]`、`[plugin.timeout]`、`[plugin.team]`、`[plugin.billing]`
- 主密钥从 `CONCLAVE_MASTER_KEY` 环境变量加载

### 10.4 启动顺序

```
1. 加载配置 / 环境变量
2. 初始化 DB 连接池 / Redis（若配置）
3. 构造 PluginRegistry
4. 注册内置插件实例
5. registry.resolve_and_load():
   a. 拓扑排序
   b. 按序调用 on_startup（CORE 失败→终止，其他失败→unhealthy/disabled）
6. 构造 FastAPI app
7. 注册中间件（反向拓扑序：被依赖者先包外层）
8. 注册路由（每个插件的 RouterMixin）
9. 启动健康检查后台任务（30s 间隔）
10. 启动事件监听后台任务
11. 进入服务
```

---

## 11. 安全设计

### 11.1 JWT Cookie 方案

放弃 localStorage 存储 JWT，全部使用 Cookie：

**Cookie 属性**：
- `HttpOnly`：JS 无法读取，防御 XSS 窃取 token
- `Secure`：仅 HTTPS 传输（本地开发环境可通过配置关闭）
- `SameSite=Strict`：跨站请求不携带，强防御 CSRF（再加 double-submit token 作为第二层）
- `Path=/`
- `Max-Age`：access token 15 分钟；refresh token 7 天（单独的 refresh cookie）

**Token 类型**：
- Access Token（短寿命，15min）：包含 uid、is_system_admin、roles 快照
- Refresh Token（长寿命，7d）：HttpOnly Secure SameSite=Strict，存储在 DB 可吊销
- 每次刷新轮换 refresh token（rotation），旧 token 立即失效

**登录流程**：
1. `POST /api/auth/login` 验证用户名密码
2. 生成 access + refresh token
3. Set-Cookie: `conclave_access=...; HttpOnly; Secure; SameSite=Strict; Max-Age=900`
4. Set-Cookie: `conclave_refresh=...; HttpOnly; Secure; SameSite=Strict; Max-Age=604800; Path=/api/auth/refresh`
5. 返回 body `{ "csrf_token": "..." }` 供客户端读取

### 11.2 AES-256-GCM 加密

见 §3.6 加密格式规范。补充要点：
- 主密钥长度严格 32 字节（AES-256）
- Nonce 每次加密使用 `secrets.token_bytes(12)` 生成，严禁重用
- 解密时必须验证 tag，tag 无效视为密文篡改，抛出 `DecryptionError`
- 密钥轮换（Phase 5+）：`v{}` 前缀支持多版本密钥共存，解密时按版本查找对应密钥；新加密始终使用当前版本
- 内存中密钥使用后尽快释放（避免长时间驻留）；不在日志中打印密钥或明文

### 11.3 /setup 防护

详见 §2。补充要点：
- setup token 存储时使用 SHA-256 哈希（与密码一致），数据库不存明文
- 登录尝试失败不透露"用户名是否存在"，统一返回"凭证无效"
- setup 成功后立即签发管理员会话，但要求管理员首次登录后强制修改密码（若密码为初始生成）

### 11.4 匿名围观防护

详见 §7.3 与 §1.4。多层防护：
1. **连接数上限**：`anon_cap`（默认 100）按会议计数（Redis `INCR/DECR`，连接断开保证 DECR 使用 finally 块）
2. **速率限制**：同一 IP 每分钟 10 次匿名 WS 连接尝试
3. **事件过滤**：服务端硬编码白名单，只下行 `agent.message`、`meeting.meta`、`meeting.end`；所有用户/控制/文件事件丢弃
4. **审计**：每个匿名连接记录 IP、UA、连接时长到 audit_logs，保留 90 天
5. **CAPTCHA**（可选）：开启后，必须先调用 `/verify-captcha` 获取一次性 `anon_token`（5 分钟有效，单次使用），WS 连接时校验
6. **不注入任何用户上下文**：匿名连接 ContextVar 中 `auth.current_user` 为 None，钩子中明确区分
7. **带宽控制**：匿名连接的下行消息速率限制（默认 100 msg/s/connection），防止刷屏攻击

### 11.5 CSRF 防护

采用 **Double-Submit Cookie 模式**：

1. 登录成功后，除 HttpOnly Cookie 外，额外下发一个 `csrf_token`（非 HttpOnly，JS 可读）
   - Set-Cookie: `csrf_token=<random>; Secure; SameSite=Strict; Path=/`
   - 响应 body 同时返回 `{ "csrf_token": "..." }`
2. 客户端读取 `csrf_token` cookie 值（或响应字段），在所有状态变更请求（POST/PUT/PATCH/DELETE）中携带 Header：`X-CSRF-Token: <value>`
3. 服务端中间件校验：
   - 对安全方法（GET/HEAD/OPTIONS）跳过
   - 对状态变更方法：比较 Cookie 中的 csrf_token 与 Header 中的值，必须一致
   - 不一致返回 403 `csrf_violation`
4. WebSocket 连接：在 URL query 参数中携带 `?csrf=...`（仅用于已认证 WS，匿名 WS 不走 CSRF）
5. csrf_token 随会话刷新，登录/登出时轮换

该方案与 SameSite=Strict 形成双重防御：即使 SameSite 被浏览器策略变化绕过，double-submit 仍有效。

---

## 12. 数据迁移方案（Migration Playbook）

### 12.1 迁移原则

- 所有变更**向后兼容**：v0.4 代码必须能在 v0.3 数据库上运行（不丢数据），v0.3 代码也能在 v0.4 数据库上运行（新列/新表被忽略）
- 迁移分阶段执行，每阶段可独立回滚
- 生产迁移前必须在 staging 环境完整演练

### 12.2 现有数据处理

**用户数据**
- 现有 `users` 表保留，bcrypt 密码哈希与 auth 插件的 passlib/bcrypt 配置完全兼容，无需重哈希
- uid 映射：保持现有 UUID 不变；is_system_admin 字段初始化为 FALSE；首次 setup 创建的用户设为 TRUE
- 现有个人 API Key（若有）迁移到 `user_api_keys` 表，使用新的 AES-256-GCM 格式重新加密（迁移脚本读取旧明文或旧加密格式，用新主密钥重新加密）

**会议数据**
- 所有现有会议执行：
  ```sql
  UPDATE meetings SET metadata = '{}' WHERE metadata IS NULL OR metadata = '';
  ```
- 现有会议隐式属于个人 Namespace（`owner_uid` 的个人空间），team 插件读取时若 `metadata["team"]` 不存在即视为个人会议
- 不进行数据回填（不把 owner_uid 映射到 metadata），保持核心简洁

**其他数据**
- v0.3 若已存在 team 相关试验表，迁移脚本检测并转换（若不存在则直接创建新表）
- audit_logs、token_usage 等历史表数据保留，迁移到新分区结构（通过 INSERT ... SELECT 在迁移窗口执行，或保留旧表作为归档）

### 12.3 迁移步骤（按顺序）

**Step 1 — 数据库准备（可在线执行，不影响 v0.3 运行）**
- 启用 LTREE 扩展
- 为 `meetings` 表添加 `metadata JSONB NOT NULL DEFAULT '{}'` 列 + GIN 索引
- 将现有 meetings 的 metadata 初始化为 '{}'
- 创建所有插件新表（§3.3 DDL）
- 创建 token_usage 当月分区
- 此时 v0.3 代码继续正常运行（新列/新表被忽略）

**Step 2 — 部署 v0.4 代码（仅启用 auth + billing + audit 插件）**
- 部署新二进制/镜像
- 配置 `CONCLAVE_MASTER_KEY` 环境变量
- 配置 `plugins.enabled = ["auth", "billing", "audit"]`（team 插件不启用）
- 启动服务
- 验证：
  - 登录/登出正常
  - 个人 API Key 正常
  - LLM 调用正常（走 auth+billing 链路，billing 在无团队场景下回退到个人配额/系统兜底）
  - 审计日志正常写入
- 若验证失败：直接回滚到 v0.3 二进制，数据库无需回滚（metadata 列与新表保留不影响 v0.3）

**Step 3 — 执行 setup（若首次部署）或迁移 System Admin**
- 若为全新实例：访问 `/setup` 创建管理员
- 若为升级实例：将现有 admin 用户 `is_system_admin = TRUE`

**Step 4 — 启用 team 插件**
- 通过配置或热开关启用 team 插件：`SREM conclave:plugins:disabled team`（或重启加载）
- 验证 team 插件健康检查通过
- 通过 UI 创建第一个团队（推荐使用 System Admin 账号创建测试团队验证）
- 邀请少量用户进入测试团队，验证：
  - 创建团队会议
  - 团队池密钥配置
  - 配额扣减
  - 匿名围观

**Step 5 — 数据迁移（个人 API Key 等）**
- 运行离线脚本将旧版个人 key 数据迁移到 `user_api_keys` 并重新加密
- 运行脚本为现有用户创建当月 quota_snapshots
- 验证数据完整性

**Step 6 — 全量开放**
- 开放团队创建/邀请功能给所有用户
- 启用监控告警
- 观察 24-48 小时

### 12.4 回滚方案

每个阶段均可独立回滚：
- **数据库回滚**：不执行 DROP。metadata 列和新表保留在数据库中，v0.3 代码不会查询它们，完全不影响功能。后续再次升级时这些结构已存在，迁移脚本使用 IF NOT EXISTS 幂等处理。
- **代码回滚**：直接重新部署 v0.3 二进制。因为 v0.4 核心 API 路径保持兼容（会议/认证端点未变路径），回滚后用户体验一致。
- **插件回滚**：通过热开关禁用 team 插件，用户回到纯个人空间体验，所有团队数据保留在数据库中，下次启用时状态恢复。
- **数据回滚**：若迁移脚本出错，使用迁移前的数据库备份恢复（推荐在 Step 1 前执行一次全量备份）。

---

## 13. 配额重置策略

**重置周期**：自然月（UTC 00:00）

**重置任务**：
- 由 billing 插件注册定时任务（APScheduler 或 asyncio 周期任务）
- 每月 1 日 UTC 00:05（错开整点高峰）执行：
  1. 为所有上一月有活动的（uid, team_id）组合创建新月份的 `quota_snapshots` 记录：
     - `period_month = 当月第一天`
     - `used_tokens = 0`
     - `total_quota` 按当前规则重新计算（触发规则重评估）
  2. 重置 `team_pool.allocated_to_children` 的缓存校验（实际值由子团队预算之和决定，不重置数值，但刷新校验）
  3. 清理 Redis 缓存：`rules:*`、`quota_exceeded:*`、`pool_exhausted:*`
  4. 触发 `quota.reset` 事件，通知插件（例如 notification 插件发送"月度配额已重置"通知）

**新用户/新成员处理**：
- 新用户首次发起 LLM 调用时，若当月快照不存在，在原子扣减的 UPDATE 语句未命中时即时创建（见 §9.4 重试逻辑）
- 新成员加入团队时，立即为其创建当月快照（total_quota 按规则计算）

**跨月边界处理**：
- 月末最后一秒发起的长请求可能跨越重置点。处理方式：
  - LLM 调用开始时（on_llm_pre_call）确定 `period_month` 并记录到 CallContext
  - 扣减时使用调用开始时的 period_month，避免跨月误扣到新月份
  - 审计日志同时记录调用开始时间和结束时间

---

## 14. 监控与 SLO

### 14.1 关键指标（Metrics）

所有指标通过 Prometheus 格式暴露（`/metrics` 端点），核心与插件均可注册指标：

| 指标名 | 类型 | 标签 | 说明 |
|--------|------|------|------|
| `conclave_plugin_hook_duration_seconds` | Histogram | plugin, hook, tier | 钩子调用耗时（含超时截断） |
| `conclave_plugin_hook_errors_total` | Counter | plugin, hook, error_type | 钩子异常/超时计数 |
| `conclave_plugin_hook_timeouts_total` | Counter | plugin, hook | 钩子超时（>200ms）计数 |
| `conclave_plugin_health_status` | Gauge | plugin | 健康状态（1=健康，0=不健康） |
| `conclave_llm_call_duration_seconds` | Histogram | provider, model, team_id, fallback | LLM 总调用耗时 |
| `conclave_llm_call_overhead_seconds` | Histogram | - | 插件 pre_call+post_call 总开销 |
| `conclave_llm_fallbacks_total` | Counter | plugin, reason | fallback 触发次数 |
| `conclave_quota_check_duration_seconds` | Histogram | team_id | 配额检查耗时 |
| `conclave_quota_update_retries_total` | Counter | team_id | 配额原子 UPDATE 重试次数 |
| `conclave_balance_fetch_duration_seconds` | Histogram | provider | 上游余额查询耗时 |
| `conclave_balance_fetch_failures_total` | Counter | provider | 余额查询失败次数 |
| `conclave_anon_connections_active` | Gauge | meeting_id | 当前匿名围观连接数 |
| `conclave_anon_connections_total` | Counter | meeting_id | 历史匿名连接总数 |
| `conclave_ws_connections_active` | Gauge | type(auth/anon) | WS 活跃连接数 |
| `conclave_rule_cache_hits_total` | Counter | team_id | 规则缓存命中 |
| `conclave_rule_cache_misses_total` | Counter | team_id | 规则缓存未命中 |
| `conclave_rule_conflicts_total` | Counter | team_id | 同优先级规则冲突次数 |

### 14.2 SLO 目标

| 指标 | 目标 |
|------|------|
| 插件钩子 p50 延迟 | < 50ms |
| 插件钩子 p99 延迟 | < 200ms（超 200ms 即超时） |
| LLM 调用插件总开销 p99 | < 100ms |
| 插件健康检查频率 | 每 30 秒一次 |
| 插件健康故障恢复时间 | < 1 分钟（健康检查连续 2 次通过即恢复） |
| 配额原子扣减 p99 | < 20ms（单条 UPDATE，通常 <5ms） |
| 规则缓存命中率 | > 90%（正常负载下） |

### 14.3 告警规则

| 告警 | 条件 | 严重度 | 处理 |
|------|------|--------|------|
| 插件不健康 | `plugin_health_status == 0` 持续 > 1 分钟 | CRITICAL（CORE/CROSSCUTTING）/ WARNING（OPTIONAL） | 检查插件日志，必要时热禁用或重启 |
| 钩子超时率高 | `rate(hook_timeouts_total[5m]) / rate(hook_calls_total[5m]) > 5%` | WARNING | 定位慢插件，检查是否有外部 IO 阻塞 |
| 配额不一致 | `quota_snapshots.used_tokens > total_quota + overshoot_tolerance` 出现 | WARNING | 检查是否有并发问题或余额缓存失效 |
| 余额查询失败率高 | `rate(balance_fetch_failures[5m]) / rate(balance_fetch_total[5m]) > 10%` | WARNING | 检查 provider API 可达性 |
| LLM fallback 率高 | `rate(llm_fallbacks_total[10m]) / rate(llm_calls_total[10m]) > 20%` | WARNING | 检查 pool key 有效性、配额状态 |
| 匿名连接异常 | `anon_connections_active > anon_cap * 0.9` 持续 | INFO | 考虑提升容量或检查是否被刷 |

### 14.4 日志

- 插件加载、钩子调用（DEBUG 级含参数）、超时、异常、fallback、配额耗尽、匿名连接均记录结构化日志（JSON）
- 日志字段必须包含：plugin、hook、tier、duration_ms、trace_id、uid、team_id
- 审计日志独立写入 `audit_logs` 表，同时输出到应用日志（INFO 级）

---

## 15. 实施分期（重构后 Phase 0-5）

每个阶段有明确的交付物、验收标准和回滚计划。

### Phase 0 — 插件框架基础（1 周）

**内容**：
- 实现 `PluginBase`、所有 Mixin 协议类、PluginTier
- 实现 `PluginRegistry`：注册、拓扑排序、依赖解析、钩子调度（拦截型/观察型）、200ms 超时、健康检查
- 实现 `ContextVar` 容器、AppContext/CallContext
- 实现 `EventBus`（内存版，Redis pub/sub 预留接口）
- 实现插件热开关（Redis 键监听）
- 重构 `create_app()` 使用注册表
- 建立 `conclave/plugins/` 目录骨架

**验收标准**：
- 可编写一个测试插件（echo），注册后能在钩子中被调用
- 拓扑排序正确处理依赖顺序和循环依赖检测
- 拦截型钩子短路逻辑正确
- 观察型钩子所有插件均被调用
- 超时能正确跳过慢插件
- 热禁用插件后钩子不再被调用
- 单元测试覆盖率 > 80%

**回滚**：框架代码独立，未接入业务，直接删除 `conclave/plugins/` 即可（此阶段不涉及业务改造）。

### Phase 1a — Auth 插件抽取 + Setup 流程 + JWT Cookie 迁移（1 周）

**内容**：
- 将现有认证逻辑迁移到 `plugins/builtin/auth/`
- 实现 System Admin setup 流程（§2）
- JWT 改为 HttpOnly Secure SameSite=Strict Cookie + CSRF double-submit
- Refresh token rotation
- 中间件重构为 auth 插件注册

**验收标准**：
- 登录/登出/会话验证功能与 v0.3 一致
- Cookie 属性正确（浏览器 DevTools 可见 HttpOnly/Secure/SameSite）
- CSRF 校验对 POST 等请求生效
- Setup 流程在空库时可用，token 24h 过期、一次性使用、速率限制生效
- 现有 bcrypt 密码哈希可正常登录
- 单元测试 + E2E 登录流测试

**回滚**：auth 插件以 CORE tier 运行，若失败服务无法启动，立即回滚到 v0.3 二进制（或 Phase 0 前状态）。

### Phase 1b — 核心最小改造 + Billing/Audit 插件（1 周）

**内容**：
- `meetings` 表添加 metadata JSONB 列 + GIN 索引
- 在 `llm.py` 中埋入 pre_call/post_call/error 钩子点
- 在 `runner.py` 中埋入 meeting_creating/created/accessing 钩子点
- 实现 billing 插件（CROSSCUTTING）：个人配额、原子扣减、余额缓存、超支容忍
- 实现 audit 插件（CROSSCUTTING）：操作审计、token_usage 写入
- 创建所有插件表（§3.3）
- 迁移脚本（§12 Step 1）

**验收标准**：
- 核心 LLM 调用路径在无 team 插件时正常工作（auth + billing + audit 三插件协作）
- metadata 列存在，默认 '{}'，核心不写入任何业务数据
- 钩子超时保护有效（可注入一个 sleep(300ms) 的测试插件验证）
- 配额原子扣减并发测试（100 并发）不超扣
- 审计日志记录所有 LLM 调用
- 旧会议数据可正常访问

**回滚**：回滚二进制到 v0.3（或 Phase 1a 末状态），数据库保留新列和新表不影响旧代码。

### Phase 2 — Team MVP（2 周）

**内容**：
- 实现 team 插件（OPTIONAL）：
  - 扁平团队（无层级，parent_id 为 NULL）
  - 成员管理（邀请/移除/角色/批量）
  - 团队基础设置
  - 团队池密钥（加密存储）、基础配额（不切分给子团队）
  - 基本可见性（私有/团队内可见）
  - 团队 pool key vs personal key 选择器（on_llm_pre_call）
  - LLM 错误 fallback（pool key 失效时回退个人 key）
  - 团队会议列表
- 前端：团队切换器、团队创建、成员管理、基础设置页

**验收标准**：
- 可创建团队、邀请成员、分配角色
- 团队会议创建后 metadata["team"] 正确写入
- 团队成员可使用池 key 发起调用，配额扣减到团队池
- pool key 失效时自动 fallback 到个人 key（若配置）
- 非团队成员无法访问团队会议
- team 插件被禁用时团队 API 返回 503，个人空间功能正常
- 前端可完成团队创建→邀请→创建会议→LLM 调用全流程

**回滚**：热禁用 team 插件，团队功能消失，个人空间正常；数据保留在 DB。

### Phase 3 — 规则引擎 + 配额系统 + 通知（2 周）

**内容**：
- 规则引擎：match_conditions 评估、priority 排序、effect 合并、乘法叠加
- 中点优先级算法 + 冲突检测
- Redis 规则缓存 + 精确失效
- 配额计算公式（base × multiplier）
- 自动重评估触发（成员变更/规则变更/邮箱变更）
- 通知系统（plugin/builtin/notification，OPTIONAL）
- 前端：规则编辑器（含实时预览）、冲突提示、配额可视化、通知中心
- 规则 CRUD API、preview API、reorder API

**验收标准**：
- 规则匹配逻辑正确（uids/groups/email_domains）
- 中点插入算法在 1000 次插入后仍有效，精度耗尽时触发批量重排
- 同优先级冲突产生通知
- 配额乘法叠加正确，UI 预览与实际扣减一致
- 缓存失效正确（规则变更后 10 秒内新规则生效）
- 自动重评估不阻塞主请求

**回滚**：禁用规则相关 API，团队回退到"所有成员统一配额"模式；规则数据保留。

### Phase 4 — 树形团队 + 高级可见性 + 匿名围观 + 组 + 自动打标（2 周）

**内容**：
- 树形团队（parent_id + LTREE path）
- 预算切分给子团队（allocated_to_children 校验、SELECT FOR UPDATE）
- 团队树页面
- 公开会议 + 匿名围观（独立 WS 端点、事件过滤、CAPTCHA、anon_cap、速率限制、审计）
- 用户组与组规则匹配
- 匿名围观入口页（前端）
- 自动打标（Phase 4 的 label 支持）
- 公开围观相关 API

**验收标准**：
- 可创建子团队，预算切分原子且不超预算
- 祖先/后代查询通过 LTREE 正确工作
- 匿名围观只读、事件过滤正确
- anon_cap 生效、超额拒绝连接
- CAPTCHA 验证流程可走通
- 组成员变更触发规则重评估

**回滚**：禁用匿名围观/组/树相关 API 开关，扁平团队模式继续工作；新表保留。

### Phase 5 — 高级功能（持续迭代）

- Vault/KMS 集成（密钥管理外移）
- 多副本部署支持（Redis 强依赖、leader election 用于定时任务单例）
- SSO/OIDC 集成
- 细粒度权限（自定义角色）
- 用量报表导出
- Webhook / 外部事件集成
- 密钥版本轮换
- 硬删除/归档工作流
- 审计日志外部导出（SIEM）

### 阶段总览

| 阶段 | 周期 | 累计 | 交付能力 |
|------|------|------|---------|
| Phase 0 | 1 周 | 1 周 | 插件框架 |
| Phase 1a | 1 周 | 2 周 | 认证 + Setup + Cookie 安全 |
| Phase 1b | 1 周 | 3 周 | 核心钩子点 + 计费/审计插件 |
| Phase 2 | 2 周 | 5 周 | Team MVP（扁平团队可用） |
| Phase 3 | 2 周 | 7 周 | 规则 + 配额 + 通知 |
| Phase 4 | 2 周 | 9 周 | 树团队 + 匿名 + 组 |
| Phase 5 | 持续 | - | 高级特性 |

### MVP 范围约束（< 10k 用户）

为控制 MVP（Phase 2-4 完成时）复杂度，做以下明确约束：
- **单实例部署**：不支持多副本水平扩展；Redis 可选，<100 用户时使用内存缓存
- **无 K8s/Leader Election**：定时任务（配额重置、余额刷新）在单实例运行；升级到多副本前引入 Redis + leader election
- **文件/环境变量密钥**：主密钥从环境变量读取，不接入 Vault/KMS（Phase 5 再做）
- **无 SSO**：仅用户名密码登录；Phase 5 引入 OIDC
- **无自定义角色**：固定 Owner/Admin/Member 三角色；Phase 5 开放自定义
- **单 provider 优先**：Phase 2-3 优先支持一个主 provider（如 OpenAI），其他 provider 按相同接口扩展

---

## 16. 已确认决策（最终）

以下决策在 v0.4 中最终确定，不再讨论：

1. **JSONB metadata 方案**：meetings 表仅加 metadata JSONB 一列，核心不解读业务字段；插件使用各自命名空间。
2. **插件三 Tier**：CORE/CROSSCUTTING/OPTIONAL，失败行为明确分层。
3. **Mixin 组合式接口**：替代单一 Protocol，插件按需实现。
4. **钩子二分法**：Interceptor（短路）/ Observer（全触发），LLM/Meeting 钩子具体分类见 §0.4。
5. **PluginRegistry 实例化 + DI**：在 create_app 中构造，通过依赖注入传递；非类变量单例。
6. **拓扑排序加载**：dependencies 声明确定性排序，循环依赖启动失败。
7. **健康检查 + 200ms 超时**：拦截器 unhealthy 跳过，observer best-effort；超时即跳过并警告。
8. **ContextVar + EventBus + 类型化参数**：插件通信三通道，禁止直接引用。
9. **热开关**：Redis 键 + Pub/Sub 实时生效，CORE 不可禁用。
10. **REAL 中点优先级**：无 UNIQUE，中点插入，冲突按创建顺序 + 告警。
11. **数据模型修正**：
    - teams.slug 复合唯一 (parent_id, slug)
    - teams.path LTREE
    - teams 拆分为 teams/team_settings/team_pool
    - quota_snapshots.team_id 使用哨兵 UUID 而非 NULL
    - period_month 为 DATE（月初）
    - token_usage 复合索引 + 按月分区
    - 软删除 deleted_at
    - user_api_keys 部分唯一索引 (uid, provider) WHERE is_default
    - CHECK 约束 allocated_to_children <= monthly_token_budget
    - 分配操作 SELECT ... FOR UPDATE
    - 加密格式 `v{ver}:{b64nonce}:{b64(ciphertext|tag)}`
    - plugin_states 表
    - meetings 仅加 metadata 列
12. **规则引擎**：
    - token_quota_multiplier 乘法叠加，UI 实时预览
    - 自动重评估在三类事件触发
    - 同优先级按创建顺序应用 + 管理员通知
13. **JWT Cookie**：HttpOnly + Secure + SameSite=Strict + CSRF double-submit，废弃 localStorage。
14. **/setup 防护**：24h 过期、5 次/10min/IP、一次性、DB 存储状态。
15. **API 标准化**：游标分页、标准错误格式、HTTP 状态码规范、PATCH batch 端点。
16. **Phase 0-5 分期**：总周期约 9 周到 Phase 4，每阶段独立可回滚。
17. **规则缓存**：Redis key `rules:{uid}:{team_id}` TTL 5min，精确失效。
18. **原子配额**：UPDATE ... RETURNING + 乐观重试 3 次。
19. **超支容忍**：$1.00 容差，缓存 5min，超支立即标记 exhausted。
20. **匿名围观**：独立 `/ws/anon/` 端点、事件白名单过滤、10 conn/IP/min、anon_cap、审计、CAPTCHA 可选。
21. **迁移方案**：向后兼容、分步执行、metadata/新表保留不影响回滚。
22. **监控 SLO**：钩子 p99 < 200ms、LLM 插件开销 p99 < 100ms、5 类核心告警。
23. **MVP 范围约束**：单实例、Redis 可选、无 K8s/无 Vault/无 SSO。
24. **personal namespace 哨兵 UUID**：`00000000-0000-0000-0000-000000000000`，代码中以常量引用，禁止 NULL。

---

## 17. 与 v0.3 的变更记录

v0.4 相对 v0.3 的所有架构变更（已全部通过多模型审计与用户确认）：

| # | 领域 | v0.3 方案 | v0.4 方案 | 决策理由 |
|---|------|----------|----------|---------|
| 1 | 核心 meetings 表 | 添加 5 个业务列（namespace_type、owner_team_id、visibility、access_list、token_source） | 单一 `metadata JSONB DEFAULT '{}'` 列，核心不解读 | 保持核心零感知，插件扩展不触发核心 DDL |
| 2 | 插件分层 | 单一 enabled/disabled | 三层 CORE/CROSSCUTTING/OPTIONAL，失败行为分级 | 避免一个可选插件故障拖垮全站 |
| 3 | 插件接口 | 胖 Protocol（所有钩子方法在一个类） | Mixin 组合（PluginBase + 多个 Mixin） | 插件按需实现，接口清晰 |
| 4 | 钩子类型 | 未明确分类，pre_call 既是观察又是拦截 | 明确 Interceptor（短路）/ Observer（全触发）两类，每个钩子明确归类 | 避免语义混乱，插件作者知道返回值/异常的影响 |
| 5 | Registry 生命周期 | 类变量单例 | create_app 中实例化 + DI | 支持测试隔离、多 app 场景 |
| 6 | 插件加载顺序 | 按注册顺序 | dependencies 声明 + 拓扑排序（确定性） | 依赖关系显式化，避免顺序 bug |
| 7 | 运行时保护 | 无 | 健康检查（30s）+ 200ms 钩子超时 | 防止异常插件阻塞全站 |
| 8 | 插件间通信 | 允许 get_plugin("name") | 仅 ContextVar + EventBus + 类型化参数，禁止直接引用 | 解耦插件，支持独立演进 |
| 9 | 规则优先级 | INT + UNIQUE 约束（插入需批量重排） | REAL 中点法、无 UNIQUE、冲突告警 | 避免重排风暴，支持无限次插入 |
| 10 | teams.slug | 全局唯一 | 复合唯一 (parent_id, slug) | 不同父团队下允许同名子团队 |
| 11 | teams 表 | 宽表（settings、pool 都在 teams） | 拆为 teams / team_settings / team_pool | 职责清晰，避免 NULL 密集 |
| 12 | quota_snapshots.team_id | NULL 表示个人 | 哨兵 UUID '00000000-...' | 修复 UNIQUE(team_id, uid, period) 对 NULL 不生效的问题 |
| 13 | period_month | VARCHAR / TIMESTAMPTZ | DATE（月初） | 语义清晰、查询高效、分区友好 |
| 14 | token_usage 索引 | 单列索引 | 复合索引 (uid, created_at DESC) 等 + 按月分区 | 查询性能、数据生命周期管理 |
| 15 | 删除 | 物理删除 | 软删除 deleted_at（users/teams/resource_rules） | 审计、可恢复、避免外键连锁物理删除 |
| 16 | user_api_keys 默认 key | 应用层约束 | 部分唯一索引 WHERE is_default = TRUE | 数据库保证一致性 |
| 17 | 预算分配 | 无 DB 约束 | CHECK + SELECT FOR UPDATE | 防超分、并发安全 |
| 18 | 加密格式 | 未明确 | 版本化 `v{ver}:b64nonce:b64(ct|tag)` | 支持密钥轮换、格式可演进 |
| 19 | plugin_states | 无 | 专用表（plugin_name, key, value, updated_at） | 插件状态持久化（setup token、健康状态、配置） |
| 20 | 规则叠加 | 加法/乘法未定 | 乘法叠加 + UI 实时预览 | 语义明确，管理员可直观看到效果 |
| 21 | 自动重评估 | 未设计 | 三类事件触发后台重评估 | 避免规则变更后用户状态不一致 |
| 22 | JWT 存储 | localStorage | httpOnly Secure SameSite=Strict Cookie + CSRF | 防御 XSS 窃取 + CSRF |
| 23 | /setup | 简单无防护 | 24h 过期 + 速率限制 + 一次性 + DB 存储 | 防止暴力破解、支持多副本 |
| 24 | API 分页/错误 | 多种分页方式混用 | 游标分页 + 标准错误格式 + HTTP 状态码规范 | 前端统一处理、可预测 |
| 25 | 批量操作 | 无 | PATCH batch 端点 | 减少管理操作的请求数 |
| 26 | 实施阶段 | 粗略分 3 阶段 | Phase 0-5（9 周），每阶段独立验收与回滚 | 可度量、可回滚、风险可控 |
| 27 | 热开关 | 需重启 | Redis 键 + Pub/Sub 实时生效 | 运维灵活、故障隔离快 |
| 28 | 规则缓存 | 未设计 | Redis 缓存 5min TTL + 精确失效 | 避免每请求重算规则 |
| 29 | 配额扣减 | 非原子（SELECT + UPDATE） | 单条 UPDATE ... RETURNING + 重试 | 并发安全 |
| 30 | 超支处理 | 实时余额查询（增加延迟） | 缓存 5min + $1 容差 + 事后立即标记 | 性能与安全平衡 |
| 31 | 匿名围观 | 无（或共用 WS 端点） | 独立 `/ws/anon/` 端点 + 事件过滤 + 多层防护 | 隔离读写权限、防滥用 |
| 32 | 迁移方案 | 未提供 | 详细 6 步迁移 + 每步回滚方案 | 生产升级可执行 |
| 33 | 监控 SLO | 无 | 指标定义 + SLO 目标 + 告警规则 | 可观测、可运维 |
| 34 | MVP 范围 | 未界定 | 明确单实例/Redis 可选/无 K8s/无 Vault | 避免过度设计 |

---

## ADR 引用

对应 `docs/adr/` 目录下的架构决策记录（待创建或已存在）：

- **ADR-001**：JSONB metadata 作为核心扩展机制（决策 §0.1）
- **ADR-002**：插件三 Tier 分层模型（决策 §0.2）
- **ADR-003**：Mixin 组合式插件接口（决策 §0.3）
- **ADR-004**：Interceptor/Observer 钩子二分法（决策 §0.4）
- **ADR-005**：PluginRegistry 实例化与依赖注入（决策 §0.5）
- **ADR-006**：钩子超时与健康检查机制（决策 §0.6）
- **ADR-007**：插件通信三通道与禁止直接引用（决策 §0.7）
- **ADR-008**：JWT Cookie + CSRF 方案（决策 §11.1, §11.5）
- **ADR-009**：REAL 中点优先级算法（决策 §4.4）
- **ADR-010**：哨兵 UUID 代表个人 Namespace（决策 §1.2, §3.3）
- **ADR-011**：AES-256-GCM 版本化加密格式（决策 §3.6, §11.2）
- **ADR-012**：原子配额 UPDATE RETURNING 与乐观重试（决策 §5.3）
- **ADR-013**：余额缓存与超支容忍（决策 §5.2）
- **ADR-014**：匿名围观独立端点与事件过滤（决策 §11.4, §7.3）
- **ADR-015**：Phase 0-5 分阶段交付策略（决策 §15）
- **ADR-016**：MVP 范围约束（单实例、可选 Redis、延后 Vault/K8s）（决策 §15 末）

---

**文档结束**。本设计文档所有决策已完成评审，进入实施阶段。实施过程中若发现需调整的决策，必须通过新的 ADR 记录变更，并更新本文件版本号至 v0.5+。
