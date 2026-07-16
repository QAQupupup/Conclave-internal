# Conclave RBAC 认证鉴权体系设计方案

## 一、现状分析

### 当前认证架构

| 维度 | 现状 | 问题 |
|------|------|------|
| JWT | 自实现 HMAC-SHA256（非 PyJWT） | 无 refresh token，过期即重新登录 |
| 用户模型 | `users` 表：username, password_hash, role, display_name, is_active | 缺少 email、avatar、phone 等字段 |
| 角色体系 | 硬编码 2 个角色：`admin` / `user` | 无权限粒度，admin 拥有全部权限，user 无任何管理权限 |
| 权限控制 | 路由内 `if role == 'admin'` 判断 | 无策略引擎，新增角色需改代码 |
| 密码找回 | 无 | 无法找回密码 |
| Token 刷新 | 无 | 24h 过期后强制重新登录 |
| 邮箱 | 无 | 无法通知、无法找回密码 |
| 前端守卫 | `api()` 401 后弹登录框 | 无路由级守卫，无 token 有效期预检 |

### 当前 users 表结构

```sql
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(64) UNIQUE NOT NULL,
    password_hash VARCHAR(256) NOT NULL,
    role VARCHAR(32) NOT NULL DEFAULT 'user',       -- 仅 admin/user
    display_name VARCHAR(128),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    last_login_at TIMESTAMP
);
```

---

## 二、目标架构

### 整体设计

```
┌─────────────────────────────────────────────────────┐
│                    前端 (Browser)                      │
│                                                       │
│  ┌─────────────┐  ┌──────────────┐  ┌─────────────┐ │
│  │ 路由守卫     │  │ API 拦截器    │  │ Token 管理   │ │
│  │ (beforeRoute)│  │ (401→login)  │  │ (access+ref)│ │
│  └──────┬──────┘  └──────┬───────┘  └──────┬──────┘ │
│         │                │                  │        │
│         ▼                ▼                  ▼        │
├─────────────────────────────────────────────────────┤
│                   nginx (5173→80)                     │
│           /auth/* /api/* → proxy to backend           │
├─────────────────────────────────────────────────────┤
│                  后端 (FastAPI)                       │
│                                                       │
│  ┌──────────┐  ┌───────────┐  ┌──────────────────┐  │
│  │ Auth MW  │→ │ CasBin ENF│→ │ Route Handler    │  │
│  │ JWT 验证  │  │ RBAC 策略 │  │ (业务逻辑)       │  │
│  └──────────┘  └───────────┘  └──────────────────┘  │
│                                                       │
│  ┌─────────────────────────────────────────────────┐ │
│  │              PostgreSQL                         │ │
│  │  users / roles / permissions / user_roles       │ │
│  │  casbin_rule (策略表) / email_verifications      │ │
│  └─────────────────────────────────────────────────┘ │
│                                                       │
│  ┌─────────────┐  ┌──────────────┐                  │
│  │ SMTP 发信    │  │ Redis 会话   │                  │
│  │ (密码找回)   │  │ (token 黑名单)│                  │
│  └─────────────┘  └──────────────┘                  │
└─────────────────────────────────────────────────────┘
```

---

## 三、CasBin RBAC 模型设计

### 模型文件 `rbac_model.conf`

```ini
[request_definition]
r = sub, obj, act

[policy_definition]
p = sub, obj, act

[role_definition]
g = _, _

[policy_effect]
e = some(where (p.eft == allow))

[matchers]
m = g(r.sub, p.sub) && keyMatch2(r.obj, p.obj) && r.act == p.act
```

说明：
- `sub` = 用户ID 或角色名
- `obj` = 资源路径（如 `/meetings/*`、`/agent-roles`）
- `act` = HTTP 方法（GET/POST/PUT/DELETE）
- `g` = 角色继承关系（user→role 映射）
- `keyMatch2` = 支持 `/meetings/:id` 通配符匹配

### 策略表 `casbin_rule`（PostgreSQL）

CasBin 的 SQL Adapter 自动创建：

```sql
CREATE TABLE casbin_rule (
    id SERIAL PRIMARY KEY,
    ptype VARCHAR(100) NOT NULL,    -- 'p' 策略 / 'g' 角色继承
    v0   VARCHAR(100) NOT NULL,     -- sub (角色/用户)
    v1   VARCHAR(100) NOT NULL,     -- obj (资源路径)
    v2   VARCHAR(100) DEFAULT '',   -- act (HTTP 方法)
    v3   VARCHAR(100) DEFAULT '',
    v4   VARCHAR(100) DEFAULT '',
    v5   VARCHAR(100) DEFAULT ''
);
```

### 预置角色与权限

| 角色 | code | 说明 | 典型权限 |
|------|------|------|----------|
| 系统管理员 | `system_admin` | 全部权限，管理用户/角色 | `*` → `*` |
| 项目管理员 | `project_admin` | 管理会议、Agent 角色、查看监控 | meetings CRUD, agent-roles, metrics |
| 会议操作员 | `meeting_operator` | 创建/运行会议、介入 | meetings create/run/control |
| 只读观察者 | `viewer` | 查看会议列表和报告 | meetings GET, reports GET |

预置策略数据：

```python
POLICIES = [
    # system_admin — 通配权限
    ("p", "system_admin", "*", "GET"),
    ("p", "system_admin", "*", "POST"),
    ("p", "system_admin", "*", "PUT"),
    ("p", "system_admin", "*", "DELETE"),

    # project_admin
    ("p", "project_admin", "/meetings/*", "GET"),
    ("p", "project_admin", "/meetings/*", "POST"),
    ("p", "project_admin", "/meetings/*", "PUT"),
    ("p", "project_admin", "/agent-roles", "GET"),
    ("p", "project_admin", "/agent-roles", "POST"),
    ("p", "project_admin", "/metrics", "GET"),
    ("p", "project_admin", "/preferences/*", "GET"),

    # meeting_operator
    ("p", "meeting_operator", "/meetings", "GET"),
    ("p", "meeting_operator", "/meetings", "POST"),
    ("p", "meeting_operator", "/meetings/:id/run", "POST"),
    ("p", "meeting_operator", "/meetings/:id/control", "POST"),
    ("p", "meeting_operator", "/meetings/:id/intervene", "POST"),

    # viewer
    ("p", "viewer", "/meetings", "GET"),
    ("p", "viewer", "/meetings/:id", "GET"),
    ("p", "viewer", "/meetings/:id/report-layout", "GET"),

    # 角色继承：admin 用户 → system_admin 角色
    ("g", "admin", "system_admin"),
]
```

---

## 四、数据库 Schema 变更

### 1. 扩展 `users` 表

```sql
ALTER TABLE users
    ADD COLUMN IF NOT EXISTS email VARCHAR(255) UNIQUE,
    ADD COLUMN IF NOT EXISTS phone VARCHAR(32),
    ADD COLUMN IF NOT EXISTS avatar_url VARCHAR(512),
    ADD COLUMN IF NOT EXISTS status VARCHAR(20) DEFAULT 'active',
    -- status: active / disabled / pending_email / locked
    ADD COLUMN IF NOT EXISTS email_verified_at TIMESTAMP,
    ADD COLUMN IF NOT EXISTS password_reset_token VARCHAR(128),
    ADD COLUMN IF NOT EXISTS password_reset_expires_at TIMESTAMP,
    ADD COLUMN IF NOT EXISTS failed_login_count INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS locked_until TIMESTAMP,
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT NOW();
```

### 2. 角色表 `roles`

```sql
CREATE TABLE IF NOT EXISTS roles (
    id SERIAL PRIMARY KEY,
    code VARCHAR(50) UNIQUE NOT NULL,    -- system_admin, project_admin, ...
    name VARCHAR(100) NOT NULL,           -- 显示名
    description TEXT,
    is_builtin BOOLEAN DEFAULT FALSE,     -- 内置角色不可删除
    sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

### 3. 用户-角色关联表 `user_roles`

```sql
CREATE TABLE IF NOT EXISTS user_roles (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role_id INTEGER NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(user_id, role_id)
);
```

### 4. CasBin 策略表 `casbin_rule`

由 CasBin SQL Adapter 自动管理。

### 5. 邮箱验证码表 `email_verifications`

```sql
CREATE TABLE IF NOT EXISTS email_verifications (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    type VARCHAR(20) NOT NULL,            -- 'register' / 'reset_password' / 'change_email'
    code VARCHAR(64) NOT NULL,            -- 验证码或 token
    email VARCHAR(255) NOT NULL,
    expires_at TIMESTAMP NOT NULL,
    used_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_email_verif_code ON email_verifications(code) WHERE used_at IS NULL;
```

---

## 五、后端实现方案

### 1. 依赖新增

```
# requirements.txt 新增
casbin>=1.34
casbin-sqlalchemy-adapter>=1.4
PyJWT>=2.8          # 替换自实现 JWT，支持 RS256/ES256
pydantic[email]     # EmailStr 验证
aiosmtplib>=3.0     # 异步 SMTP 发信
```

### 2. 认证流程

```
登录流程:
  POST /auth/login {username_or_email, password}
    → authenticate_user()
    → create_access_token() — 15min 有效期
    → create_refresh_token() — 7d 有效期，存 Redis
    → 返回 {access_token, refresh_token, user}

Token 验证流程 (中间件):
  Authorization: Bearer <access_token>
    → verify_jwt()
    → 检查 Redis 黑名单（是否已 logout）
    → 注入 request.state.auth_user = {uid, username, roles}

权限检查流程 (CasBin):
  auth_user → enforcer.enforce(uid, path, method)
    → True: 放行
    → False: 403 Forbidden

Token 刷新流程:
  POST /auth/refresh {refresh_token}
    → verify_refresh_token() (Redis 查询)
    → 检查 access_token 是否已过期（防止提前刷新）
    → 签发新 access_token
    → 旧 access_token 加入 Redis 黑名单（剩余 TTL）

登出流程:
  POST /auth/logout
    → access_token + refresh_token 加入 Redis 黑名单
    → 清除前端 localStorage

密码找回流程:
  POST /auth/forgot-password {email}
    → 生成 reset_token (6位验证码 或 URL token)
    → 存 email_verifications 表（15min 有效）
    → SMTP 发送找回邮件
    → 返回 200（不泄露邮箱是否存在）

  POST /auth/reset-password {token, new_password}
    → 验证 token 有效性 + 未过期
    → 更新密码
    → 标记 token 已使用
    → 作废所有该用户的 refresh_token
```

### 3. CasBin 集成

```python
# backend/app/rbac.py
import casbin
from casbin_sqlalchemy_adapter import Adapter

_enforcer = None

def init_casbin(db_url: str):
    """初始化 CasBin enforcer（单例）"""
    global _enforcer
    adapter = Adapter(db_url)
    model_path = os.path.join(os.path.dirname(__file__), "rbac_model.conf")
    _enforcer = casbin.Enforcer(model_path, adapter)
    _enforcer.load_policy()
    # 加载预置角色和策略（首次启动）
    _seed_builtin_policies()

def get_enforcer() -> casbin.Enforcer:
    return _enforcer

def check_permission(uid: str, path: str, method: str) -> bool:
    """权限检查"""
    return _enforcer.enforce(uid, path, method)

def assign_role(uid: str, role_code: str):
    """给用户分配角色"""
    _enforcer.add_role_for_user(uid, role_code)

def revoke_role(uid: str, role_code: str):
    """撤销用户角色"""
    _enforcer.delete_role_for_user(uid, role_code)
```

### 4. 中间件改造

```python
# middleware.py 改造后
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    method = request.method

    # 1. 公开路径放行
    if _is_public(path):
        return await call_next(request)

    # 2. 提取 JWT
    token = _extract_bearer_token(request)
    if not token:
        return _unauthorized("请先登录")

    # 3. 验证 JWT + 检查黑名单
    payload = verify_jwt(token)
    if not payload:
        return _unauthorized("token 无效或已过期")
    if _is_blacklisted(token):
        return _unauthorized("token 已失效")

    # 4. 注入用户信息
    uid = str(payload["uid"])
    request.state.auth_user = {
        "uid": uid,
        "username": payload["sub"],
        "roles": payload.get("roles", []),
    }

    # 5. CasBin 权限检查
    from app.rbac import check_permission
    if not check_permission(uid, path, method):
        return _forbidden("无权限访问此资源")

    return await call_next(request)
```

### 5. 新增 API 端点

```
认证相关:
  POST   /auth/register          — 用户注册（邮箱+密码）
  POST   /auth/login             — 登录（支持 username 或 email）
  POST   /auth/refresh           — 刷新 access_token
  POST   /auth/logout            — 登出（token 加入黑名单）
  GET    /auth/me                — 获取当前用户信息（含角色）
  PUT    /auth/me                — 更新个人资料（display_name, avatar）
  POST   /auth/change-password   — 修改密码（需当前密码）
  POST   /auth/forgot-password   — 发起密码找回（发邮件）
  POST   /auth/reset-password    — 重置密码（验证码+新密码）
  POST   /auth/verify-email      — 验证邮箱

用户管理 (system_admin/project_admin):
  GET    /auth/users             — 用户列表
  POST   /auth/users             — 创建用户
  PUT    /auth/users/:id         — 更新用户
  DELETE /auth/users/:id         — 禁用/删除用户
  POST   /auth/users/:id/roles   — 分配角色
  GET    /auth/roles             — 角色列表
  POST   /auth/roles             — 创建自定义角色
  PUT    /auth/roles/:id         — 更新角色
  GET    /auth/permissions       — 权限列表（可选）
```

---

## 六、前端实现方案

### 1. Token 管理

```javascript
// 双 token 策略
const ACCESS_TOKEN_KEY = 'conclave_access';   // 15min
const REFRESH_TOKEN_KEY = 'conclave_refresh';  // 7d

// API 拦截器改造
async function api(path, opts = {}) {
    const headers = { ...opts.headers };
    const token = getAccessToken();
    if (token) headers['Authorization'] = `Bearer ${token}`;

    const res = await fetch(path, { ...opts, headers });

    // 401 时尝试刷新 token
    if (res.status === 401) {
        const refreshed = await tryRefreshToken();
        if (refreshed) {
            // 重新发起原请求
            const newToken = getAccessToken();
            headers['Authorization'] = `Bearer ${newToken}`;
            return fetch(path, { ...opts, headers });
        } else {
            // 刷新失败，跳转登录
            clearTokens();
            redirectToLogin();
            throw new Error('登录已过期');
        }
    }

    if (res.status === 403) {
        showToast('无权限执行此操作', 'error');
    }

    return res;
}

// 静默刷新（access_token 剩余 < 2min 时自动刷新）
async function maybeRefreshToken() {
    const token = getAccessToken();
    if (!token) return;

    const payload = decodeJwtPayload(token);
    const remaining = payload.exp - Date.now() / 1000;

    if (remaining < 120) {  // 剩余不足 2 分钟
        await tryRefreshToken();
    }
}

// 路由守卫：每次视图切换前检查
function guardRoute(viewName) {
    if (!getAccessToken()) {
        redirectToLogin();
        return false;
    }
    // 预检 token 有效性
    maybeRefreshToken();
    return true;
}
```

### 2. 登录页改造

```
登录页要素:
- 用户名或邮箱输入框
- 密码输入框（含显示/隐藏切换）
- "记住我" 复选框（7天免登录 = refresh_token 7d）
- "忘记密码？" 链接 → /auth/forgot-password
- "注册账号" 链接 → /auth/register（可选，默认 admin 创建用户）

注册页要素:
- 用户名
- 邮箱
- 密码 + 确认密码
- 注册后发送验证邮件

忘记密码页:
- 邮箱输入
- 发送验证码
- 输入验证码 + 新密码
- 重置完成
```

### 3. 用户中心页

```
个人资料:
- 头像、显示名、邮箱（已验证/未验证标记）
- 修改密码（需当前密码）
- 修改邮箱（需验证新邮箱）

角色权限:
- 当前角色列表
- 权限说明（只读展示）

管理员视图（仅 system_admin）:
- 用户列表（搜索、筛选、分页）
- 创建/编辑用户
- 分配角色
- 禁用/启用用户
- 角色管理（内置角色只读，自定义角色可编辑）
```

---

## 七、邮件配置

### SMTP 环境变量

```env
# .env
CONCLAVE_SMTP_HOST=smtp.example.com
CONCLAVE_SMTP_PORT=587
CONCLAVE_SMTP_USERNAME=noreply@example.com
CONCLAVE_SMTP_PASSWORD=xxx
CONCLAVE_SMTP_USE_TLS=true
CONCLAVE_SMTP_FROM_NAME=Conclave
CONCLAVE_SMTP_FROM_EMAIL=noreply@example.com

# 邮箱验证码配置
CONCLAVE_EMAIL_CODE_LENGTH=6
CONCLAVE_EMAIL_CODE_EXPIRE_MINUTES=15
CONCLAVE_EMAIL_RESET_URL=https://conclave.example.com/reset-password?token=
```

### 邮件模板

密码找回邮件：
- 6 位数字验证码（15 分钟有效）
- 或含 token 的重置链接 URL

### 开发模式

未配置 SMTP 时：
- 验证码写入日志（`[DEV] 验证码: 123456`）
- 不实际发送邮件
- 前端显示验证码（开发模式提示）

---

## 八、关于你的问题

### Q1: 前端如何判断登录有效性？

**方案**：双 Token + 主动刷新 + 被动重试

```
主动: 路由切换时 maybeRefreshToken() — access_token 剩余 <2min 自动刷新
被动: API 返回 401 时 tryRefreshToken() — 尝试刷新后重发请求
失败: refresh_token 也过期 → 清除 token → 重定向到 /auth/login
```

比单 token 方案优势：用户无感知刷新，不会被 401 弹窗打断操作。

### Q2: 后端基于标准 header 的 auth token 认证？

**确认**：`Authorization: Bearer <jwt>` 是标准做法，保持不变。

但需要补充：
- **Refresh Token 不走 header**，单独走 `/auth/refresh` 端点 body 传输
- **WebSocket 认证**保持 `?token=` query param（WS 不支持自定义 header）
- **Token 黑名单**用 Redis（access_token 短 TTL，黑名单 TTL = 剩余有效期）

### Q3: CasBin 是否必要？

**我的建议**：CasBin 适合复杂权限场景，但对于 Conclave 当前阶段可能过重。

| 方案 | 适用场景 | 优势 | 劣势 |
|------|----------|------|------|
| **CasBin RBAC** | 多角色、细粒度权限、动态策略 | 策略与代码解耦，支持运行时调整 | 新增依赖，学习成本，策略文件维护 |
| **简化 RBAC** (推荐) | 角色固定 <10 种，权限按角色映射 | 零新依赖，代码简洁直观 | 新增角色需改代码 |
| **FastAPI Depends** | 极简场景 | 框架原生 | 无角色继承，无策略管理 |

**推荐路线**：
1. **Phase 1**：先做简化 RBAC（角色表 + 权限装饰器），不引入 CasBin
2. **Phase 2**：当角色超过 5 种或需要动态策略时再接入 CasBin

简化 RBAC 示例（不引入 CasBin）：
```python
# 权限映射表（代码内定义，清晰直观）
ROLE_PERMISSIONS = {
    "system_admin": ["*"],
    "project_admin": ["meetings:*", "agent-roles:*", "metrics:read", "preferences:read"],
    "meeting_operator": ["meetings:read", "meetings:create", "meetings:run", "meetings:control", "meetings:intervene"],
    "viewer": ["meetings:read", "meetings:report"],
}

def require_permission(resource: str, action: str):
    """FastAPI 依赖注入：检查当前用户是否有权限"""
    def checker(request: Request):
        user = request.state.auth_user
        if not user:
            raise HTTPException(401, "未登录")
        if not has_permission(user["roles"], resource, action):
            raise HTTPException(403, f"无权限: {resource}:{action}")
    return checker
```

### Q4: 邮箱找回密码的流程

```
1. 用户输入邮箱 → POST /auth/forgot-password {email}
2. 后端生成 6 位验证码 → 存 DB（15min 有效）→ SMTP 发邮件
3. 用户输入验证码 + 新密码 → POST /auth/reset-password {token, new_password}
4. 后端验证码校验 → 更新密码 → 作废所有 refresh_token → 返回成功
5. 前端跳转登录页

安全措施:
- 邮箱不存在时仍返回 200（防枚举）
- 验证码尝试 5 次后失效
- 同邮箱 60s 内只能发一次
- 重置后作废所有会话（force logout everywhere）
```

---

## 九、实施计划

### Phase 1: 基础 RBAC（1-2 天）
- [ ] 扩展 users 表（加 email、status 字段）
- [ ] 创建 roles + user_roles 表
- [ ] 简化 RBAC 权限检查（不引入 CasBin）
- [ ] JWT 改用 PyJWT（支持 RS256）
- [ ] Refresh Token 机制（Redis 存储）
- [ ] Token 黑名单（Redis）

### Phase 2: 前端改造（1 天）
- [ ] 双 Token 管理（access + refresh）
- [ ] API 拦截器 401 自动刷新
- [ ] 路由守卫 + 预检刷新
- [ ] 登录页改造（邮箱登录支持）
- [ ] 忘记密码页面
- [ ] 用户中心页面

### Phase 3: 邮件系统（1 天）
- [ ] SMTP 配置
- [ ] 邮件模板（密码找回）
- [ ] 邮箱验证流程
- [ ] 开发模式日志输出验证码

### Phase 4: 用户管理（1 天）
- [ ] 用户列表 CRUD（admin）
- [ ] 角色分配 UI
- [ ] 角色管理页面

### Phase 5: CasBin 接入（可选，按需）
- [ ] 当角色 >5 种或需要动态策略时引入
- [ ] 迁移简化 RBAC → CasBin
- [ ] 策略管理 UI
