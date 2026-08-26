# 认证刷新流程（Auth Refresh Flow）

## 架构概览

```
┌─────────────────────────────────────────────────────────────┐
│                        浏览器                                │
│  ┌──────────┐    ┌──────────────┐    ┌───────────────────┐  │
│  │ React UI │───▶│ api.ts (拦截) │───▶│ zustand auth store│  │
│  └──────────┘    └──────┬───────┘    └────────┬──────────┘  │
│                         │                      │             │
│                  401→自动刷新            AuthInit 初始化      │
│                         │                      │             │
└─────────────────────────┼──────────────────────┼─────────────┘
                          │                      │
               ┌──────────▼──────────┐  ┌───────▼─────────┐
               │  HttpOnly Cookie    │  │ localStorage    │
               │  refresh_token      │  │ token (persist) │
               └──────────┬──────────┘  └───────┬─────────┘
                          │                      │
┌─────────────────────────┼──────────────────────┼─────────────┐
│                        后端                    │             │
│  ┌───────────────┐  ┌──▼────────────────┐  ┌──▼──────────┐  │
│  │ POST /login   │  │ POST /auth/refresh│  │ GET /auth/me│  │
│  │ set-cookie    │  │ 验证 refresh_token│  │ 验证 access  │  │
│  │ + access_token│  │ 签发新 access+refresh││ 返回 user   │  │
│  └───────────────┘  └───────────────────┘  └─────────────┘  │
│                                                             │
│  JWT 配置：                                                 │
│  - access_token: HS256, 15分钟过期 (JWT_EXPIRE_SECONDS=900) │
│  - refresh_token: HttpOnly Cookie, 7天过期                  │
│  - CSRF: 双重提交 Cookie（csrf_token cookie + X-CSRF-Token） │
└─────────────────────────────────────────────────────────────┘
```

## 关键文件

| 文件 | 职责 |
|---|---|
| `backend/app/auth.py` | JWT 创建/验证、密码哈希、Token 配置常量 |
| `backend/app/plugins/builtin/auth/middleware.py` | Cookie/Bearer 提取、CSRF 检查、速率限制、公开路径白名单 |
| `backend/app/plugins/builtin/auth/router.py` | `/auth/login`、`/auth/refresh`、`/auth/logout` 端点 |
| `backend/app/public_paths.py` | 公开路径白名单（不需要认证的路径） |
| `frontend/src/lib/api.ts` | API 请求封装、自动刷新拦截器、CSRF 自动附加 |
| `frontend/src/stores/auth-slice.ts` | zustand store、`fetchUser`、`silentRefresh`、`logout` |
| `frontend/src/App.tsx` | `AuthInit` 组件，认证初始化唯一入口 |

## Token 自动刷新机制

`api.ts` 中的 `request()` 函数实现了自动刷新：

1. 发送请求时附加 `Authorization: Bearer <token>` 和 `X-CSRF-Token`（写操作）
2. 如果响应 401 且不是 auth 请求（`/auth/login`、`/auth/refresh`、`/auth/logout`）：
   - 如果没有正在进行的刷新，调用 `refreshAccessToken()` 发起刷新
   - 如果已有刷新在进行中，将请求加入 `pendingRequests` 队列等待
3. 刷新成功：更新 store 中的 token，重放所有排队请求
4. 刷新失败：reject 所有排队请求，调用 `logout()` 跳转到登录页

### 并发请求队列

当多个请求同时遇到 401 时，只发起**一次**刷新请求，其余请求排队等待结果。避免刷新风暴。

## CSRF 双重提交 Cookie 模式

1. 登录/刷新后，后端设置 `csrf_token` Cookie（非 HttpOnly，JS 可读）
2. 前端写操作（POST/PUT/DELETE/PATCH）时：
   - 从 `document.cookie` 读取 `csrf_token`
   - 附加到 `X-CSRF-Token` header
3. 后端中间件验证 Cookie 值与 Header 值一致

`api.ts` 已自动处理 CSRF 附加，组件层无需手动处理。

## AuthInit 初始化流程

页面加载时的认证初始化（`App.tsx` 的 `AuthInit` 组件）：

1. 等待 zustand persist hydration（含超时兜底，见 `zustand-persist-patterns.md`）
2. 如果 store 中有 token：
   a. 调用 `fetchUser()` 验证 token 是否有效
   b. 如果 fetchUser 失败（token 过期），调用 `silentRefresh()` 用 refresh_token 刷新
3. 如果 store 中无 token：
   a. 调用 `silentRefresh()` 尝试用 HttpOnly refresh_token cookie 刷新
4. 如果所有尝试都失败：设置 `isLoading=false`，`ProtectedRoute` 会重定向到登录页

## 修改认证代码的检查清单

### 修改 Token 过期时间
- [ ] 更新 `backend/app/auth.py` 中的 `JWT_EXPIRE_SECONDS` 默认值
- [ ] 确认 `CONCLAVE_JWT_EXPIRE` 环境变量未在 docker-compose 中覆盖旧值
- [ ] 前端 `mock-data.ts` 中 `jwt_expire_minutes` 同步更新
- [ ] 重建后端容器：`docker compose up -d --build backend`

### 添加公开路径
- [ ] 在 `backend/app/public_paths.py` 的 `PUBLIC_PATHS` 中添加路径
- [ ] 路径使用小写，不含末尾斜杠
- [ ] 子路径自动公开（前缀匹配）

### 修改 Cookie 设置
- [ ] 确认 `COOKIE_SECURE` 环境变量在生产环境为 `True`（HTTPS）
- [ ] 确认 `COOKIE_SAMESITE` 为 `'lax'` 或 `'strict'`
- [ ] access_token Cookie 的 `max_age` 必须与 `JWT_EXPIRE_SECONDS` 一致
- [ ] refresh_token Cookie 的 `max_age` 必须与 `REFRESH_TOKEN_EXPIRE_SECONDS` 一致

### 修改前端认证逻辑
- [ ] 不要在 `onRehydrateStorage` 中调用异步函数（见 zustand-persist-patterns.md）
- [ ] 不要在多个地方重复实现 hydration 等待逻辑，统一用 `AuthInit`
- [ ] 所有 API 请求必须走 `api.ts` 的 `request()` 函数，不要裸 `fetch()`（裸 fetch 会绕过自动刷新和 CSRF）
- [ ] 唯一例外：`/auth/refresh` 端点必须用裸 `fetch`（避免 401 死循环），参考 `silentRefresh` 实现

## 已知遗留风险

1. **refresh_token 未轮换**：当前每次刷新只签发新 access_token，refresh_token 本身不轮换。如果 refresh_token 泄露，攻击者可以持续刷新。后续应实现 refresh_token 轮换（每次刷新签发新 refresh_token 并使旧 token 失效）。
2. **软删除数据堆积**：会议软删除后无自动清理机制，长期运行会导致数据库膨胀。后续应添加定期清理策略。
3. **Agent state 硬编码**：normalize 层将 `agent.state` 硬编码为 `'idle'`，不反映真实运行时状态。后续需从 WebSocket 或后端获取真实状态。
