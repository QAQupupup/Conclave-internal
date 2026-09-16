# Conclave 安全加固 + 前端/测试审查修复总结

**日期**: 2026-07-18
**分支**: refactor/v3-manager-agent-runtime

## 一、本次修复范围

### 后端安全修复（C/H/M/L 级）

| 编号 | 问题 | 修复 | 文件 |
|------|------|------|------|
| SQLAlchemy | 错误导入/health重复检查 | 修正导入，移除重复路由 | `backend/app/main.py` |
| C-03 | WebSocket 认证绕过（测试模式双条件不满足） | 修复中间件和 ws router 双重条件判定 | `middleware.py`, `ws.py`, `conftest.py` |
| C-04 | API Key 通过 URL 查询参数传递 | HTTP 中间件不再读取 `?token=`，仅 WebSocket 保留 | `middleware.py` |
| H-02 | WS 缺少会议/系统级别权限校验 | `/ws/meetings/{id}` 校验访问权限，`/ws/system` 仅 admin | `routers/ws.py` |
| H-03 | safe_fetch 使用同步 httpx 阻塞事件循环 | 改为 `httpx.AsyncClient`，模块级连接池复用，手动跟随重定向每跳校验 SSRF | `network_security.py` |
| H-04 | PBKDF2 迭代次数低于 OWASP 推荐 | 从 260,000 提升至 600,000，旧哈希登录时透明升级 | `auth.py` |
| H-05 | JWT 缺少 iss/aud 声明 | 新增 `iss`/`aud`/`jti` 声明，验证时严格校验，防跨环境 token 重用 | `auth.py` |
| H-06 | deploy_service 原地修改 Dockerfile | 创建临时副本构建后删除，修复硬编码路径为 `workspace_root`，正则更严格 | `sandbox.py` |
| H-07 | workspace/exec 沙箱逃逸风险 | Docker 容器加固：drop caps/no-new-privs/pids-limit/ipc/uts 私有/tmpfs noexec，命令黑名单扩展 | `sandbox.py` |
| H-08 | 速率限制数据结构内存永久增长 | 新增后台定期清理（60s），LRU 淘汰（上限 10000 IP），lifespan 管理 | `middleware.py` |
| M-04 | WS 入站限流缺失 | 新增 `WsInboundRateLimiter`（滑动窗口），system_ws 更严格 | `routers/ws.py` |
| M-08 | SSRF 多跳重定向 | safe_fetch 手动跟随重定向（最多 5 跳），每跳协议/DNS/IP/域名白名单校验 | `network_security.py` |
| 中/低危 | 路径匹配绕过/OPTIONS 预检/裸 create_task/sh-c 注入等 | 统一使用 `create_supervised_task`，规范化路径匹配，修复 Windows chmod | 多处 |

**H-06 澄清**: 修复的是 **LLM 生成的可部署服务的 Dockerfile**（工作区中用户服务的），不是 Conclave 自身的 Dockerfile。

**H-07 最终方案**: 核心防沙箱逃逸而非仅防网络。通过 Docker 安全参数（drop all capabilities, no-new-privileges, --pids-limit, --ipc=private, --uts=private, tmpfs noexec,nosuid,nodev, --privileged=false）+ 命令黑名单（Docker socket/DinD/kubectl/内核模块/命名空间操作）双重防护。

**httpx 是否最佳选择**: 是。原生 async/await、连接池复用、同步/异步双模式、类型注解完善、活跃维护，是 FastAPI 生态默认推荐。唯一注意点是复用 AsyncClient 实例（已实现模块级单例）。

**JWT iss/aud 解释**: `iss`(签发者) + `aud`(受众) 声明确保 token 只能在预期环境使用。例如 staging 和 prod 即使使用相同 JWT_SECRET，staging 签发的 token 无法在 prod 使用（aud 不匹配），防止跨环境 token 重用。`jti` 提供唯一标识便于撤销。

### 前端审查修复（新增发现的严重问题）

| 问题 | 严重度 | 修复 |
|------|--------|------|
| **WS 重连逻辑失效**（`connect()` 先设 destroyed=false 再调用 disconnect() 设回 true） | 严重 | 修复执行顺序：先清理旧连接，再设标志位，提取 `createConnection()` 方法，新增 `intentionalClose` 标志 |
| WS 无客户端心跳检测"半开连接" | 中 | 添加客户端心跳：每 25s 发 ping，60s 无消息主动 close 触发重连 |
| WS onerror 不主动 close 导致连接挂起 | 中 | 会议 WS onerror 主动 close 以触发重连 |
| WS 4403/4429 特殊关闭码未处理 | 中 | 4403 停止重连，4429 延迟 5s 重试，新增 `onRateLimited` 回调 |
| 登出未清理 WS/会议状态/日志 | 中 | logout 时断开 WS、重置会议状态、清空日志；401 拦截器同样处理 |
| Token 直接读 localStorage 而非 getToken() | 低 | 统一使用 `getToken()` |
| Login redirect 参数开放重定向风险 | 中 | 验证 redirect 必须以 `/` 开头且非 `//` 开头 |
| sanitizeRich 仅过滤 javascript: 未过滤 data:/vbscript: 等 | 中 | href 属性白名单：仅允许 http/https/mailto/tel/#/相对路径 |

### 测试体系修复

| 问题 | 修复 |
|------|------|
| `conftest.py` 缺少 `APP_ENV=test` 导致测试模式认证绕过未生效 | 添加 `os.environ.setdefault("APP_ENV", "test")` |
| `docker-compose.test.yml` 同样缺少 `APP_ENV=test` | 添加环境变量 |
| `test_net_auth_flow.py` 中 8 个同步测试方法调用 async 函数（假阳性） | 全部改为 `async def` + `await` |
| `test_middleware_security.py` 的 `test_token_via_query_param` 与 C-04 修复后行为矛盾 | 改为 `test_token_via_query_param_rejected`，断言返回 401 |
| CI 中 `frontend-tests` job 引用不存在的 `npm run test` 脚本 | 添加 vitest 配置 + 基础测试集 |
| 前端完全没有测试 | 添加 vitest + jsdom + testing-library，编写 20 个测试用例（format.ts 15 个 + ws.ts 5 个） |

## 二、新增/修改文件清单

### 后端修改
- `backend/app/auth.py` - PBKDF2 提升至 600k + JWT iss/aud/jti
- `backend/app/main.py` - 修正导入/health/后台任务监督
- `backend/app/middleware.py` - HTTP 禁用 query token + 速率限制 LRU 清理
- `backend/app/network_security.py` - async httpx + 多跳重定向 SSRF 校验
- `backend/app/pricing_fetcher.py` - create_supervised_task
- `backend/app/routers/meetings.py` - 后台任务异常处理
- `backend/app/routers/ws.py` - 权限校验 + 入站限流
- `backend/app/sandbox.py` - Dockerfile 安全修改 + 容器逃逸加固
- `backend/app/utils/tasks.py` - 新增后台任务监督工具
- `backend/conftest.py` - 添加 APP_ENV=test
- `backend/tests/test_net_auth_flow.py` - 修复 async 假阳性测试
- `backend/tests/test_middleware_security.py` - 更新 query token 测试为拒绝
- `docker-compose.test.yml` - 添加 APP_ENV=test

### 前端修改
- `frontend/src/lib/ws.ts` - **重写**：修复 destroyed bug、添加心跳、正确处理关闭码
- `frontend/src/state/AppContext.tsx` - logout/401 清理 WS/状态、统一 getToken()
- `frontend/src/views/Login.tsx` - redirect 开放重定向防护
- `frontend/src/lib/format.ts` - sanitizeRich 协议白名单
- `frontend/package.json` - 添加 vitest/jsdom/testing-library 依赖和 test 脚本
- `frontend/vite.config.ts` - 添加 vitest 配置（jsdom 环境）
- `frontend/tsconfig.json` - 添加 vitest/testing-library 类型
- `frontend/src/test/setup.ts` - 新增测试 setup
- `frontend/src/test/format.test.ts` - 新增 sanitize/escHtml/format 测试（15 个）
- `frontend/src/test/ws.test.ts` - 新增 WS 客户端测试（5 个）

### 文档
- `docs/conclave-full-code-review-2026-07-18.md` - 完整代码审查报告

## 三、前端现存问题（未在本次修复，记录后续）

### 中优先级
1. **单 Context 过大导致全局重渲染**：AppContext 包含 30+ 属性，elapsed 每秒更新导致所有消费组件重渲染。建议拆分 AuthContext/MeetingContext/UIContext，或用 Zustand 支持选择订阅。
2. **Token 存储在 localStorage**：XSS 一旦发生即可窃取。长期建议 HttpOnly Cookie + refresh token。
3. **API 层无超时/重试/取消机制**：建议添加 AbortController 超时（30s）、GET 请求幂等重试、组件卸载自动取消。
4. **apiControlMeeting 参数名 `signal` 与 AbortSignal 冲突**：建议重命名为 `action`。
5. **借调请求的批准/拒绝按钮是空壳**：仅写日志，未发 API/WS 消息。
6. **CSP 允许 'unsafe-inline'**：nginx.conf 中 script-src/style-src 可进一步收紧。

### 低优先级
1. 消息操作按钮（复制/聚焦/引用）未实现
2. 使用 alert()/confirm() 阻塞式对话框
3. 多个 setTimeout 未在卸载时清理（影响小）
4. mock 数据初始状态导致闪烁
5. elapsed 计时器始终运行（即使不在会议中）
6. 5xx 错误信息直接暴露给用户
7. 404 页面缺失（catch-all 直接重定向到首页）

## 四、测试覆盖缺口（需后续补充）

### 后端缺失测试
1. **JWT 登录流程**：`/auth/login`、`/auth/me` 无任何测试
2. **安全边界测试**：未认证返回 401、角色权限隔离（admin vs user）、用户 A 无法访问用户 B 的会议
3. **SSRF 防护**：`network_security.py` 0 测试（内网 IP、DNS rebinding、重定向绕过）
4. **路径穿越**：`_resolve_path()` 0 测试（`../`、绝对路径、URL 编码绕过）
5. **WebSocket 权限**：未认证 4401、普通用户访问他人会议 4403、system WS admin 限制
6. **工作区文件 API**：`/workspace/files`、`/workspace/exec` 路由无集成测试
7. **API 限流/IP 封禁**：`test_middleware_security.py` 使用独立最小化 app，未经过真实 middleware 栈
8. **异常路径覆盖**：数据库连接失败、Redis 不可用、LLM 超时/无效 JSON 等降级场景

### 前端缺失测试
1. **认证流程**：RequireAuth 守卫、SessionExpiredModal、login/logout 完整流程
2. **API 层**：401 拦截、错误处理、token 注入
3. **组件测试**：Meeting、Report、Board 等核心视图
4. **状态管理**：AppContext 状态转换
5. **端到端测试**：Playwright/Cypress 覆盖登录→创建会议→会议运行全流程

### 测试质量改进
1. 引入数据库事务回滚机制（每个测试在事务中运行，结束后回滚），替代 TRUNCATE
2. 提供认证 fixture（自动携带有效 JWT），而非全局禁用认证
3. 统一 client fixture 和 reset_state fixture（移除 test_smoke.py/test_event_replay.py 中的重复定义）
4. 测试中硬编码 meeting_id 改为 uuid，避免并行执行冲突
5. 修复 `test_sandbox_security.py` 等测试中可能的 mock 泄漏

## 五、验证结果

- **后端**：149 个 Python 文件全部通过 AST 语法检查
- **前端**：TypeScript 严格编译通过（`tsc --noEmit`），20 个单元测试全部通过
- **前端测试**：2 files, 20 tests passed（format 15 + ws 5）

## 六、后续开发规范建议

1. **认证/安全相关改动必须加测试**：任何修改 auth.py、middleware.py、ws.py、sandbox.py、network_security.py 的 PR 必须包含对应的安全边界测试
2. **异步代码规范**：禁止裸 `asyncio.create_task()`，统一使用 `create_supervised_task()` 并附 done_callback
3. **HTTP 客户端规范**：统一使用 `network_security.py` 中的 `safe_fetch`/`AsyncClient`，禁止直接使用 `requests` 或同步 `httpx`
4. **前端 WS 规范**：所有新 WS 消息类型必须在 `handleMessage` 的 switch 中添加 case，4401/4403/4429 必须正确处理
5. **密码哈希**：使用 `hash_password.verify_and_update()` 而非 `verify_password()`，确保旧哈希自动升级
6. **Docker 沙箱**：新增命令必须经过 `_validate_command()` 校验，容器启动必须包含安全参数
