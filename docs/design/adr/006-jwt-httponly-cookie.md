# ADR-006: JWT 存储于 HttpOnly Cookie

| 字段 | 值 |
|------|-----|
| 编号 | ADR-006 |
| 状态 | Accepted |
| 日期 | 2026-07-19 |
| 影响范围 | 前后端认证流程、axios 请求拦截器、CORS 配置、登录/登出 API、CSRF 防护中间件、WebSocket 鉴权 |

## 背景

Conclave v0.1-v0.3 版本将 JWT（JSON Web Token）存储在浏览器 `localStorage` 中，前端在每次 HTTP 请求时通过 `Authorization: Bearer <token>` 头发送。该方案实现简单，但存在严重的安全隐患，在多租户场景下风险被进一步放大：

1. **XSS 窃取风险**：`localStorage` 可被同源下任意 JavaScript 代码访问。一旦前端存在 XSS 漏洞（无论是 Conclave 自身代码还是第三方依赖），攻击者可通过一行脚本 `fetch('/api/steal?token=' + localStorage.getItem('access_token'))` 将 Token 发送到外部服务器；
2. **多租户放大效应**：Conclave 支持团队协作，Team Admin 的 Token 被窃取意味着攻击者可以管理整个团队的成员、修改规则、查看所有会议记录和转录文本。企业级客户（使用 SSO/SAML 登录的组织）一旦发生 Token 泄露，影响范围覆盖整个组织；
3. **Token 生命周期过长**：为减少用户频繁登录，当前 access_token 有效期设为 7 天，refresh_token 30 天。Token 一旦被窃取，攻击者有充裕的时间窗口进行滥用；
4. **无法主动失效**：纯 JWT 方案无服务端状态，Token 在过期前无法主动吊销。虽然已有黑名单机制（Redis 存储 jti），但 XSS 窃取通常在数秒内完成，黑名单响应窗口有限；
5. **WebSocket 认证隐患**：WebSocket 连接建立时无法自定义 Header（浏览器原生 WebSocket API 限制），当前通过 URL query 参数传递 Token（`ws://host/ws?token=xxx`），Token 会出现在服务器日志、Nginx access log、浏览器历史记录中，存在额外泄露面。

我们需要重新设计 Token 存储方案，在不显著增加开发复杂度的前提下，将 XSS 攻击面降到最低。

## 决策

采用 **HttpOnly + Secure + SameSite=Strict Cookie** 存储 JWT，并使用 **Double-Submit Cookie** 模式防护 CSRF 攻击。

### Cookie 设计

认证成功后，服务端通过 `Set-Cookie` 响应头下发两个 Cookie：

```
Set-Cookie: access_token=<jwt>; HttpOnly; Secure; SameSite=Strict; Path=/; Max-Age=900
Set-Cookie: refresh_token=<jwt>; HttpOnly; Secure; SameSite=Strict; Path=/api/auth; Max-Age=2592000
Set-Cookie: csrf_token=<random>; Secure; SameSite=Strict; Path=/; Max-Age=2592000
```

关键属性说明：

- **HttpOnly**：禁止 JavaScript 访问 `access_token` 和 `refresh_token` Cookie，XSS 攻击无法读取 Token 值；
- **Secure**：仅在 HTTPS 连接下传输，防止中间人攻击截获（本地开发环境 `localhost` 可豁免）；
- **SameSite=Strict**：完全禁止跨站请求携带 Cookie，从根本上阻止 CSRF 攻击的基础条件；
- **Path 隔离**：`refresh_token` 仅在 `/api/auth` 路径下传输，减少泄露面；
- **短期 access_token**：access_token 有效期缩短至 15 分钟，refresh_token 30 天，即使 Cookie 被泄露（如通过浏览器漏洞），攻击窗口大幅缩小。

### CSRF 防护：Double-Submit Cookie 模式

`SameSite=Strict` 在现代浏览器（Chrome 80+、Firefox 69+、Safari 13+）中已能有效防护 CSRF，但为了纵深防御和兼容旧浏览器，额外部署 Double-Submit Cookie 模式：

1. 服务端下发 `csrf_token` Cookie（**无 HttpOnly**，前端 JS 可读），值为 32 字节随机值的十六进制编码；
2. 前端 axios 请求拦截器从 `document.cookie` 中读取 `csrf_token`，在每个非安全方法（POST/PUT/PATCH/DELETE）请求中携带 `X-CSRF-Token: <value>` Header；
3. 服务端 CSRF 中间件校验：请求 Header 中的 `X-CSRF-Token` 值必须与 Cookie 中的 `csrf_token` 值一致；
4. 安全方法（GET/HEAD/OPTIONS）不做 CSRF 校验。

工作原理：CSRF 攻击可以让浏览器自动携带 Cookie，但无法读取 Cookie 值（同源策略限制跨站 JS 读取目标站点 Cookie），因此无法在请求 Header 中放入正确的 CSRF Token。

### 前端改造

1. **axios 拦截器改造**：
   - 移除 `Authorization` Header 注入逻辑；
   - 请求拦截器中读取 `csrf_token` Cookie 并注入 `X-CSRF-Token` Header；
   - 响应拦截器处理 401 错误：当 access_token 过期时，自动调用 `/api/auth/refresh` 刷新 Token（浏览器自动携带 refresh_token Cookie），然后重试原请求；
2. **登录流程**：登录 API 不再返回 Token 字符串，而是通过 `Set-Cookie` 写入，前端只需处理登录成功/失败状态；
3. **Token 访问**：前端 JS 不再需要读取 access_token。如需获取当前用户信息，调用 `/api/auth/me` 接口；
4. **登出流程**：调用 `/api/auth/logout`，服务端清除两个 HttpOnly Cookie 和 csrf_token Cookie，并将 jti 加入黑名单。

### WebSocket 鉴权改造

WebSocket 连接不再通过 URL query 参数传递 Token，改为：

1. 建立 WebSocket 连接时，浏览器自动携带 Cookie（`access_token`）；
2. 服务端在握手阶段从 Cookie 中提取 JWT 并验证；
3. 连接建立后定期（每 10 分钟）检查 Token 有效性，access_token 快过期时通过 WS 消息通知前端触发刷新；
4. 前端在收到 401/4403 WS 关闭码时，先调用 refresh 接口再重连。

### CORS 配置

由于使用 Cookie 认证，CORS 配置必须收紧：

```python
# 不再支持 credentials: '*'，必须显式指定允许的前端 Origin
ALLOWED_ORIGINS = [
    "https://conclave.app",
    "https://app.conclave.app",
    "http://localhost:3000",  # 开发环境
]
CORS_SETTINGS = {
    "allow_origins": ALLOWED_ORIGINS,
    "allow_credentials": True,  # 必须开启，否则浏览器不发送 Cookie
    "allow_methods": ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    "allow_headers": ["Content-Type", "X-CSRF-Token"],
}
```

关键约束：`allow_origins` 禁止使用通配符 `*`，必须显式枚举。

## 选项对比

| 选项 | 优点 | 缺点 | 结论 |
|------|------|------|------|
| 选项1：localStorage + Authorization Header（v0.3 现状） | 实现最简单；前后端完全解耦；CORS 配置简单（无需 credentials）；移动端原生 App 易于集成 | XSS 可直接窃取 Token；多租户场景下泄露影响极大；Token 有效期内无法彻底阻止滥用；WebSocket 需通过 URL 参数传 Token，增加日志泄露面 | 否决，安全风险不可接受，特别是面向企业客户的 SSO 场景 |
| 选项2：HttpOnly Cookie + Double-Submit CSRF（选定） | XSS 无法读取 Token（HttpOnly 隔离）；SameSite=Strict 提供 CSRF 基础防护；Double-Submit 提供纵深防御；浏览器自动管理 Cookie 生命周期；WebSocket 握手时自动携带无需额外处理；access_token 可设短期（15 分钟），refresh_token 自动轮换 | 需要实现 CSRF 中间件；CORS 配置需收紧（不能用通配符）；前后端同域部署要求（或共享父域名）；移动端原生 App 需使用 Cookie 存储或额外提供 API Key 机制；本地 HTTP 开发环境需特殊处理 Secure 属性 | 选定，安全性显著提升，复杂度可控，符合 OWASP 推荐实践 |
| 选项3：内存存储 access_token + refresh_token 轮换 | access_token 仅存于 JS 变量中（页面刷新即丢失），XSS 仅能在页面存活期间访问；refresh_token 同样 HttpOnly Cookie | 实现复杂度高：页面刷新需要静默刷新流程；多标签页状态同步复杂（需 BroadcastChannel）；refresh_token 轮换需要检测复用（检测到重放攻击时全族吊销）；用户体验受影响（刷新页面短暂白屏）；仍然需要 CSRF 防护（refresh 接口） | 否决，复杂度远超收益。短期 access_token（15分钟）+ HttpOnly 已能将 XSS 时间窗口压缩到极小，内存存储带来的额外安全收益边际递减 |

## 后果

### 正面影响

1. **XSS 攻击面大幅缩小**：即使存在 XSS 漏洞，攻击者无法通过 JS 读取 HttpOnly Cookie 中的 Token，无法将 Token 外传；
2. **CSRF 可防可控**：SameSite=Strict 在主流浏览器完全阻止 CSRF，Double-Submit 为旧浏览器和极端场景提供兜底；
3. **WebSocket 安全性提升**：Token 不再出现在 URL 和日志中；
4. **Token 自动刷新体验更好**：前端无需手动管理 Token 过期逻辑，axios 拦截器统一处理刷新，用户无感知；
5. **符合安全合规要求**：SOC 2、ISO 27001 等安全审计对认证存储有明确要求，HttpOnly Cookie 是行业标准实践；
6. **支持服务端主动吊销**：refresh_token 轮换机制下，服务端可在检测到异常时立即吊销，且短期 access_token 意味着即使泄露也很快失效。

### 负面影响

1. **CORS 配置复杂化**：必须显式配置允许的 Origin 列表，新增部署域名需要更新配置。开发环境和生产环境的 Origin 管理需要统一的配置机制；
2. **跨域部署限制**：前后端如果部署在不同父域名下（如前端 `web.com`，后端 `api.io`），SameSite=Strict 会导致跨站 Cookie 不发送。需要部署在同域名下（如 `app.conclave.app` + `api.conclave.app`）或使用 SameSite=None（会降低 CSRF 防护能力）；
3. **移动端适配成本**：React Native / 原生 App 的网络栈对 Cookie 支持程度不一，需要额外提供 OAuth2 Password Grant 或 API Key 认证方式作为移动端专用通道；
4. **本地开发调整**：本地 HTTP（非 HTTPS）环境下 Secure Cookie 不会被浏览器保存，需要开发环境特殊处理（如 `secure: False` when `DEBUG=True`）；
5. **CSRF Token 管理**：前端需要在每个状态变更请求中携带 CSRF Token，axios 拦截器统一处理后对业务代码透明，但 WebSocket 和 SSE 长连接需单独设计鉴权续期机制。

### 缓解措施

- 配置管理：通过环境变量 `CORS_ALLOWED_ORIGINS` 配置允许的 Origin 列表，支持逗号分隔多个域名，部署时通过 Kubernetes ConfigMap 或 .env 文件注入；
- 域名规划：生产环境前端使用 `app.conclave.app`，后端使用 `api.conclave.app`，共享父域名 `conclave.app`，Cookie Domain 设为 `.conclave.app` 即可跨子域使用；
- 移动端认证：保留 `/api/auth/mobile/token` 接口（OAuth2 Resource Owner Password Credentials 或基于 Refresh Token 的 JSON 响应），仅限移动端 App 使用，通过 App 自身的安全存储（iOS Keychain / Android Keystore）保存 Token，该接口有单独的 Rate Limiting 策略；
- 开发环境：`DEBUG=True` 时自动关闭 Secure 标志并添加 `localhost` 到允许的 Origin 列表；
- XSS 防护：HttpOnly Cookie 降低了 XSS 的影响，但并非不做 XSS 防护。仍需保持 CSP 头、输入校验、输出转义、依赖库安全审计等基础 XSS 防护措施；
- CSRF 中间件白名单：Webhook 回调接口（`/api/webhooks/*`）、服务器间通信接口（内部 mTLS）可通过白名单跳过 CSRF 校验，因为这些接口不是面向浏览器的。

### Token 刷新流程时序

```
1. 前端发起业务请求，浏览器自动携带 access_token Cookie
2. 若 access_token 有效，正常返回响应
3. 若 access_token 过期（401 + code="token_expired"）：
   a. axios 响应拦截器捕获 401
   b. 自动发起 POST /api/auth/refresh（浏览器自动携带 refresh_token Cookie + csrf_token Header）
   c. 服务端验证 refresh_token，生成新 access_token 并 Set-Cookie
   d. 拦截器重试原始请求
   e. 若 refresh_token 也过期，跳转登录页
4. 为防止并发请求触发多次刷新，使用"刷新锁"（Promise 单例），第一个 401 触发刷新，其余请求等待刷新完成后重试
```

## 相关

- ADR-003：插件三层分级——auth 插件是 CORE 层插件，认证机制的变更影响所有依赖身份信息的插件
- ADR-001：插件化架构——CSRF 中间件作为核心 HTTP 中间件注册，所有插件路由自动受保护
- OWASP CSRF Prevention Cheat Sheet：Double-Submit Cookie 模式
- OWASP XSS Prevention Cheat Sheet：HttpOnly Cookie 防护 XSS Token 窃取
- RFC 6749：OAuth 2.0 Bearer Token 使用规范（Cookie 是 Bearer Token 的一种传输方式）
