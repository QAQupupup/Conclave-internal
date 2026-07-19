# Conclave 团队管理与多租户设计文档

> 版本: v0.3 (Draft)
> 状态: 所有核心决策已确认
> 核心原则: **插件化架构** - 多租户/团队管理作为可插拔模块实现，核心服务不感知

---

## 0. 架构原则（最高优先级）

### 0.1 核心与插件分离

Conclave 核心（`conclave-core`）**不感知**多租户、团队、配额、用户身份等概念。核心只负责：
- 会议生命周期管理（创建/运行/暂停/结束）
- Agent 编排与 LLM 调用
- 沙箱执行与工作区文件操作
- 事件总线与基础中间件

所有多租户、用户管理、配额管控、团队功能通过 **Plugin（插件）** 机制实现，以可插拔方式加载。

```
┌─────────────────────────────────────────────────────┐
│                   Conclave Core                      │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────┐  │
│  │ Meeting  │ │ LLM      │ │ Sandbox  │ │ Events │  │
│  │ Runner   │ │ Client   │ │ Runner   │ │ Bus    │  │
│  └──────────┘ └──────────┘ └──────────┘ └────────┘  │
│                                                      │
│  Plugin Hook System (pre_call / post_call / on_error │
│                      register_router / middleware)   │
└──────────────────────┬──────────────────────────────┘
                       │ hooks
        ┌──────────────┼──────────────┐
        ▼              ▼              ▼
   ┌─────────┐   ┌──────────┐   ┌──────────┐
   │  Auth   │   │ Billing/ │   │  Team/   │
   │ Plugin  │   │ Cost     │   │ Multi-   │
   │ (JWT)   │   │ Plugin   │   │ Tenant   │
   └─────────┘   └──────────┘   └──────────┘
                                   │
                                   └── 团队管理/命名空间/配额/规则
```

### 0.2 插件接口定义

所有插件实现统一的 `ConclavePlugin` Protocol：

```python
class ConclavePlugin(Protocol):
    """Conclave 插件协议"""

    # 元信息
    name: str                           # 插件唯一标识，如 "team"
    version: str                        # 语义化版本

    # 生命周期
    async def on_startup(self, app: FastAPI, ctx: "PluginContext") -> None: ...
    async def on_shutdown(self, app: FastAPI) -> None: ...

    # HTTP 层
    def register_routers(self, app: FastAPI) -> None:
        """注册插件自己的 API 路由"""
        ...

    def register_middlewares(self, app: FastAPI) -> None:
        """注册插件自己的中间件（如认证、租户上下文注入）"""
        ...

    # LLM 调用链钩子（核心！配额/多Key/降级都靠这些）
    async def on_llm_pre_call(self, call_ctx: "LLMCallContext") -> "LLMOverride | None":
        """LLM 调用前触发。可返回 LLMOverride 来替换 API Key/Model/BaseURL。
        返回 None 表示使用默认配置。"""
        ...

    async def on_llm_post_call(self, call_ctx: "LLMCallContext", result: "LLMResult") -> None:
        """LLM 调用成功后触发。用于计量/记账/用量统计。"""
        ...

    async def on_llm_error(self, call_ctx: "LLMCallContext", error: Exception) -> "LLMFallback | None":
        """LLM 调用失败时触发。可返回 LLMFallback 指定降级策略（切换BYOK/终止/重试）。
        返回 None 表示不干预，走默认错误处理。"""
        ...

    # 会议生命周期钩子
    async def on_meeting_creating(self, ctx: "MeetingCreateContext") -> None:
        """会议创建前触发。用于权限校验、配额预检、注入 namespace 信息。"""
        ...

    async def on_meeting_created(self, state: "MeetingState") -> None:
        """会议创建后触发。用于审计、初始化资源。"""
        ...

    async def on_meeting_accessing(self, ctx: "MeetingAccessContext") -> None:
        """访问会议时触发。用于可见性/权限校验，不通过则抛出 HTTPException。"""
        ...
```

### 0.3 插件注册与加载

```python
# app/plugins/__init__.py
class PluginRegistry:
    _plugins: dict[str, ConclavePlugin] = {}

    @classmethod
    def register(cls, plugin: ConclavePlugin) -> None: ...

    @classmethod
    def get(cls, name: str) -> ConclavePlugin | None: ...

    @classmethod
    def all(cls) -> list[ConclavePlugin]: ...

    @classmethod
    async def fire_llm_pre_call(cls, ctx) -> LLMOverride | None:
        """按注册顺序依次调用所有插件的 pre_call，第一个返回非 None 的生效"""
        for p in cls.all():
            result = await p.on_llm_pre_call(ctx)
            if result is not None:
                return result
        return None

    @classmethod
    async def fire_llm_error(cls, ctx, error) -> LLMFallback | None:
        """错误时依次调用插件，第一个返回 Fallback 的生效（用于配额耗尽降级BYOK）"""
        ...
```

插件通过环境变量启用，在 `create_app()` 中加载：

```python
# 启用方式：环境变量 CONCLAVE_PLUGINS=auth,billing,team
# 未列出的插件不加载，核心以最小模式运行（单人单租户）
PLUGINS = os.environ.get("CONCLAVE_PLUGINS", "auth,billing").split(",")
```

**核心在不加载 team 插件时完全不感知多租户，和现在的运行方式一致。** 这保证了向后兼容性和最小可运行性。

**插件启动失败策略**：
- `auth` 插件（认证/JWT）启动失败 → **阻断服务启动**。没人能登录，服务不可用，直接报错退出
- `team`/`billing` 插件启动失败（如迁移失败、外部依赖不可用）→ **打印错误日志但不阻断启动**。核心会议功能（个人空间+BYOK）仍可使用；团队相关 API 返回 503，前端显示"团队功能暂时不可用"的降级提示

### 0.4 插件间通信

插件之间通过以下方式协作，不直接 import：
- **ContextVar 上下文**：认证插件设置 `current_user`，team 插件读取它
- **事件总线**：插件订阅 `meeting.created`/`llm.called`/`quota.exceeded` 等事件
- **PluginContext 服务定位**：插件启动时可获取其他插件实例（通过 `ctx.get_plugin("auth")`）

---

## 1. 核心概念总览

### 1.1 双角色模型

Conclave 存在两套正交的"角色"系统：

| 维度 | 名称 | 作用 | 举例 |
|------|------|------|------|
| **层级角色** (Hierarchical Role) | 组织管理权限 | 决定谁能管谁、谁能改设置 | System Admin > Team Owner > Team Admin > Member > Guest |
| **资源规则** (Resource Rule / Tag) | 功能权限 + 配额分配 | 决定能用什么模型、有多少 token、能做什么操作 | "实习生"标签=低配额+只读；"VIP"标签=大配额+全模型 |

两套角色解耦：一个 Team Admin 可能因为"实习生"标签只有很低的 token 配额，一个普通 Member 可能因为"VIP客户"标签拥有更高配额。

### 1.2 Namespace 模型（真正的树形结构）

```
Root (Platform)
 ├── System Admins (全局管理员)
 │
 ├── Team (树形嵌套, LTREE 物化路径)
 │    ├── Team A (path=acme)
 │    │    ├── Sub-team A-1 (path=acme.eng)
 │    │    │    └── Sub-team A-1-1 (path=acme.eng.backend)
 │    │    └── Sub-team A-2 (path=acme.product)
 │    └── Team B (path=partner-x)
 │
 └── User Personal Namespace (path=user-<uid>)
      ├── User 1 的个人空间 (私有)
      └── User 2 的个人空间 (私有)
```

**规则**：
- 每个人拥有一个 **Personal Namespace**（类似 GitLab 个人空间），会议/文档默认私有
- 一个人可以创建/加入多个 Team，每个 Team 是树形命名空间
- Team 内的资源对 Team 成员可见（受可见性设置约束）
- 子 Team 默认继承父 Team 的成员、规则和配额池（可覆盖）
- **会议迁移**：个人空间的会议可以移入团队空间（需要目标团队的 create_meeting 权限）

### 1.3 资源来源双轨制

用户运行会议时，token 来源有两条轨道：

1. **Team Pool（团队配额池）**：Team 负责人充值/分配的公共额度，用户在 Team 内开会消耗团队池
2. **Personal BYOK（用户自带 Key）**：用户自己配置的 API Key，不消耗团队配额

**发起会议前必须明确选择使用哪个池**，UI 显示：
- 当前可用的 Team Pool 余额（从 `llm_providers.fetch_balance()` 实时查询）
- 当前 BYOK 状态
- 如果 Team Pool 余额不足，自动降级到 BYOK 并给出明确提示
- 如果既没有 Team 余额也没有 BYOK，无法发起会议，提示充值或配置 Key

### 1.4 公开会议

两种公开级别：
- **组织内公开（public_org）**：所有已登录用户可见可加入
- **互联网公开（public_internet）**：任何拿到链接的人（含未登录）可**只读围观**
  - 匿名围观只展示 Agent 对话流，不允许 intervene/control/upload
  - 匿名围观不消耗 LLM 配额（只读）
  - 单会议匿名围观人数上限可配置（默认 50），超出返回"房间已满"
  - 可选开启 CAPTCHA（默认关闭，Team Admin 可启用）

---

## 2. System Admin 初始化

参考 GitLab/MinIO/Outline 等开源项目的首次初始化模式：

### 2.1 初始化流程

```
首次启动（数据库无任何用户记录）
  │
  ├── 1. 生成一次性 Setup Token（32字节随机）
  ├── 2. 将 Token 打印到 stdout 和日志文件
  ├── 3. 写入到 ~/.conclave/setup_token 文件（权限 0600）
  ├── 4. 启动服务
  │
  ▼
用户访问 Web UI
  │
  ├── 自动检测到"未初始化"状态 → 跳转到 /setup 页面
  ├── 用户输入 Setup Token + 创建第一个管理员账号（邮箱+用户名+密码）
  ├── 后端验证 Token 有效（一次性使用，验证后立即失效）
  ├── 创建第一个 System Admin 用户
  ├── 删除 setup_token 文件
  └── /setup 端点永久关闭（后续访问返回 404）
```

### 2.2 环境变量覆盖（容器部署友好）

如果设置了环境变量 `CONCLAVE_SETUP_ADMIN_TOKEN=<token>`，则：
- 不自动生成随机 token
- 使用指定的 token 作为 Setup Token
- 适合 Docker Compose / K8s 部署时通过 secrets 注入

如果设置了 `CONCLAVE_SETUP_ADMIN_EMAIL` + `CONCLAVE_SETUP_ADMIN_PASSWORD`：
- 启动时自动创建该管理员账号（仅在无用户时）
- 不需要手动走 /setup 流程
- 适合自动化部署/CI 测试

### 2.3 打印格式示例

```
╔══════════════════════════════════════════════════════╗
║                                                      ║
║   Conclave 首次启动                                  ║
║                                                      ║
║   Setup Token: a8f3b2c1d4e5f6...                    ║
║                                                      ║
║   请打开 http://localhost:8000/setup                 ║
║   输入上述 Token 创建管理员账号                       ║
║                                                      ║
║   此 Token 仅本次启动有效，创建后失效                 ║
║                                                      ║
╚══════════════════════════════════════════════════════╝
```

---

## 3. 数据模型

### 3.1 核心表结构

所有 team 相关表使用 `team_` 前缀，与核心表物理隔离，方便插件卸载。

```sql
-- ========== 插件启用状态 ==========

CREATE TABLE plugin_states (
    plugin_name  VARCHAR(64) PRIMARY KEY,
    enabled      BOOLEAN NOT NULL DEFAULT TRUE,
    config       JSONB NOT NULL DEFAULT '{}',
    installed_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at   TIMESTAMPTZ DEFAULT NOW()
);

-- ========== 用户与身份 (auth 插件，team 插件依赖) ==========

CREATE TABLE users (
    uid            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username       VARCHAR(64) UNIQUE NOT NULL,
    email          VARCHAR(255) UNIQUE NOT NULL,
    display_name   VARCHAR(128) NOT NULL,
    password_hash  VARCHAR(255) NOT NULL,
    avatar_url     TEXT,
    is_system_admin BOOLEAN DEFAULT FALSE,
    is_active      BOOLEAN DEFAULT TRUE,
    created_at     TIMESTAMPTZ DEFAULT NOW(),
    last_login_at  TIMESTAMPTZ
);

-- 用户自带的 BYOK API Key（AES-256-GCM 加密存储）
CREATE TABLE user_api_keys (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    uid         UUID NOT NULL REFERENCES users(uid) ON DELETE CASCADE,
    provider    VARCHAR(32) NOT NULL DEFAULT 'openai',
    api_key_enc BYTEA NOT NULL,                 -- AES-256-GCM 加密后的 API Key
    key_version INT NOT NULL DEFAULT 1,         -- 密钥版本，支持轮转
    base_url    VARCHAR(512),
    is_default  BOOLEAN DEFAULT TRUE,
    label       VARCHAR(64),                    -- 用户给 Key 起的名字
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- 加密主密钥（DEK）从环境变量 CONCLAVE_ENCRYPTION_KEY 注入（32字节base64）
-- 若未设置则首次启动时自动生成并存储在 ~/.conclave/encryption.key（权限0600）

-- ========== 团队与组织架构（树形） ==========

CREATE TABLE teams (
    team_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug          VARCHAR(64) UNIQUE NOT NULL,
    display_name  VARCHAR(128) NOT NULL,
    description   TEXT,
    avatar_url    TEXT,
    parent_id     UUID REFERENCES teams(team_id) ON DELETE SET NULL,
    path          LTREE NOT NULL,               -- 物化路径: acme.eng.backend
    depth         INT NOT NULL DEFAULT 0,
    sort_order    INT DEFAULT 0,                -- 同级排序

    -- 团队配额（月度）
    -- 根团队的 monthly_token_budget 是团队池的总容量（由API Key账户余额决定）
    -- 子团队的 monthly_token_budget 是从父团队配额中切分的额度（由父团队Admin分配）
    monthly_token_budget BIGINT DEFAULT 0,      -- 本团队可用的月度 token 总额度
    allocated_to_children BIGINT DEFAULT 0,     -- 已分配给子团队的 token 额度总和（必须 <= monthly_token_budget）
    allowed_models TEXT[] DEFAULT '{}',         -- 团队可用模型白名单，空=不限制
    default_model VARCHAR(64),

    -- 团队 API Key（团队公共池使用的 Key，加密存储）
    -- 根团队配置 API Key；子团队默认使用父团队的 Key（也可覆盖为自己的 Key）
    pool_api_key_enc BYTEA,
    pool_base_url    VARCHAR(512),
    pool_provider    VARCHAR(32) DEFAULT 'openai',
    pool_key_inherited BOOLEAN DEFAULT TRUE,    -- TRUE=使用父团队的Key，FALSE=使用自己配置的Key
    pool_last_balance_check TIMESTAMPTZ,        -- 上次余额查询时间
    pool_cached_balance   NUMERIC(12,6),        -- 缓存的余额
    pool_cached_currency  VARCHAR(8),

    -- 加入策略
    join_policy   VARCHAR(16) NOT NULL DEFAULT 'invite_only',
    -- invite_only=仅邀请 / request=申请审批 / domain=邮箱域名自动加入
    allowed_email_domains TEXT[] DEFAULT '{}',

    -- 匿名围观设置
    allow_anonymous_view BOOLEAN DEFAULT FALSE,
    max_anonymous_viewers INT DEFAULT 50,
    require_captcha       BOOLEAN DEFAULT FALSE,

    created_by    UUID NOT NULL REFERENCES users(uid),
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    updated_at    TIMESTAMPTZ DEFAULT NOW()
);

-- 团队成员关系
CREATE TABLE team_members (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    team_id      UUID NOT NULL REFERENCES teams(team_id) ON DELETE CASCADE,
    uid          UUID NOT NULL REFERENCES users(uid) ON DELETE CASCADE,
    role         VARCHAR(16) NOT NULL DEFAULT 'member',
    -- owner / admin / member / guest
    joined_at    TIMESTAMPTZ DEFAULT NOW(),
    invited_by   UUID REFERENCES users(uid),
    is_auto_joined BOOLEAN DEFAULT FALSE,       -- 是否通过域名策略自动加入
    UNIQUE(team_id, uid)
);

-- 待处理的加入申请/邀请
CREATE TABLE team_invitations (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    team_id      UUID NOT NULL REFERENCES teams(team_id) ON DELETE CASCADE,
    email        VARCHAR(255),                  -- 邀请的邮箱（预注册用户）
    uid          UUID REFERENCES users(uid),    -- 已注册用户的申请
    inviter_uid  UUID REFERENCES users(uid),
    role         VARCHAR(16) DEFAULT 'member',
    status       VARCHAR(16) DEFAULT 'pending', -- pending/accepted/rejected/cancelled
    token        VARCHAR(64) UNIQUE NOT NULL,   -- 邀请链接 token
    expires_at   TIMESTAMPTZ,
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    handled_at   TIMESTAMPTZ
);

-- ========== 资源规则 (Resource Rule) ==========

CREATE TABLE resource_rules (
    rule_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    team_id       UUID NOT NULL REFERENCES teams(team_id) ON DELETE CASCADE,
    name          VARCHAR(64) NOT NULL,
    description   TEXT,
    priority      INT NOT NULL DEFAULT 100,    -- 数字越小优先级越高；同优先级抛异常等待处理
    scope         VARCHAR(16) NOT NULL DEFAULT 'team',
    -- team=仅当前团队 / subtree=作用于整棵子树 / personal=个人规则

    -- 匹配条件（自动打标）
    match_email_domains  TEXT[] DEFAULT '{}',
    match_email_pattern  TEXT,                  -- 正则
    match_metadata       JSONB DEFAULT '{}',    -- {"department": "engineering"}

    -- 配额规则
    token_quota_override  BIGINT,               -- 绝对值（tokens/月），NULL=不覆盖
    token_quota_multiplier REAL,               -- 倍率（如0.8=打8折），NULL=不覆盖
    max_concurrent_meetings INT,
    max_meeting_duration_minutes INT,

    -- 功能权限（NULL=不覆盖，继承低优先级规则）
    can_create_meeting     BOOLEAN,
    can_upload_documents   BOOLEAN,
    can_deploy_services    BOOLEAN,
    can_invite_members     BOOLEAN,
    can_use_sandbox        BOOLEAN,
    can_move_to_team       BOOLEAN,             -- 能否将个人会议移入团队

    -- 模型白名单覆盖
    allowed_models_override TEXT[],

    is_active    BOOLEAN DEFAULT TRUE,
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    updated_at   TIMESTAMPTZ DEFAULT NOW(),

    -- 同团队内 priority 唯一约束（防止同优先级冲突）
    UNIQUE(team_id, priority)
);

-- 规则绑定：贴到用户/组
CREATE TABLE rule_bindings (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    rule_id      UUID NOT NULL REFERENCES resource_rules(rule_id) ON DELETE CASCADE,
    target_type  VARCHAR(16) NOT NULL,         -- user / group
    target_id    UUID NOT NULL,
    is_auto      BOOLEAN DEFAULT FALSE,        -- 是否自动匹配绑定
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(rule_id, target_type, target_id)
);

-- 用户组
CREATE TABLE user_groups (
    group_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    team_id      UUID NOT NULL REFERENCES teams(team_id) ON DELETE CASCADE,
    name         VARCHAR(64) NOT NULL,
    description  TEXT,
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(team_id, name)
);

CREATE TABLE group_members (
    group_id UUID NOT NULL REFERENCES user_groups(group_id) ON DELETE CASCADE,
    uid      UUID NOT NULL REFERENCES users(uid) ON DELETE CASCADE,
    PRIMARY KEY(group_id, uid)
);

-- ========== 配额计量 ==========

CREATE TABLE token_usage (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    uid           UUID NOT NULL REFERENCES users(uid),
    team_id       UUID REFERENCES teams(team_id),    -- NULL=个人空间/BYOK
    meeting_id    VARCHAR(36),
    source        VARCHAR(16) NOT NULL,             -- team_pool / byok
    provider      VARCHAR(32) NOT NULL,
    model         VARCHAR(64) NOT NULL,
    input_tokens  INT NOT NULL DEFAULT 0,
    output_tokens INT NOT NULL DEFAULT 0,
    cost_usd      NUMERIC(12,6) DEFAULT 0,
    created_at    TIMESTAMPTZ DEFAULT NOW()
);

-- 月度配额快照（每月1号自然月重置）
CREATE TABLE quota_snapshots (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    uid            UUID NOT NULL REFERENCES users(uid),
    team_id        UUID REFERENCES teams(team_id),   -- NULL=个人配额
    period_month   CHAR(7) NOT NULL,                 -- '2025-07'
    total_quota    BIGINT NOT NULL,                  -- 计算后总配额
    used_tokens    BIGINT NOT NULL DEFAULT 0,
    last_reset_at  TIMESTAMPTZ NOT NULL,
    UNIQUE(uid, team_id, period_month)
);

-- ========== 会议可见性扩展 (核心 meetings 表加字段) ==========

-- 以下字段通过 migration 添加到核心 meetings 表：
-- namespace_type  VARCHAR(16) DEFAULT 'personal'  (personal/team/public_org/public_internet)
-- owner_team_id   UUID REFERENCES teams(team_id)
-- visibility      VARCHAR(16) DEFAULT 'private'   (private/team/subtree/org/public)
-- access_list     JSONB DEFAULT '[]'
-- token_source    VARCHAR(16) DEFAULT 'byok'      (team_pool/byok)
-- token_source_detail JSONB                       -- {provider, model, source_team_id?}

-- ========== 审计日志 ==========

CREATE TABLE audit_logs (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    timestamp   TIMESTAMPTZ DEFAULT NOW(),
    actor_uid   UUID REFERENCES users(uid),
    action      VARCHAR(64) NOT NULL,
    target_type VARCHAR(32),
    target_id   UUID,
    metadata    JSONB,
    ip_address  INET
);

-- ========== 系统通知（配额告警等） ==========

CREATE TABLE notifications (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    uid         UUID NOT NULL REFERENCES users(uid),
    type        VARCHAR(32) NOT NULL,
    -- quota_warning / quota_exceeded / team_invite / meeting_failed / system
    title       VARCHAR(255) NOT NULL,
    body        TEXT,
    data        JSONB DEFAULT '{}',
    is_read     BOOLEAN DEFAULT FALSE,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
```

### 3.2 LTREE 索引

```sql
-- 启用 ltree 扩展（PostgreSQL）
CREATE EXTENSION IF NOT EXISTS ltree;

-- 团队路径索引
CREATE INDEX idx_teams_path ON teams USING GIST (path);
CREATE INDEX idx_teams_parent ON teams (parent_id);
CREATE INDEX idx_teams_depth ON teams (depth);

-- 查询某节点所有子树: SELECT * FROM teams WHERE path <@ 'acme.eng';
-- 查询某节点所有祖先: SELECT * FROM teams WHERE path @> 'acme.eng.backend';
```

---

## 4. 规则计算引擎

### 4.1 有效规则计算

用户在指定 Team 上下文中的最终权限和配额由规则引擎计算（team 插件实现）：

```python
def compute_effective_rules(user_id: UUID, team_id: UUID) -> EffectiveRules:
    """
    规则来源（从低优先级到高优先级）：
    1. 团队默认设置（teams 表上的默认值）
    2. 沿 Team 树从根到当前节点的所有 subtree 作用域规则（按深度升序）
    3. 当前 Team 的 team 作用域规则（按 priority 升序）
    4. 绑定到该用户所在 Group 的规则
    5. 绑定到该用户个人的规则（最高优先级）

    合并策略：
    - 布尔/枚举/列表字段：高优先级非 NULL 值覆盖低优先级
    - token_quota_multiplier：乘法叠加（0.8 * 1.2 = 0.96）
    - token_quota_override：最高优先级的绝对值直接生效，不再叠加
    - 同 priority 的规则冲突 → 抛出 RuleConflictError，告警管理员处理
    """
```

### 4.2 配额计算公式

**父池切分模型**：
- 根团队的 `monthly_token_budget` 由 API Key 账户余额决定（充值在提供商平台完成，Conclave 不处理支付）
- 父团队可以将自己的 budget 切分一部分给子团队（通过 `allocated_to_children` 跟踪）
- 父团队直接可用额度 = `monthly_token_budget - allocated_to_children`
- 子团队可以继续往下切分给孙团队
- 子团队默认继承父团队的 API Key（`pool_key_inherited=TRUE`），也可以配置自己的 Key

```
# 1. 确定本团队可用配额
available_quota = team.monthly_token_budget - team.allocated_to_children

# 2. 应用倍率规则
multiplier = product(所有命中规则的 token_quota_multiplier)
quota_after_multiplier = available_quota * multiplier

# 3. 应用绝对值覆盖（如果有）
override = 最高优先级规则的 token_quota_override
final_quota = override if override is not None else quota_after_multiplier

# 4. 边界处理
if final_quota <= 0:
    → 该用户无法使用 Team Pool，必须使用 BYOK
```

**配额分配约束**：
- 父团队分配给子团队的总额度不能超过父团队自身可用额度（`allocated_to_children <= monthly_token_budget`）
- 子团队的 `monthly_token_budget` 由父团队 Admin 设置，减少时需要检查子团队已分配+已使用不超过新额度
- 配额分配是"软"的：如果父团队的 API Key 实际余额不足，即使有预算也会触发降级

### 4.3 自动打标

用户加入团队或首次登录时，自动评估 `resource_rules` 的匹配条件：
- `match_email_domains`: 邮箱域名匹配（如 `@company.com` 自动打"正式员工"标签）
- `match_email_pattern`: 邮箱正则（如 `*intern*@` 打"实习生"标签）
- `match_metadata`: 扩展字段匹配

自动绑定的 `is_auto=True`，可被管理员手动解绑，也可被更高优先级手动规则覆盖。

---

## 5. LLM 错误检测与配额耗尽处理

### 5.1 现有问题（已调研）

当前 `llm.py` 对 401/402/429/insufficient_quota 无差异化处理，全部走统一重试+降级 StubLLM，用户无感知。team 插件通过 `on_llm_error` 钩子修复此问题。

### 5.2 错误码分类与处理

team 插件在 `on_llm_error` 中结构化解析错误响应：

```python
# OpenAI 兼容 API 的错误格式:
# { "error": { "code": "insufficient_quota", "message": "...", "type": "..." } }

LLM_ERROR_HANDLERS = {
    # === 认证错误 → 立即切换 BYOK，不重试 ===
    "invalid_api_key":       {"action": "fallback_byok", "retry": False, "notify_user": True},
    "invalid_organization":  {"action": "fallback_byok", "retry": False, "notify_user": True},

    # === 配额/余额不足 → 检查余额，切换BYOK，发通知 ===
    "insufficient_quota":    {"action": "quota_exceeded", "retry": False, "notify_user": True},
    "billing_not_active":    {"action": "quota_exceeded", "retry": False, "notify_user": True},
    "account_deactivated":   {"action": "quota_exceeded", "retry": False, "notify_user": True},

    # === 限流 → 指数退避重试，重试3次仍失败则降级BYOK ===
    "rate_limit_exceeded":   {"action": "retry_with_backoff", "max_retries": 3, "notify": False},
    "concurrent_requests":   {"action": "retry_with_backoff", "max_retries": 3, "notify": False},

    # === 模型不存在/不允许 → 切换到允许列表中的默认模型 ===
    "model_not_found":       {"action": "switch_default_model", "retry": True},
    "model_not_supported":   {"action": "switch_default_model", "retry": True},

    # === 服务器错误 → 默认重试（核心已有此逻辑，插件不干预）===
    "server_error":          None,  # None = 不干预，走核心默认处理
    "overloaded":            None,
}
```

### 5.3 余额实时查询

在 `on_llm_pre_call` 中，team 插件：

1. 若使用 Team Pool：
   - 距离上次余额查询 > 5 分钟 → 调用 `fetch_balance()` 更新缓存
   - 缓存余额 < 阈值（如 $1.00 或 100K tokens）→ 发送告警通知
   - 缓存余额 <= 0 → 直接返回 `LLMFallback(action="use_byok")`，不发起 LLM 调用
2. 若使用 BYOK：
   - 用户有 BYOK → 用用户的 Key
   - 用户无 BYOK → 终止调用，返回明确错误

### 5.4 配额耗尽降级流程

```
LLM 调用触发
  │
  ├─ pre_call 钩子:
  │    检查配额快照 used_tokens >= total_quota?
  │    ├─ 是 → 检查 BYOK 是否可用
  │    │    ├─ BYOK 可用 → 返回 LLMOverride(使用BYOK) + 发通知"已自动切换到你的API Key"
  │    │    └─ BYOK 不可用 → 抛出 QuotaExceededException → 会议暂停，提示充值/配置Key
  │    └─ 否 → 通过，继续
  │
  ├─ LLM 实际调用
  │    │
  │    ├─ 成功 → post_call 钩子:
  │    │    1. 记录 token_usage
  │    │    2. 更新 quota_snapshots.used_tokens (原子操作)
  │    │    3. 若使用后达到 80%/90%/100% 阈值 → 发送告警通知
  │    │
  │    └─ 失败 → on_llm_error 钩子:
  │         解析 error.code → 查 LLM_ERROR_HANDLERS
  │         ├─ insufficient_quota → 标记 team pool 为耗尽状态 → 降级 BYOK
  │         ├─ invalid_api_key → 通知管理员 Key 无效 → 降级 BYOK
  │         ├─ rate_limit → 指数退避重试
  │         └─ 其他 → 不干预，走核心默认逻辑
```

---

## 6. 权限矩阵

### 6.1 层级角色权限

| 操作 | System Admin | Team Owner | Team Admin | Member | Guest | 匿名 |
|------|:---:|:---:|:---:|:---:|:---:|:---:|
| 创建根团队 | Y | - | - | - | - | - |
| 管理所有团队 | Y | - | - | - | - | - |
| 转让团队所有权 | - | Y | - | - | - | - |
| 修改团队设置/充值 | - | Y | Y | - | - | - |
| 创建子团队 | - | Y | Y | - | - | - |
| 管理成员/邀请 | - | Y | Y | - | - | - |
| 创建/编辑/删除规则 | - | Y | Y | - | - | - |
| 调整成员配额 | - | Y | Y | - | - | - |
| 创建会议(团队空间) | - | Y | Y | Y* | - | - |
| 查看团队会议列表 | - | Y | Y | Y | Y** | - |
| 参与团队会议 | - | Y | Y | Y | Y** | - |
| 创建会议(个人空间) | Y | Y | Y | Y | - | - |
| 将个人会议移入团队 | - | Y | Y | Y* | - | - |
| 围观组织内公开会议 | Y | Y | Y | Y | Y | - |
| 围观互联网公开会议 | Y | Y | Y | Y | Y | Y(只读) |

*受规则引擎限制（`can_create_meeting=false` 则无法创建）
**visibility=private 的会议需在参会者/access_list 中

### 6.2 会议可见性判定

```python
def can_access_meeting(user, meeting) -> AccessLevel:
    # 1. 互联网公开会议：匿名只读
    if meeting.visibility == 'public' and meeting.namespace_type == 'public_internet':
        if not user or not user.is_authenticated:
            return AccessLevel.VIEW

    if not user or not user.is_authenticated:
        return AccessLevel.NONE

    # 2. 创建者/owner
    if meeting.owner_uid == user.uid:
        return AccessLevel.OWNER

    # 3. 参会者
    if user.uid in meeting.participants:
        return AccessLevel.PARTICIPATE

    # 4. 个人空间会议
    if meeting.namespace_type == 'personal':
        return AccessLevel.NONE  # 只有owner可见(前面已处理)

    # 5. 团队空间会议
    if meeting.namespace_type in ('team', 'public_org', 'public_internet'):
        team = get_team(meeting.owner_team_id)

        if meeting.visibility == 'private':
            return check_access_list(user, meeting.access_list)

        if meeting.visibility == 'team':
            if is_member_of(user.uid, team.team_id):
                return AccessLevel.VIEW

        if meeting.visibility == 'subtree':
            if is_member_of_descendant(user.uid, team.team_id):
                return AccessLevel.VIEW

        if meeting.visibility in ('org', 'public'):
            if meeting.visibility == 'org' or user.is_authenticated:
                return AccessLevel.VIEW

        return check_access_list(user, meeting.access_list)

    return AccessLevel.NONE
```

---

## 7. API 设计

### 7.1 初始化

```
GET  /api/setup/status                     返回 {needs_setup: bool}
POST /api/setup                            完成初始化（一次性）
  Body: {setup_token, email, username, password, display_name}
```

### 7.2 团队管理

```
POST   /api/teams                          创建团队（根团队或子团队）
GET    /api/teams                          列出我加入的所有团队（树形结构）
GET    /api/teams/:team_id                 团队详情（含配额、成员数、子团队、缓存余额）
PATCH  /api/teams/:team_id                 修改团队设置
DELETE /api/teams/:team_id                 删除团队（Owner，二次确认）
POST   /api/teams/:team_id/transfer        转让所有权
POST   /api/teams/:team_id/pool-key        设置团队公共池 API Key（根团队配置，子团队可覆盖）
POST   /api/teams/:team_id/pool/inherit    子团队切换为继承父团队Key
POST   /api/teams/:team_id/pool/check-balance  主动查询公共池余额
POST   /api/teams/:team_id/allocate-quota  分配配额给子团队 {child_team_id, amount}
GET    /api/teams/:team_id/tree            团队子树（含各节点配额分配情况）
GET    /api/teams/:team_id/ancestors       从根到当前的路径
```

### 7.3 成员与邀请

```
GET    /api/teams/:team_id/members         列出成员（含角色、有效配额、用量）
POST   /api/teams/:team_id/members         邀请成员（批量邮箱）
PATCH  /api/teams/:team_id/members/:uid    修改成员角色
DELETE /api/teams/:team_id/members/:uid    移除成员
POST   /api/teams/:team_id/invitations     创建邀请链接
POST   /api/teams/join                     通过邀请token加入
POST   /api/teams/:team_id/join-requests   申请加入
POST   /api/teams/join-requests/:id/approve
POST   /api/teams/join-requests/:id/reject
GET    /api/invitations                    我的待处理邀请/申请
```

### 7.4 规则与标签

```
POST   /api/teams/:team_id/rules                    创建规则
GET    /api/teams/:team_id/rules                    列出规则（按priority排序）
PATCH  /api/teams/:team_id/rules/:rule_id           修改规则
DELETE /api/teams/:team_id/rules/:rule_id           删除规则
POST   /api/teams/:team_id/rules/reorder            批量调整优先级
POST   /api/teams/:team_id/rules/:rule_id/bind      绑定到用户/组
DELETE /api/teams/:team_id/rules/:rule_id/bind/:id  解绑
GET    /api/teams/:team_id/members/:uid/effective-rules  查看该用户最终规则（含来源解释）
```

### 7.5 用户组

```
CRUD /api/teams/:team_id/groups + /groups/:gid/members
```

### 7.6 配额与计量

```
GET    /api/teams/:team_id/quota              团队配额总览
GET    /api/teams/:team_id/quota/usage        用量明细（按日/按成员/按模型）
GET    /api/teams/:team_id/members/:uid/quota 成员配额详情
POST   /api/teams/:team_id/members/:uid/quota/override  手动覆盖配额
GET    /api/me/quota                          个人跨团队配额概览
GET    /api/me/usage                          个人用量明细
```

### 7.7 BYOK

```
GET    /api/me/api-keys
POST   /api/me/api-keys                       {provider, api_key, base_url?, label?}
PATCH  /api/me/api-keys/:id                   设为默认
DELETE /api/me/api-keys/:id
POST   /api/me/api-keys/:id/test              测试 Key 是否可用、查询余额
```

### 7.8 Namespace

```
GET    /api/namespaces                        我可用的所有 namespace（个人+所有团队）
GET    /api/namespaces/:ns/meetings           指定 namespace 下可见的会议
POST   /api/meetings/:id/move-to-team         将个人会议移入团队
```

### 7.9 会议创建（扩展）

```
POST /api/meetings
  Body: {
    topic: "...",
    namespace: "personal" | "team",
    team_id: "uuid",            // namespace=team 时必填
    visibility: "private" | "team" | "subtree" | "org" | "public",
    token_source: "auto" | "team_pool" | "byok",  // auto=按规则自动选择
    ...
  }

GET  /api/meetings/token-pools?team_id=xxx     // 发起会议前获取可用token池
  返回: {
    pools: [
      {
        source: "team_pool",
        team_id: "...",
        team_name: "ACME/工程部",
        balance: {amount: 2.45, currency: "CNY"},  // 从 fetch_balance() 实时查询
        quota: {total: 3000000, used: 600000, remaining: 2400000},
        allowed_models: ["gpt-4o", "deepseek-chat"],
        default_model: "gpt-4o",
        available: true,
        recommended: true       // 余额充足时推荐
      },
      {
        source: "byok",
        provider: "openai",
        label: "我的OpenAI Key",
        balance: null,          // BYOK不查询余额
        allowed_models: null,   // BYOK不限制模型（受模型是否存在约束）
        default_model: null,
        available: true,
        recommended: false
      }
    ],
    auto_selected: "team_pool",  // auto模式下的默认选择
    warnings: [                  // 警告信息
      {type: "low_balance", message: "团队配额剩余不足20%"}
    ]
  }
```

### 7.10 通知

```
GET    /api/notifications                我的通知（含配额告警）
POST   /api/notifications/:id/read       标记已读
POST   /api/notifications/read-all
GET    /api/notifications/unread-count   未读数
```

---

## 8. 前端页面结构

### 8.1 导航变更

**Namespace 切换器**（导航栏顶部，类似 GitLab 左上角）：

```
┌─────────────────────────┐
│ 🔄 ACME/工程部/后端 ▾    │  ← 始终显示当前 namespace
│ ─────────────────────── │
│ ⭐ 你的空间 (个人)       │
│ ─────────────────────── │
│ 📁 ACME                  │
│   ├─ 工程部              │
│   │  └─ ✅ 后端          │  ← 当前选中
│   └─ 产品部              │
│ 📁 Partner X             │
│ ─────────────────────── │
│ ➕ 创建新团队            │
└─────────────────────────┘
```

### 8.2 页面清单

**全局：**
1. `/setup` - 首次初始化页（仅无用户时可访问）
2. 导航栏 Namespace 切换器组件

**个人空间：**
3. `/` - 个人空间首页（我的会议、最近活动、BYOK 状态）
4. `/settings/api-keys` - BYOK 管理
5. `/settings/usage` - 个人用量总览
6. `/invitations` - 我的邀请/申请

**团队空间：**
7. `/team/:slug` - 团队首页（概览、活跃会议、用量仪表盘、余额状态）
8. `/team/:slug/settings` - 团队通用设置、公共池 API Key 配置（继承/覆盖）、子团队配额分配、加入策略、匿名围观设置
9. `/team/:slug/members` - 成员管理（列表、角色分配、邀请、配额覆盖）
10. `/team/:slug/members/:username` - 成员详情（规则来源解释、用量趋势、配额历史）
11. `/team/:slug/rules` - 规则管理（列表、可视化编辑器、优先级拖拽排序、绑定管理）
12. `/team/:slug/groups` - 用户组管理
13. `/team/:slug/quota` - 配额仪表盘（总池余额、成员用量排行、消耗趋势、充值入口）
14. `/team/:slug/invitations` - 邀请/审批管理

**会议创建弹窗扩展：**
15. Token 池选择器组件

**通知：**
16. 顶部通知铃铛（未读数、下拉列表）

### 8.3 Token 池选择器交互（核心组件）

```
┌─ 发起新会议 ──────────────────────────────────────┐
│  主题: [___________________________________]      │
│                                                    │
│  归属空间:                                         │
│  ○ 我的个人空间                                    │
│  ● ACME/工程部/后端 (团队空间)                     │
│                                                    │
│  可见性: [团队内可见 ▾]                            │
│   - 仅参会者                                       │
│   - 团队内可见                                     │
│   - 子树内可见                                     │
│   - 全组织可见                                     │
│   - 互联网公开 (只读围观)                          │
│                                                    │
│  ── Token 来源 ──────────────────────────────────  │
│  ┌──────────────────────────────────────────────┐ │
│  │ ✅ 团队配额 (ACME/工程部/后端)               │ │
│  │    💰 余额 ¥168.50 / ¥500 (34%)             │ │
│  │    📊 月度配额 2.4M / 3M tokens (80%)        │ │
│  │    🤖 可用模型: gpt-4o, deepseek-chat        │ │
│  │    ⚠️ 配额已用80%，注意用量                  │ │
│  ├──────────────────────────────────────────────┤ │
│  │ ⚪ 我的 API Key (OpenAI · 我的Key)           │ │
│  │    未查询余额 (BYOK不检查余额)                │ │
│  │    使用你自己的API Key，不消耗团队配额        │ │
│  └──────────────────────────────────────────────┘ │
│  ℹ️ 团队配额耗尽时将自动切换到你的API Key          │
│                                                    │
│  模型: [gpt-4o ▾]  (受配额规则限制)               │
│                                                    │
│           [取消]  [发起会议]                      │
└────────────────────────────────────────────────────┘
```

### 8.4 规则编辑器交互（表单式）

MVP 阶段使用**标准表单控件**（输入框、开关、下拉、多选、滑块），不做可视化连线/流程图编排。规则优先级排序在规则列表页通过**拖拽列表项**实现。

```
┌─ 规则编辑器 ──────────────────────────────────────┐
│  规则名称: [实习生规则                    ]        │
│  优先级:  [50     ] (越小越高，同优先级报错)       │
│  作用域:  [当前团队 ▾]                             │
│           范围: ○当前团队 ●子树(含所有子团队)      │
│                                                    │
│  ── 自动匹配条件 ────────────────────────────────  │
│  满足以下条件的用户自动应用此规则:                  │
│  ├─ 邮箱域名: [company.com, intern.company.com] [x]│
│  ├─ 邮箱正则: [*.intern@.*              ] [x]      │
│  └─ 元数据:   [department] [=] [engineering] [x] [+]│
│                                                    │
│  ── 配额设置 ────────────────────────────────────  │
│  ☑ Token 配额                                      │
│    ○ 绝对值: [0] tokens/月 (0=禁止使用团队配额)   │
│    ● 倍率:   [0.3] × 团队基础配额                  │
│  ☐ 并发会议上限                                    │
│  ☑ 单会议时长上限: [30] 分钟                       │
│                                                    │
│  ── 功能权限 ────────────────────────────────────  │
│  ☑ 创建会议                                        │
│  ☐ 上传文档                                        │
│  ☐ 部署服务                                        │
│  ☐ 邀请成员                                        │
│  ☑ 使用沙箱                                        │
│  ☐ 将个人会议移入团队                              │
│                                                    │
│  ── 模型白名单 ──────────────────────────────────  │
│  ☑ gpt-3.5-turbo                                  │
│  ☐ gpt-4o                                         │
│  ☐ deepseek-chat                                  │
│                                                    │
│  ── 已绑定 ──────────────────────────────────────  │
│  ├─ 👤 张三 (手动)                           [解绑]│
│  ├─ 👥 实习生组 (自动匹配)                   [解绑]│
│  └─ [+ 绑定到用户/组]                              │
│                                                    │
│           [取消]  [保存规则]                       │
└────────────────────────────────────────────────────┘
```

规则列表页支持**拖拽排序优先级**，同优先级的规则显示红色警告提示冲突。

---

## 9. 关键流程

### 9.1 首次初始化

```
服务启动
  ↓
检查 users 表是否为空
  ├─ 否 → 正常启动
  └─ 是 → 执行初始化流程:
      1. 生成 Setup Token（或从环境变量读取）
      2. 打印到 stdout + 日志
      3. 写入 ~/.conclave/setup_token
      4. /setup/status 返回 {needs_setup: true}
      5. 前端检测到 needs_setup → 跳转 /setup
      6. 用户输入 token + 创建管理员
      7. 验证 token → 创建 System Admin
      8. 删除 setup_token 文件
      9. /setup 端点返回 404
```

### 9.2 用户加入团队

```
场景A: 管理员邀请
  Admin输入邮箱 → 生成邀请链接+token → 邮件发送
  → 用户点击链接 → 登录/注册 → 加入团队
  → 触发自动打标引擎 → 匹配规则自动绑定

场景B: 用户申请
  用户浏览团队/点击链接 → "申请加入"
  → Admin收到通知 → 审批通过/拒绝
  → 通过后触发自动打标

场景C: 域名自动加入
  Team设置 join_policy=domain, allowed_email_domains=['@company.com']
  → 用户用 @company.com 邮箱注册 → 自动加入该 Team
  → 触发自动打标
```

### 9.3 发起会议（Token选择+降级）

```
用户点击"发起会议"
  ↓
前端调用 GET /api/meetings/token-pools?team_id=xxx
  ↓
team 插件:
  1. 计算用户有效规则 → 得到配额、允许模型
  2. 查询 Team Pool 余额（缓存或实时 fetch_balance()）
  3. 查询用户 BYOK 状态
  4. 返回可用 pools 列表 + 推荐选择
  ↓
用户选择 token_source（或auto）
  ↓
POST /api/meetings 创建会议
  ↓
team 插件 on_meeting_creating:
  1. 校验 namespace 权限
  2. 校验 visibility 权限
  3. 预扣配额（仅标记，不实际扣减）
  4. 将 token_source 写入 MeetingState
  ↓
会议运行中，每次 LLM 调用:
  on_llm_pre_call:
    根据 token_source 返回 LLMOverride(team_pool_key 或 byok_key)
    检查配额快照是否耗尽 → 耗尽则降级
  ↓
  LLM 调用成功 → on_llm_post_call:
    记录 token_usage
    原子更新 quota_snapshots.used_tokens
    检查阈值 → 80/90/100% 发通知
  ↓
  LLM 调用失败 → on_llm_error:
    解析 error.code
    ├─ insufficient_quota → 标记 pool 耗尽 → 降级 BYOK（若可用）→ 通知用户
    ├─ invalid_api_key → 通知Admin Key失效 → 降级 BYOK
    ├─ rate_limit → 指数退避重试
    └─ 其他 → 不干预
  ↓
Team Pool中途耗尽且无BYOK:
  → 暂停会议
  → 前端弹出提示"团队配额已用完，请配置你的API Key或联系管理员充值"
  → 用户配置BYOK/管理员充值后可恢复
```

### 9.4 会议迁移（个人→团队）

```
用户在个人空间打开会议详情
  ↓
点击"移动到团队"
  ↓
选择目标团队（下拉列表显示用户有create_meeting权限的团队）
  ↓
team 插件校验:
  1. 用户在目标团队有 can_move_to_team 和 can_create_meeting 权限
  2. 目标团队的规则允许此操作
  ↓
更新 meeting.namespace_type='team', owner_team_id=xxx
  ↓
重新计算会议可见性
  ↓
团队成员可见该会议
```

---

## 10. 核心代码改造点

### 10.1 核心改造（最小化，只加钩子，不加业务逻辑）

| 文件 | 改造 | 性质 |
|------|------|------|
| `app/plugins/__init__.py` | 新增 PluginRegistry、ConclavePlugin Protocol、钩子触发机制 | 新增 |
| `app/plugin_context.py` | 新增 PluginContext、LLMCallContext、LLMOverride、LLMFallback 等类型 | 新增 |
| `app/main.py` | `create_app()` 中增加插件加载逻辑（按 CONCLAVE_PLUGINS 环境变量），在各阶段调用插件钩子 | 改造 |
| `app/agents/llm.py` | 在 `complete()` 和 `_call_api()` 中增加 pre_call/post_call/on_error 钩子触发点 | 改造（仅插入hook调用，不改业务逻辑） |
| `app/orchestrator/runner.py` | 在会议创建/访问点增加 on_meeting_creating/on_meeting_accessing 钩子 | 改造 |
| `app/db/models/meeting.py` | meetings 表增加 namespace_type, owner_team_id, visibility, access_list, token_source 字段 | 迁移 |
| `app/context.py` | 新增 namespace 相关的 contextvars（当前用户、当前团队、当前配额上下文） | 改造 |

### 10.2 auth 插件（可独立加载）

| 文件 | 功能 |
|------|------|
| `app/plugins/auth/__init__.py` | AuthPlugin 实现：注册 JWT 中间件、登录/注册路由 |
| `app/plugins/auth/routes.py` | /auth/login, /auth/register, /auth/me 等端点 |
| `app/plugins/auth/middleware.py` | JWT 认证中间件，设置 current_user contextvar |
| `app/plugins/auth/jwt.py` | JWT 签发/验证 |
| `app/plugins/auth/passwords.py` | 密码哈希（bcrypt/argon2） |
| `app/plugins/auth/setup.py` | 首次初始化 /setup 端点 |

### 10.3 billing/cost 插件（重构现有 CostTracker）

| 文件 | 功能 |
|------|------|
| `app/plugins/billing/__init__.py` | BillingPlugin 实现：on_llm_post_call 中记录用量（重构现有 CostTracker 逻辑） |
| `app/plugins/billing/cost_tracker.py` | 从现有 CostTracker 迁移，增加 uid/team_id 维度 |
| `app/plugins/billing/routes.py` | /metrics/cost 端点（重构现有 metrics router） |

### 10.4 team 插件（本次核心新增）

```
app/plugins/team/
├── __init__.py           # TeamPlugin 实现，实现所有钩子
├── models.py             # SQLAlchemy 模型（teams/members/rules/bindings/groups/invitations/usage/notifications）
├── engine.py             # 规则计算引擎 compute_effective_rules()
├── auto_tagging.py       # 自动打标引擎
├── quota.py              # 配额管理：预检、扣减、月度重置、阈值告警
├── balance.py            # 余额查询（封装 llm_providers.fetch_balance + 缓存）
├── llm_hooks.py          # on_llm_pre_call/post_call/on_error 实现
├── meeting_hooks.py      # on_meeting_creating/accessing/created 实现
├── error_parser.py       # LLM 错误响应结构化解析
├── migrations/           # Alembic 迁移脚本
├── routes/
│   ├── setup.py          # /setup 端点（和 auth 插件协作）
│   ├── teams.py          # 团队 CRUD
│   ├── members.py        # 成员管理
│   ├── invitations.py    # 邀请/申请
│   ├── rules.py          # 规则 CRUD + 绑定
│   ├── groups.py         # 用户组
│   ├── quota.py          # 配额仪表盘
│   ├── byok.py           # BYOK API Key 管理
│   ├── namespaces.py     # Namespace 列表/切换
│   └── notifications.py  # 通知
└── encryption.py         # AES-256-GCM 加密/解密（用于 API Key 存储）
```

### 10.5 前端改造

| 模块 | 改造 |
|------|------|
| API 层 | 新增 plugins/team API 客户端；现有 API 调用在 headers 中携带 namespace 上下文 |
| 状态管理 | 新增 namespace store、auth store（用户信息）、quota store、notifications store |
| 导航栏 | 新增 Namespace 切换器组件；新增通知铃铛 |
| 路由 | 新增团队相关路由（:slug/members, :slug/rules 等） |
| 会议创建 | 新增 namespace 选择器、visibility 选择器、**Token 池选择器** |
| 会议详情 | 新增"移动到团队"操作（个人空间的会议） |
| 设置页 | 新增 BYOK 管理页面 |
| 新增页面 | 团队首页、成员管理、规则编辑器、组管理、配额仪表盘、邀请管理 |

---

## 11. AES-256-GCM 加密方案

```python
# app/plugins/team/encryption.py

class KeyEncryption:
    """API Key 加密存储

    主密钥（Master Key）来源（优先级）：
    1. 环境变量 CONCLAVE_ENCRYPTION_KEY（32字节base64编码）
    2. 文件 ~/.conclave/encryption.key（权限0600，首次启动自动生成）

    加密格式: v1:<key_version>:<nonce>:<ciphertext>:<tag>
    - key_version: 整数，支持主密钥轮转
    - nonce: 12字节随机
    - ciphertext: AES-256-GCM 加密
    - tag: 16字节 GCM 认证标签
    """

    def __init__(self):
        self._current_key = self._load_or_create_key()
        self._key_version = 1
        self._old_keys: dict[int, bytes] = {}  # 旧密钥（用于轮转期间解密）

    def encrypt(self, plaintext: str) -> bytes: ...
    def decrypt(self, encrypted: bytes) -> str: ...
    def rotate_key(self, new_key: bytes) -> None:
        """密钥轮转：新数据用新密钥加密，旧数据延迟重加密"""
        ...
```

---

## 12. 会议迁移策略

现有数据处理方式：
- 现有所有会议的 `namespace_type='personal'`，`owner_uid` 对应创建者
- 现有用户登录后自动拥有 Personal Namespace
- 不自动创建默认团队，用户可自行创建
- 个人空间会议可通过"移动到团队"操作手动迁移（用户主动操作）

---

## 13. 配额重置策略

- **重置时间**：自然月 1 号 00:00（服务器时区，默认 Asia/Shanghai）
- **重置方式**：定时任务在每月 1 号创建新的 quota_snapshots 记录，used_tokens=0
- **未用完配额**：不滚存（"用 it or lose it"），简化计费逻辑
- **重置时**：发送月度配额更新通知

---

## 14. 规则冲突处理

- 同一 team 内 `priority` 字段有 **UNIQUE 约束**（数据库层面保证）
- 如果通过某种方式（并发/迁移）出现同优先级规则：
  - 引擎计算时抛出 `RuleConflictError`
  - 错误被捕获并记录到 `audit_logs`
  - Team Admin 收到通知"规则优先级冲突，请调整"
  - 冲突期间：冲突规则都不生效，降级到上一级规则（保守策略，拒绝提权）
- 规则编辑器 UI 在保存时检查优先级冲突，拖拽排序时自动处理

---

## 15. 匿名围观策略

默认保守策略：
- 匿名围观**默认关闭**，Team Admin 在团队设置中手动开启
- 开启后：
  - 匿名用户只能看 Agent 对话流（只读）
  - 不能看到用户 intervene 的内容（保护用户隐私）
  - 不能看到文档/工作区文件
  - 单会议匿名人数上限默认 50（可配置）
  - CAPTCHA 默认关闭，Team Admin 可启用
- 匿名连接不创建 WebSocket 认证 session，使用单独的只读事件通道
- 匿名围观不调用 LLM、不消耗配额

---

## 16. 实施分期

### Phase 1: 插件框架 + 基础Auth（地基）
- [ ] PluginRegistry + ConclavePlugin Protocol
- [ ] 核心钩子点植入（LLM 调用链、会议生命周期、路由注册）
- [ ] 将现有 JWT 认证逻辑重构为 auth 插件
- [ ] 首次初始化 /setup 流程
- [ ] 用户表 + BYOK 管理（AES-256-GCM 加密）
- [ ] 个人 Namespace（默认）
- [ ] 将现有 CostTracker 重构为 billing 插件
- [ ] 前端：导航栏基础结构、BYOK 设置页、初始化页

### Phase 2: Team MVP（扁平团队）
- [ ] Team CRUD（扁平结构，暂不嵌套）
- [ ] 成员管理（邀请/移除/角色：owner/admin/member/guest）
- [ ] 会议归属 namespace（personal/team）
- [ ] 基础可见性（private/team/org）
- [ ] 团队公共池 API Key 配置
- [ ] Token 池选择器（发起会议时）
- [ ] LLM 错误差异化处理（401/402/429 识别+BYOK降级）
- [ ] 前端：Namespace 切换器、团队基础页面、Token池选择器

### Phase 3: 规则引擎 + 配额系统
- [ ] ResourceRule + RuleBinding 模型
- [ ] 规则计算引擎（优先级叠加、倍率、绝对值覆盖）
- [ ] 配额计量（pre_check、post_扣减、阈值告警、月度重置）
- [ ] 余额查询 + 缓存
- [ ] 配额仪表盘
- [ ] 团队配额耗尽自动降级 BYOK
- [ ] 通知系统
- [ ] 前端：规则编辑器（可视化+拖拽排序）、配额仪表盘、通知铃铛

### Phase 4: 树形组织 + 高级可见性
- [ ] Team 树形嵌套（LTREE path）
- [ ] subtree 可见性
- [ ] public_internet 匿名围观
- [ ] 用户组
- [ ] 自动打标（域名/正则/元数据匹配）
- [ ] 会议迁移（个人→团队）
- [ ] 前端：团队树浏览、匿名只读视图、会议移动功能

### Phase 5: 高级功能
- [ ] 域名自动加入策略
- [ ] 规则冲突检测与告警
- [ ] 密钥轮转
- [ ] 用量导出/报表
- [ ] 团队级审计日志浏览
- [ ] System Admin 面板（全局团队管理、平台用量统计）
- [ ] 插件市场/第三方插件支持（远期）

---

## 17. 已确认决策

以下问题已确认，不再变更：

1. **子团队配额来源**：父池切分。子团队的月度配额从父团队的配额池中切分（分配），不是独立设置。父团队可以控制给每个子团队分多少配额，未分配部分归父团队直接使用。
2. **团队配额充值流程**：充值是独立过程，不在 Conclave 内完成。Team Admin 直接在 LLM 提供商平台（如硅基流动/SiliconFlow、DeepSeek 开放平台、OpenRouter 等）充值，Conclave 只负责：
   - 配置团队池的 API Key（指向已充值的账号）
   - 实时/定时查询余额（调用 `fetch_balance()`）
   - 计量消耗、在余额不足时告警和降级
   - Conclave 本身不处理支付/充值流程
3. **规则编辑器形式**：MVP 阶段使用**表单式编辑器**（标准表单控件：输入框、开关、下拉、多选、倍率滑块等）。规则优先级排序支持拖拽排序（列表项上下拖动）。不做可视化连线/流程图式的规则编排（远期功能）。
4. **个人 Namespace 配额**：个人空间**无配额限制**。用户使用自己配置的 BYOK，Conclave 不计量、不限制个人空间用量。
5. **插件启动失败策略**：
   - **核心插件（auth）启动失败** → 阻断整个服务启动，打印错误日志（没人能登录，服务不可用）
   - **可选插件（team/billing）启动失败** → 打印错误日志但不阻断启动，核心会议功能仍可使用（个人空间 + BYOK），返回 503 给团队相关 API，前端显示"团队功能暂时不可用"的提示
6. **现有会议归属**：现有会议全部归到创建者的个人空间（`namespace_type='personal'`），不自动创建默认团队。用户可通过"移动到团队"操作主动迁移。

---

## 18. 多方审校小结

> 本节汇总多方审校意见，供决策参考。

---

### 18.1 Qwen 3.7 Plus 审校意见

> 审校日期: 2026-07-19
> 审校角度: 架构合理性、数据模型严谨性、安全性、性能与一致性、运维可操作性、实施可行性
> 总体评价: **概念设计扎实，工程落地存在明显空白**

#### 总体判断

本文档在**概念设计层面是扎实的**：双角色模型（层级角色 + 资源规则）的解耦、Namespace 模型、父池切分配额模型、插件化架构的方向均正确。参考 GitLab/Outline 等成熟产品的设计体现了务实的工程判断。

但在**工程落地层面存在多处关键空白**：缓存策略缺失、并发控制未讨论、监控告警未设计、数据迁移未规划、API 规范不完整。这些不是"后续再补"的细节——它们直接影响架构决策。例如，不解决规则计算的缓存问题，插件架构中"每次 LLM 调用都经过钩子链"的设计在性能上就站不住。

**核心建议：在进入实施前，补充"技术风险与缓解策略"章节，至少覆盖：规则计算缓存方案、配额并发控制方案、插件间通信治理规则、数据迁移方案、监控指标清单。**

#### 问题清单

| 编号 | 维度 | 问题 | 严重度 | 说明 |
|------|------|------|--------|------|
| Q-01 | 架构 | `ConclavePlugin` Protocol 违反接口隔离原则 | 中 | 10+ 方法的胖接口，auth 不需要 LLM 钩子，billing 不需要会议钩子。建议拆分为 `LifecycleHook`、`LLMHook`、`MeetingHook` 等小接口，插件按需实现 |
| Q-02 | 架构 | `PluginRegistry` 使用类变量全局单例 | 中 | `_plugins: dict` 作为类变量导致测试间互相污染。应改为实例化 Registry，通过依赖注入传递 |
| Q-03 | 架构 | `fire_llm_pre_call` "第一个非 None 生效"引入隐式顺序依赖 | 高 | auth 和 team 都想修改 LLM 参数时，注册顺序决定行为——不可预测且难调试。应明确钩子是链式执行还是短路执行，以及冲突时的优先级规则 |
| Q-04 | 架构 | 插件间通信缺乏治理规则 | 高 | 三种通信方式（ContextVar / 事件总线 / 服务定位）无使用边界。若 team 通过 `ctx.get_plugin("auth")` 直接调用 auth，"可插拔"变成空话。建议：插件间只通过 ContextVar 和事件总线通信，禁止直接引用 |
| Q-05 | 数据 | `resource_rules` 的 `UNIQUE(team_id, priority)` 约束过激 | 中 | 同团队内不能有两个相同优先级规则——即使 scope 不同。建议改为 `UNIQUE(team_id, priority, scope)` |
| Q-06 | 数据 | `token_usage` 表缺少关键复合索引 | 高 | 每次 LLM 调用写入一行，查询按 `(uid, created_at)` 或 `(team_id, created_at)` 过滤，无索引则数据增长后查询迅速恶化 |
| Q-07 | 数据 | `audit_logs` 和 `token_usage` 无分区策略 | 中 | 只增不删的 append-only 表，数月内达百万行。建议至少对 `token_usage` 按月分区 |
| Q-08 | 数据 | `quota_snapshots.period_month` 使用 `CHAR(7)` | 低 | 语义不清晰，无法利用 PostgreSQL 日期函数。建议改用 `DATE` 类型 |
| Q-09 | 数据 | 缺少软删除机制 | 中 | `teams`、`resource_rules` 使用 `ON DELETE CASCADE` 硬删除，误操作恢复成本极高 |
| Q-10 | 数据 | `user_api_keys.is_default` 缺少部分唯一索引 | 低 | 同一用户同一 provider 可能有多个 `is_default=TRUE`。应添加 `UNIQUE(uid, provider) WHERE is_default = TRUE` |
| Q-11 | 安全 | 密钥管理过于简化 | 中 | 主密钥存储在 `~/.conclave/encryption.key`，获得文件系统+数据库访问即可解密所有 API Key。生产部署应讨论 Vault/KMS 集成路径 |
| Q-12 | 安全 | `/setup` 端点防护不足 | 中 | 未提及速率限制、Token 过期时间、多副本部署时的 setup 状态同步 |
| Q-13 | 安全 | 匿名围观的 DoS 风险 | 低 | 未讨论匿名用户消耗 WebSocket 连接池、恶意占满名额的防护 |
| Q-14 | 性能 | `compute_effective_rules` 无缓存策略 | 高 | 每次 LLM 调用都执行多次 DB 查询，一场会议可能触发数十到数百次。建议以 `(user_id, team_id)` 为 key 缓存到 Redis，规则变更时失效 |
| Q-15 | 性能 | 余额查询 5 分钟缓存窗口内可能严重超支 | 中 | 并发会议同时通过 pre_call 余额检查后各自消耗超出实际余额。应明确超支容忍边界和事后处理策略 |
| Q-16 | 性能 | `quota_snapshots.used_tokens` 原子更新实现未指定 | 中 | 未指定是 DB 层面 `UPDATE ... SET used_tokens = used_tokens + ?` 还是应用层 CAS |
| Q-17 | 运维 | 完全缺失监控和告警设计 | 高 | 规则引擎计算延迟、配额扣减成功率、余额查询失败率——生产运维必需的指标均未涉及 |
| Q-18 | 运维 | 缺少数据迁移策略 | 高 | 现有系统引入 auth 插件后如何处理现有用户？第 12 章只讨论了会议归属，未讨论用户数据迁移路径 |
| Q-19 | 运维 | 缺少 API 版本控制策略 | 中 | 30+ 个新增端点一旦发布不可随意更改 |
| Q-20 | 运维 | 列表端点缺少分页设计 | 中 | 所有列表端点均未指定分页参数 |
| Q-21 | 实施 | Phase 1 负载严重不均 | 中 | 建议拆分为 1a（插件框架 + auth 最小化）和 1b（BYOK + billing + 前端），1a 完成后验证架构可行性再继续 |
| Q-22 | 实施 | 前端 16 个新页面与既有技术债务的矛盾 | 中 | 当前前端存在 AppContext 610 行全局状态单体、133 处 any 类型等问题，不解决基础问题直接叠加会加速债务累积 |
| Q-23 | 细节 | 倍率乘法叠加可能违反直觉 | 低 | 0.5 × 0.5 × 2.0 = 0.5，两条"打折"加一条"加倍"结果是打折。建议考虑"取最高优先级倍率" |
| Q-24 | 细节 | `visibility='org'` 的跨团队可见性 | 低 | 任何已登录用户（含其他团队）都能查看 org 级别会议。多组织部署时需重新审视 |
| Q-25 | 细节 | 规则冲突"降级到上一级"的边界 | 低 | 若冲突的是最高优先级规则，"上一级"是什么？需明确 |

#### 建议补充的内容清单

在进入实施之前，建议补充以下内容：

1. **技术风险与缓解策略**（独立章节）——规则计算缓存方案、配额并发控制方案、插件间通信治理规则、数据迁移方案、监控指标清单（关键 SLI/SLO）
2. **API 规范补充**——分页参数标准、错误响应格式、API 版本化策略
3. **索引与分区策略**——`token_usage` 复合索引 + 按月分区、`audit_logs` 按月分区、查询模式与索引对应关系
4. **实施分期调整**——Phase 1 拆分为 1a/1b、各 Phase 增加工作量估算、明确 Phase 间依赖关系和验收标准

---

### 18.2 Deep Seek V4 Pro 审校意见

> 以下审校意见由 **Deep Seek V4 Pro** 于 2026-07-19 出具，基于对本文档（v0.3 Draft）的逐节审查。审校视角：架构安全性、实施可行性、数据一致性、API 完整性、边界条件覆盖。

#### 总体评价

这是一份**思路清晰、架构完整的设计文档**。插件化架构的核心决策（核心不感知多租户，通过钩子注入）是正确的，避免了将多租户逻辑耦合进核心代码的常见陷阱。数据模型设计（LTREE 物化路径、双角色模型、资源规则引擎）考虑周全，配额切分与降级流程设计合理。整体质量在同类设计文档中属上乘。

然而，以下问题需要在进入实施阶段前严肃对待，涉及**安全性、数据一致性、钩子链语义、API 完整性**四个维度。

#### 架构层面

**钩子链的"首个非空即生效"策略存在隐式优先级风险**（§0.3）。`PluginRegistry.fire_llm_pre_call` 按注册顺序依次调用，第一个返回非 None 的生效。如果 billing 插件注册在 team 插件之前，且 billing 也返回了 `LLMOverride`，team 的配额检查将被完全跳过。插件的注册顺序（由 `CONCLAVE_PLUGINS` 环境变量决定）成为隐式的优先级机制，但文档对此无任何说明或约束。**建议**：将钩子明确分为"拦截型"（first-wins）和"观察型"（all-called）两类，并在 ConclavePlugin Protocol 中声明每个钩子的类型。

**插件启动失败后的"半健康"状态**（§0.3）。team 插件启动失败不阻断服务，但若 team 插件加载成功却数据库迁移失败（halfway migration），系统处于半健康状态——团队 API 返回 503，但会议钩子仍触发。`on_meeting_creating` 钩子尝试校验 namespace 权限时行为不可预测。**建议**：插件暴露 `health_check()` 方法，核心在每次钩子调用前检查插件健康状态，不健康的插件钩子自动跳过并记录告警。

**`PluginContext` 服务定位器引入隐式耦合**（§0.4）。`ctx.get_plugin("auth")` 打破了插件间的松耦合承诺——team 插件硬依赖 auth 插件的存在和接口。**建议**：要么在 Plugin Protocol 中显式声明 `dependencies: list[str]`，要么完全通过 ContextVar + 事件总线解耦，禁止直接获取其他插件实例。

#### 安全层面

**JWT 存储方案未明确**（§10.2）。文档未说明 Token 存储位置。当前系统（审计已发现）将 JWT 存储在 `localStorage`，存在 XSS 窃取风险。多租户场景下风险放大——窃取 Team Admin 的 Token 后可管理整个团队。**建议**：在文档中明确 Token 存储策略，优先考虑 httpOnly + Secure + SameSite=Strict 的 Cookie 方案。

**加密方案描述存在细节缺失**（§11）。声明使用 AES-256-GCM，但存储格式 `v1:<key_version>:<nonce>:<ciphertext>:<tag>` 未说明各字段的编码方式（hex/base64）和分隔符转义规则。GCM 中 tag 通常附加在 ciphertext 末尾而非独立字段。**建议**：补充完整的编码规范和分隔符转义策略。

**匿名围观的安全边界不够清晰**（§15）。"单独的只读事件通道"未说明：如何防止匿名用户通过 WebSocket 发送消息（协议层还是服务端校验？）；匿名用户的 IP 是否记录；"不能看到用户 intervene 的内容"的过滤在哪个层面实现。**建议**：补充匿名通道的技术实现细节和恶意用户追溯机制。

**配额预扣的竞态条件**（§9.3）。"预扣配额（仅标记，不实际扣减）"——如果预扣标记和实际扣减之间有时间窗口，用户可能在窗口内发起第二个会议绕过配额。**建议**：明确预扣的原子性保证（`SELECT ... FOR UPDATE` 或 Redis 计数器）。

#### 数据模型层面

**`teams` 表缺少数据库层 CHECK 约束**（§3.1）。`allocated_to_children <= monthly_token_budget` 的业务约束仅在应用层描述，数据库层面无保护。高并发分配场景下应用层校验无法保证一致性。**建议**：添加 CHECK 约束到数据库层，分配操作使用 `SELECT ... FOR UPDATE`。

**`quota_snapshots` 的 UNIQUE 约束在 NULL 上有语义漏洞**（§3.1）。`UNIQUE(uid, team_id, period_month)` 在 PostgreSQL 中 `team_id IS NULL`（个人空间）时，NULL != NULL，同一用户可有多条个人空间快照记录。**建议**：使用部分唯一索引（partial unique index）或哨兵值替代 NULL。

**`token_usage` 表缺少分区策略**（§3.1）。这是写入热点表，数据量随时间线性增长。文档未提及分区或归档策略。**建议**：明确数据保留策略（如保留 12 个月，按月分区），并补充索引设计。

**`teams.slug` 的唯一性范围未明确**（§3.1）。`slug VARCHAR(64) UNIQUE NOT NULL` 是全局唯一还是同层级唯一？全局唯一时，用户创建子团队可能遇到"slug 已被其他组织占用"。**建议**：明确 slug 唯一性范围，或采用 `parent_id + slug` 的复合唯一约束。

#### 规则引擎层面

**规则冲突降级缺少通知**（§14）。"冲突规则都不生效，降级到上一级规则"是合理的保守策略，但缺少降级后的通知机制。假设"VIP 配额 10M"和"实习生配额 0.5M"冲突，降级后 VIP 用户可能突然无法使用团队配额，而管理员无任何告警。**建议**：冲突降级时对受影响用户发送通知，配额仪表盘高亮显示冲突状态。

**`token_quota_multiplier` 乘法叠加可能产生反直觉结果**（§4.1）。两个规则分别设置倍率 0.5 和 0.5，最终叠加为 0.25。管理员可能期望"取最小值"而非"乘法叠加"。**建议**：在规则编辑器 UI 中展示乘法叠加计算过程，提供"预览"功能。

**自动打标触发时机不完整**（§4.3）。"用户加入团队或首次登录时自动评估"——如果管理员在用户已加入后修改规则中的 `match_email_domains`，已加入用户是否重新评估？**建议**：明确自动打标的完整触发时机清单（加入、规则修改、手动触发），并说明已存在绑定在规则修改后的行为。

#### API 设计层面

**分页缺失**（§7）。所有列表端点（成员、用量、会议、通知等）均无分页参数。**建议**：统一定义 `PaginatedResponse` 格式，在所有列表端点中强制分页。

**错误响应格式未定义**。多个插件协作场景下，不同插件可能抛出不同格式的错误，前端无法统一处理。**建议**：定义标准错误响应格式 `{error: {code, message, details}}`，所有插件遵守。

**批量操作支持不足**（§7.3）。`POST /api/teams/:team_id/members` 接受批量邮箱，但 `PATCH /api/teams/:team_id/members/:uid` 一次只能修改一个成员角色。**建议**：补充批量修改成员角色的端点。

#### 实施分期层面

**Phase 1 范围过大**（§16）。Phase 1 包含插件框架、auth 重构、setup 流程、用户表、BYOK、CostTracker 重构、个人 Namespace、前端基础——这实际上是将现有认证体系完全重写。**建议**：将 auth 重构拆分为独立 Phase 0（预研+新旧并行），确保过渡期可共存。

**缺少回滚策略**（§16）。如果 Phase 2 上线后团队功能有严重 bug，如何快速回退到仅个人空间模式？**建议**：在插件框架层面支持热开关（如 Redis 配置项），允许不重启服务降级。

#### 其他缺失项

| 缺失项 | 影响 | 建议 |
|--------|------|------|
| 性能指标与 SLO | 无延迟约束，`on_llm_pre_call` 中 `fetch_balance()` 可能阻塞 LLM 调用 | 定义钩子最大延迟（如 200ms），超时自动跳过 |
| 并发控制细节 | `quota_snapshots.used_tokens` 的原子更新策略未说明（乐观锁 vs 悲观锁） | 明确采用 `UPDATE ... SET used = used + N` + 重试机制 |
| 监控与告警设计 | 多处"发通知"但无优先级分级、渠道、聚合策略 | 定义通知优先级（P0-P3）、渠道（站内信/邮件/Webhook）、聚合窗口 |
| 国际化考虑 | `display_name`、`name` 等字段为单列设计 | 如需国际化，预留 JSONB 格式扩展 |
| 数据迁移策略 | 现有 `meetings` 表加字段的迁移脚本未描述 | 补充 migration 的执行计划和回滚方案 |

#### 审校结论

本设计文档**可进入实施阶段**，但建议在开工前优先解决以下四项底层缺陷（按严重程度排序）：

1. **钩子链语义明确化**（见上方"架构层面"）—— 影响所有插件的行为正确性
2. **`quota_snapshots` NULL 唯一约束修正**（见上方"数据模型层面"）—— 数据库层面的数据一致性漏洞
3. **JWT 存储方案明确化**（见上方"安全层面"）—— 安全基线问题
4. **规则冲突降级通知补充**（见上方"规则引擎层面"）—— 生产事故的最后一道防线

其余问题可在各 Phase 实施过程中逐项解决。文档整体质量可评为 **B+/A- 级**，在同类设计文档中处于上乘水平。

---
*审校人：Deep Seek V4 Pro*
*审校日期：2026-07-19*
*审校范围：全文 §0–§17*
