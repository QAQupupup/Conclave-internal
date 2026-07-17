# Conclave 全栈代码审查报告

**审查日期**: 2026-07-18
**审查范围**: 前端（`frontend/`）+ 后端（`backend/`）全量代码
**项目概述**: Conclave 是一个会议型多智能体决策系统，后端采用 Python 3.12 + FastAPI + asyncio，前端采用 React 19 + TypeScript + Vite，整体 UI 风格参考 Gen Speak（Notion 风极简设计）。

---

## 一、总体评价

### 后端
- **架构清晰**: 分层明确（routers/dao/orchestrator/agents/tools），V3 重构引入的 Manager + AgentRuntime 统一了组件交互
- **安全意识较强**: SQL 注入防护到位（全参数化查询），SSRF 防护模块完整，Docker 沙箱有网络分级/非 root/cap-drop 等加固，密码哈希使用 PBKDF2 + 随机 salt + 时序安全比较
- **可观测性完善**: LogBus 结构化日志、MetricsStore 环形缓冲、CostTracker 成本追踪、全链路 trace_id
- **资源管理良好**: 崩溃恢复、TTL 淘汰、会议删除级联清理、lifespan 统一 shutdown 等机制设计完整
- **主要问题**: 存在若干安全配置缺陷（默认弱密码、WS 认证绕过、API Key 日志泄露）、同步阻塞调用、异步任务异常无监督、部分功能路径为占位实现

### 前端
- **UI 完成度高**: Gen Speak 风格的极简设计还原度好，⌘K 命令面板、可折叠阶段、富文本语义标记、报告演示模式、深色/浅色主题等功能完整
- **工程基础扎实**: TypeScript 严格模式已开启，路由守卫 + 401 拦截去重，WebSocket 指数退避重连 + 心跳 + 认证过期处理专业
- **XSS 防护到位**: `sanitizeRich()` DOM 白名单清洗 + `escHtml()` 转义 + 语义标记后处理
- **交互细节打磨**: 消息悬停操作、复制代码块反馈、报告键盘翻页 + TOC 跳转、打印样式、响应式断点
- **主要问题**: 存在多个功能阻断级 bug（MeetingToolbar 不显示、借调按钮无 API 调用、操作按钮空实现）、Context 每秒全树重渲染性能问题、大量 mock 硬编码数据、`any` 类型滥用、可访问性缺失

---

## 二、后端问题清单

### Critical（严重，需立即修复）

#### C-01: 错误导入 `sqlalchemy.testing.pickleable.User`
- **位置**: `backend/app/main.py:10`
- **描述**: `from sqlalchemy.testing.pickleable import User` 从 SQLAlchemy 内部测试模块导入了一个从未使用的测试类
- **影响**: 精简安装环境可能导致 ImportError 启动崩溃；若未来误用会引发严重逻辑错误
- **修复**: 删除第 10 行

#### C-02: 默认管理员密码硬编码为弱密码 `admin123`
- **位置**: `backend/app/auth.py:36`
- **描述**: `DEFAULT_ADMIN_PASSWORD = os.environ.get("CONCLAVE_ADMIN_PASSWORD", "admin123")`，未配置环境变量时自动创建 `admin/admin123`
- **影响**: 生产环境若忘记配置，攻击者可直接登录获得完全控制权（执行任意代码、删除所有数据）
- **修复**:
  1. 生产模式未设置密码时拒绝启动或生成随机密码打印到日志（仅一次）
  2. 首次登录强制修改密码
  3. 启动日志添加醒目安全警告

#### C-03: WebSocket 认证绕过（测试模式检查不一致）
- **位置**: `backend/app/routers/ws.py:41` vs `backend/app/middleware.py:177`
- **描述**: HTTP 中间件要求同时满足 `APP_ENV=test` 和 `CONCLAVE_TEST_DISABLE_AUTH=1` 才跳过认证；但 WebSocket 的 `_check_ws_token()` 仅检查后者
- **影响**: 若生产环境误设 `CONCLAVE_TEST_DISABLE_AUTH=1`（未设 `APP_ENV=test`），HTTP 接口仍有认证但 WS 完全开放，攻击者可订阅所有会议数据并发送控制信号
- **修复**: 将 ws.py 第 41 行改为与 HTTP 中间件一致的双重条件检查

#### C-04: API Key 通过 URL 查询参数传递（日志泄露风险）
- **位置**: `backend/app/routers/meetings.py:1218-1262`
- **描述**: `/meetings/llm/models` 和 `/meetings/llm/balance` 两个 GET 端点接受 `api_key` 作为 query parameter
- **影响**: API Key 会出现在访问日志、浏览器历史、Referer 头、代理服务器日志中
- **修复**: 改为 POST 方法，API Key 放入请求体或 `Authorization: Bearer` 头

---

### High（高危，优先修复）

#### H-01: 默认数据库连接字符串含硬编码弱密码
- **位置**: `backend/app/config.py:79-82`
- **描述**: `DATABASE_URL` 默认值为 `postgresql+asyncpg://conclave:conclave_dev@localhost:5432/conclave`
- **影响**: 生产环境若未覆盖且数据库暴露到网络，可被直接爆破
- **修复**: 生产模式检测到默认密码时打印强烈警告；无 `DATABASE_URL` 时回退到 SQLite

#### H-02: WebSocket control.signal 无会议级权限校验
- **位置**: `backend/app/routers/ws.py:232-292`
- **描述**: 任何认证用户连接到 `/ws/meetings/{meeting_id}` 即可发送 pause/resume/abort/borrow 审批等控制信号，无校验该用户是否有权限操作该会议
- **影响**: 多用户场景下越权操作他人会议
- **修复**: WS 连接建立时校验 JWT 用户与 meeting 的归属关系；处理 control.signal 时二次鉴权

#### H-03: `safe_fetch` 使用同步 httpx 客户端阻塞事件循环
- **位置**: `backend/app/network_security.py:136`
- **描述**: `safe_fetch()` 使用 `httpx.Client`（同步）而非 `httpx.AsyncClient`
- **影响**: 每次调用阻塞整个事件循环，高并发下可能导致服务雪崩
- **修复**: 改为 `async def` + `httpx.AsyncClient`，逐跳跟随重定向并对每跳做 SSRF 校验

#### H-04: PBKDF2 迭代次数低于 OWASP 推荐值
- **位置**: `backend/app/auth.py:31`
- **描述**: `PBKDF2_ITERATIONS = 260_000`，OWASP 2023+ 推荐 SHA-256 最低 600,000 次
- **影响**: 数据库泄露时暴力破解成本低于行业标准
- **修复**: 提升至 600,000+；考虑迁移到 Argon2id；添加版本标记以便后续升级

#### H-05: JWT 缺少 iss/aud 声明，无法抵御跨环境 token 重用
- **位置**: `backend/app/auth.py:111-123`
- **描述**: JWT 仅包含 `sub/role/uid/iat/exp`，无 `iss`（签发者）、`aud`（受众）、`jti`（token ID）
- **影响**: 同一密钥签发的 token 在 staging/prod 间可互用；无法实现 token 黑名单/撤销
- **修复**: 添加 `iss` 和 `aud` 声明；增加 `jti` 支持 token 撤销

#### H-06: deploy_service 自动修改用户 Dockerfile
- **位置**: `backend/app/sandbox.py:916-956`
- **描述**: 硬编码 `/workspace/` 路径；自动读取并修改 LLM 生成的 Dockerfile（替换 FROM 镜像源、追加 COPY 指令）
- **影响**: 本地开发路径错误；正则替换边界情况可能引入意外变更；自动追加的 COPY 可能将敏感文件打入镜像
- **修复**: 使用 `settings.workspace_root` 构建路径；修改前备份原文件；对生成的 Dockerfile 做安全审计（禁止 ADD 远程 URL、禁止 --privileged 等）

#### H-07: `/workspace/exec` 白名单包含高风险命令
- **位置**: `backend/app/routers/workspace.py:210-245` + `backend/app/sandbox.py:99-107`
- **描述**: 白名单包含 `npm, yarn, node, go, rustc, cargo, gcc, g++, git, make, cmake, pip` 等，`pip install` 可安装任意包，`npm install` 自动执行 postinstall 脚本
- **影响**: L2/L3 网络模式或宿主机降级模式下可执行任意代码
- **修复**:
  1. `/workspace/exec` 仅允许 admin 角色调用
  2. `pip install --no-scripts`、`npm install --ignore-scripts`
  3. 默认禁止 L3 网络模式

#### H-08: 速率限制数据结构内存永久增长风险
- **位置**: `backend/app/middleware.py:91-93`
- **描述**: `_request_log`、`_fail_log`、`_blocked_ips` 字典以 IP 为 key，分布式 DDoS 下 key 集合无限增长
- **影响**: 大量不同 IP 攻击时内存持续增长导致 OOM
- **修复**: 增加定期清理任务删除空列表 key 和过期条目；或使用 LRU 缓存限制最大 IP 追踪数

---

### Medium（中危）

| 编号 | 问题 | 位置 |
|------|------|------|
| M-01 | 多处未使用导入（`JSONResponse`、重复 `datetime` 导入等） | `main.py:11`、`meetings.py:8` |
| M-02 | 宿主机降级执行模式（`_run_on_host`）代码路径存在，误设环境变量后所有沙箱保护失效 | `sandbox.py:478-552` |
| M-03 | 所有路由端点缺少角色权限分级（admin/user 角色定义了但未使用） | 所有 routers 文件 |
| M-04 | WebSocket 入站消息无速率限制（仅出站有限制） | `routers/ws.py` |
| M-05 | `_is_public()` 路径前缀匹配可被编码/规范化绕过 | `middleware.py:151-156` |
| M-06 | `list_meetings` 查询存在 N+1 问题（每个会议单独查标签） | `dao/meeting_dao.py:146-157` |
| M-07 | 启动时不清理 workspace 孤立临时文件，长期运行后占用磁盘 | `config.py:99-102` |
| M-08 | `safe_fetch` 重定向验证不完整（多跳 SSRF 风险） | `network_security.py:136-146` |
| M-09 | `run_command` 通过 `sh -c` 执行，存在 shell 注入绕过可能（`${IFS}` 等） | `sandbox.py:442` |
| M-10 | `asyncio.create_task` 无全局异常处理，后台任务静默失败 | `main.py:82/88/94`、`meetings.py:431` |
| M-11 | `/debug/auth-info` 端点在生产环境暴露认证配置信息（限速阈值、用户名等） | `main.py:261-280` |
| M-12 | 日志中记录完整用户输入（topic、介入消息、执行命令），可能含敏感数据 | `meetings.py:107-114/424`、`workspace.py:221-224` |
| M-13 | `deploy_service` 多处硬编码 `/workspace/` 容器路径，与配置项不一致 | `sandbox.py:916/930/940/959/983/1012` |

---

### Low（低危）

| 编号 | 问题 | 位置 |
|------|------|------|
| L-01 | health 检查中 PostgreSQL 检测重复执行两次 | `main.py:178-196` |
| L-02 | `get_meeting_model` 使用 `__import__()` 动态导入不规范 | `meetings.py:1346` |
| L-03 | JWT secret 文件 `os.chmod(path, 0o600)` 在 Windows 上无效 | `auth.py:58`、`middleware.py:53` |
| L-04 | `_check_port_healthy` 使用同步 `urllib.request` 阻塞事件循环 | `sandbox.py:860-877` |
| L-05 | 路径参数缺少格式校验（如 `meeting_id` 应匹配 `mtg-[0-9a-f]{12}`） | 所有 routers |
| L-06 | `_persist()` 每条消息单独 commit，大批量消息时性能差 | `runner.py:479-480` |
| L-07 | `_run_on_host` 临时文件创建存在 TOCTOU 竞态条件（host fallback 模式） | `sandbox.py:498-501` |

---

## 三、前端问题清单

### P0 严重问题（功能阻断/体验极差，需立即修复）

#### F-C01: MeetingToolbar 完全不显示
- **位置**: `frontend/src/components/MeetingToolbar.tsx` + `frontend/src/styles/global.css:476-477`
- **描述**: CSS 中 `.meeting-toolbar{display:none}`，只有 `.meeting-toolbar.show{display:flex}`；但 App.tsx 通过条件渲染 `{isMeeting && <MeetingToolbar />}` 控制，组件挂载时没有 `show` class
- **影响**: **会议页面右侧的阶段指示器、暂停/介入/终止按钮完全不显示**，用户无法控制会议
- **修复**: 去掉 CSS 中 `display:none`/`.show` 机制（已通过条件渲染控制可见性），或在根元素添加 `show` class

#### F-C02: 借调请求批准/拒绝按钮是空实现
- **位置**: `frontend/src/views/Meeting.tsx:140-141`
- **描述**: "批准"和"拒绝"按钮 `onClick` 仅调用 `appendLog()`，没有发送 API 请求，`borrowRequest` 状态也未清空
- **影响**: 用户点击后无实际效果，借调弹窗不会消失，后端收不到决策
- **修复**: 补充 API 调用，成功后设置 `meeting.borrowRequest = null`

#### F-C03: 消息操作按钮（复制/聚焦/引用）是空实现
- **位置**: `frontend/src/views/Meeting.tsx:185-187`
- **描述**: 悬停显示的三个按钮只有 `e.stopPropagation()`，无实际功能
- **影响**: 点击无反馈，属于"死按钮"
- **修复**:
  - 复制：`navigator.clipboard.writeText()` + toast 反馈
  - 聚焦：滚动到消息位置 + 临时高亮
  - 引用：将消息内容填入介入面板 textarea 并自动打开

#### F-C04: TraceTag 和附件下载使用 `alert()` 占位
- **位置**: `frontend/src/views/Report.tsx:41`、`Report.tsx:362`
- **描述**: 溯源标签点击弹 `alert('跳转到来源: ' + trace)`，附件下载弹 `alert('下载 ' + att.filename)`
- **影响**: 功能不可用，alert 弹窗严重破坏 Gen Speak 风格的精致体验
- **修复**: TraceTag 跳转到对应 claim 消息位置；附件调用真实下载 API 或 Blob 下载

#### F-C05: 使用浏览器原生 `confirm()` 终止会议
- **位置**: `frontend/src/state/AppContext.tsx:329`
- **描述**: `abortMeeting` 使用 `window.confirm()` 阻塞式原生弹窗
- **影响**: 视觉割裂感极强，与极简 UI 风格完全不协调
- **修复**: 实现自定义 Modal 组件，与整体 UI 风格统一

#### F-C06: 系统 WS 未处理 4401 认证过期，可能无限重连风暴
- **位置**: `frontend/src/lib/ws.ts` `connectSystemWs`
- **描述**: 会议 WS 处理了 4401（停止重连+跳转登录），但系统 WS 没有
- **影响**: 登录过期后系统 WS 后台无限重连，控制台持续报错浪费资源
- **修复**: 在系统 WS `onclose` 中增加 4401 处理，停止重连并触发认证过期回调

---

### P1 重要问题（影响性能/体验/可维护性）

#### F-H01: AppContext 中 meeting 对象每秒触发全组件树重渲染
- **位置**: `frontend/src/state/AppContext.tsx:379-394`
- **描述**: `meeting` 对象每秒被 `setMeeting` 更新（计时器更新 `elapsed`），导致整个 context value 重建，所有 `useApp()` 消费者每秒重渲染
- **影响**: 长时间开会后页面卡顿，Topbar/NavRail/CommandPalette 等无关组件也被迫重渲染
- **修复**:
  - 将 `elapsed` 从全局 meeting 中拆出，在 Meeting 视图内部用局部 state 维护
  - 或基于 `started_at` 时间戳计算实时 elapsed，不需要每秒 setState 整个 meeting
  - 拆分 Context 为更细粒度

#### F-H02: 会议计时器前端本地累加，与服务端时间偏差
- **位置**: `frontend/src/state/AppContext.tsx:372-377`
- **描述**: 本地 `setInterval` 每秒 `elapsed+1`，页面后台/最小化时 setInterval 被节流；初始 elapsed 硬编码为 `32*60+14`（演示值）；刷新后重置
- **影响**: 刷新页面、切换标签、打开历史会议后显示时间不准确
- **修复**: 从 API/snapshot 读取 `started_at` 时间戳，前端基于 `Date.now() - started_at` 计算

#### F-H03: CommandPalette 快捷键标签与实际实现不一致
- **位置**: `frontend/src/data/mock.ts:458-460`
- **描述**: "切换深色模式"显示 `⌘D`、"打开日志面板"显示 `⌘L`、"新建会议"显示 `⌘N`，但均未注册全局快捷键；`⌘N` 还会与浏览器"新建窗口"冲突
- **影响**: 用户按快捷键无反应，与预期不符
- **修复**: 补充快捷键实现；避免使用浏览器保留快捷键；或移除未实现的快捷键标签

#### F-H04: openMeeting 重复连接 WS 并清空消息
- **位置**: `frontend/src/state/AppContext.tsx:290-311`
- **描述**: Landing 页 `startMeeting` 后 navigate 到 `/meeting/${id}`，Meeting 视图 `useEffect([id])` 检测到变化又调用 `openMeeting(id)`，执行 `setMeeting(m => ({...m, messages: []}))` 清空已收到的消息，然后重复连接 WS
- **影响**: 启动会议后消息短暂清空/重复连接，可能丢失早期消息
- **修复**: `openMeeting` 中判断若 `id === meeting.currentMeetingId` 且 WS 已连接则直接返回

#### F-H05: 大量使用 `any` 类型，类型安全形同虚设
- **位置**: 全局
- **描述**: `MeetingState.messages/conflicts/claims/confidence/borrowRequest` 都是 `any[]`/`any`；WS payload 全是 `any`；多处组件内使用 `(m: any)`
- **影响**: 后端字段变更时前端无编译期报错，运行时可能出现字段访问错误
- **修复**: 定义完整的接口类型（MeetingMessage、Meeting、WsXxxEvent 等），消除 `any`

#### F-H06: ContextPanel 中的数据全是硬编码 mock
- **位置**: `frontend/src/components/ContextPanel.tsx:13-17`
- **描述**: EVIDENCE、TOKEN_STATS、ROLES 发言状态全是硬编码演示数据
- **影响**: 用户打开侧边面板看到假数据，与实际会议不符，产生误导
- **修复**: 从 meeting state 读取真实数据；未加载时显示 skeleton 或"暂无数据"

#### F-H07: 分页按钮无禁用状态样式
- **位置**: `frontend/src/views/Board.tsx:133-151`、`frontend/src/views/Models.tsx`
- **描述**: 第一页/最后一页点击箭头无反应，但无 disabled 样式、无 `disabled` 属性、鼠标仍是 pointer
- **影响**: 用户感觉是 bug
- **修复**: 添加 `disabled` class 和 `aria-disabled`，降低透明度、改变 cursor

#### F-H08: Settings 页偏好设置只读展示，无法编辑
- **位置**: `frontend/src/views/Settings.tsx:243-248`
- **描述**: `handlePrefChange` 已定义但未被任何控件调用，prefs 只做只读展示
- **影响**: 用户看到偏好列表但无法修改
- **修复**: 根据值类型渲染对应控件（boolean→switch，string→select/input）

#### F-H09: 缺少 Error Boundary 错误边界
- **位置**: 全局
- **描述**: 没有实现 React Error Boundary，任何组件抛出未捕获错误都会导致整个白屏
- **影响**: 生产环境一个小组件崩溃导致整个应用不可用
- **修复**: 实现 ErrorBoundary class 组件，包裹 AppProvider 外层和懒加载边界，展示友好降级 UI

#### F-H10: 缺少 Toast/Notification 系统
- **位置**: 全局
- **描述**: 操作反馈（介入已发送、API Key 已保存等）只能通过日志面板查看，普通用户不会打开日志面板
- **影响**: 成功/失败操作无即时视觉反馈
- **修复**: 实现轻量 Toast 组件（4 秒自动消失，success/error/warning/info）

---

### P2 一般问题（代码质量/体验细节）

| 编号 | 问题 | 位置 |
|------|------|------|
| F-M01 | `silent` 选项在 api() 中声明但未使用 | `lib/api.ts:17` |
| F-M02 | 真实会议无消息时回退显示 MESSAGES mock 数据，用户困惑 | `views/Meeting.tsx:51` |
| F-M03 | 多处使用 `eslint-disable-next-line react-hooks/exhaustive-deps` 抑制警告，部分可能导致闭包过期值 bug | 多处 |
| F-M04 | Topbar 用户菜单 `position:fixed` 无正确定位参照物，菜单位置错误 | `components/Topbar.tsx:62` + CSS:331 |
| F-M05 | `appendLog` LogLevel 大小写混用（`'warning'` vs `'WARN'`） | `state/AppContext.tsx:10` |
| F-M06 | LogPanel 使用数组 index 作为 key，新日志插入顶部时 DOM 复用错误 | `components/LogPanel.tsx:36` |
| F-M07 | 系统 WS 重连后没有做一次全量 refresh，断线期间错过的事件无法同步 | `lib/ws.ts:183` |
| F-M08 | 多处 API 失败静默回退 mock，用户看不到错误提示（Models/Monitor/Board） | 多个视图 |
| F-M09 | 可访问性（a11y）问题：大量可点击 `<div>` 无 button 语义、无 aria-label、模态框无焦点陷阱、ESC 关闭不统一 | 全局 |
| F-M10 | intervene-panel 使用 `display:none/block` 控制显示，无动画过渡 | `views/Meeting.tsx:213` |
| F-M11 | `vite.config.ts` 配置 `appType: 'mpa'` 但只有一个入口 | `vite.config.ts:16` |
| F-M12 | 没有 ESLint/Prettier 配置，无 `.env.example` | 项目配置 |
| F-M13 | Board 分页在 sort 改变时没有重置 page 到 1 | `views/Board.tsx` |
| F-M14 | `Topology` 视图在 `useMemo` 中执行 `console.warn` 副作用 | `views/Topology.tsx:16-28` |
| F-M15 | 会议 elapsed 计时器未在 meeting 切换时重置 | `state/AppContext.tsx:372-377` |

---

### P3 轻微问题（细节打磨）

| 编号 | 问题 | 位置 |
|------|------|------|
| F-L01 | ReportHeader 生成时间硬编码为 `'2026-07-16 15:08'` | `views/Report.tsx:417` |
| F-L02 | 打印样式中会议 ID 和日期硬编码（CSS 伪元素 content） | `styles/global.css:815` |
| F-L03 | LogPanel 日志截断 500 条没有提示用户 | `state/AppContext.tsx:110` |
| F-L04 | ContextPanel 关闭按钮是 `<div>` 无键盘可访问性 | `components/ContextPanel.tsx:36` |
| F-L05 | 依赖版本使用 `^` 前缀允许次版本升级，团队协同时建议精确版本或 lockfile | `package.json` |

---

## 四、正面评价与亮点

### 后端亮点
1. **SQL 注入防护完善**: 所有 DAO 层使用 SQLAlchemy 参数化查询，未发现字符串拼接 SQL
2. **SSRF 防护设计完整**: 覆盖内网段、DNS rebinding、重定向检测、URL 白名单
3. **Docker 沙箱加固到位**: 网络分级（L1 无网络/L2 DNS 过滤/L3 全联网）、非 root 用户、cap-drop ALL、read-only rootfs、seccomp、tmpfs
4. **崩溃恢复机制**: `recover_crashed_meetings()` 将未完成会议标记为 PAUSED，避免状态不一致
5. **资源清理系统化**: 会议删除级联清理 state/events/RAG/沙箱/浏览器上下文，lifespan shutdown 统一清理
6. **WebSocket 专业实现**: 心跳 ping/pong、指数退避重连、出站速率限制、增量回放
7. **密码安全**: PBKDF2 + 每用户随机 salt + `hmac.compare_digest` 防时序攻击

### 前端亮点
1. **Gen Speak 风格还原度高**: Notion 风极简线条、中性灰配色、衬线标题字体、克制的动效
2. **WebSocket 实现专业**: 指数退避重连（base 1s → max 30s + jitter）、`online` 事件恢复、4401 认证处理、心跳、`disposed` 标记防泄漏
3. **XSS 防护到位**: DOM 白名单清洗 + 转义 + 语义标记后处理三层防护
4. **⌘K 命令面板完整**: 键盘导航、⌘⇧选择、⌫关闭、分组、搜索
5. **报告演示模式**: 键盘翻页、进度条、TOC 跳转、打印样式
6. **深色/浅色主题**: CSS 变量系统完整，偏好持久化
7. **路由守卫**: `RequireAuth` + `authChecked` 加载态防闪烁，401 拦截去重
8. **富文本语义标记**: `[fact]`/`[assumption]`/`[risk:high]`/`[doc:xxx]`/`claim-xxx` 视觉层次分明
9. **请求取消**: 多处使用 `cancelled` 标记避免组件卸载后 setState
10. **乐观更新**: 设置页偏好更新使用乐观更新 + 失败回滚模式

---

## 五、修复优先级建议

### 第一阶段（立即修复，1-2天）
1. 删除 `main.py` 错误导入（C-01）
2. **修复 MeetingToolbar 不显示 bug**（F-C01）——当前用户无法控制会议
3. 统一 WS 认证检查条件（C-03）
4. 实现借调批准/拒绝 API 调用（F-C02）
5. 替换所有 `confirm()`/`alert()` 为自定义组件（F-C05、F-C04）
6. 修复 health 重复 PostgreSQL 检查（L-01）
7. 清理未使用导入（M-01）

### 第二阶段（本周内修复，3-5天）
8. 默认管理员密码安全加固（C-02）
9. API Key 传递方式改为 POST/Header（C-04）
10. 消息操作按钮实现功能（F-C03）
11. 修复 openMeeting 重复连接 WS 问题（F-H04）
12. 修复系统 WS 4401 处理（F-C06）
13. `safe_fetch` 改为异步客户端（H-03）
14. 修复用户菜单 `position:fixed` 定位（F-M04）
15. 真实会议无消息时显示空状态而非 mock（F-M02）

### 第三阶段（近期优化，1-2周）
16. **拆分 AppContext 解决每秒全树重渲染性能问题**（F-H01）
17. elapsed 基于服务端 started_at 计算（F-H02）
18. 速率限制内存泄漏修复（H-08）
19. 添加 Error Boundary（F-H09）
20. 实现 Toast 通知系统（F-H10）
21. ContextPanel 接入真实数据（F-H06）
22. 统一快捷键实现（F-H03）
23. PBKDF2 迭代次数提升 + JWT 添加 iss/aud（H-04、H-05）
24. 添加角色权限分级（M-03）
25. WebSocket 入站速率限制（M-04）
26. 修复 `_is_public()` 路径匹配（M-05）
27. Meeting list N+1 查询优化（M-06）
28. `asyncio.create_task` 全局异常监督（M-10）
29. 系统 WS 重连后全量 refresh（F-M07）
30. API 失败可见提示（F-M08）

### 第四阶段（持续优化，长期）
31. TypeScript 类型完善，消除 `any`（F-H05）
32. 可访问性（a11y）改进（F-M09）
33. ESLint + Prettier + Husky 工具链（F-M12）
34. Dockerfile 自动修改安全审计（H-06）
35. `/workspace/exec` 权限加固（H-07）
36. 工作区临时文件定期清理（M-07）
37. `sh -c` 命令执行加固（M-09）
38. 日志敏感数据脱敏（M-12）
39. 大列表虚拟化（消息/会议/日志）
40. 视图懒加载减少首屏包体积
41. 考虑引入 Sentry 前端错误监控
42. 多租户权限体系完善

---

## 六、Gen Speak 风格一致性评估

### 一致性较高
- Notion 风极简线条、中性灰配色、衬线标题字体
- 无夸张阴影和弹跳动效，transition 克制在 150-300ms
- ⌘K 命令面板交互逻辑和视觉
- 可折叠面板 chevron 交互
- 列表项悬停反馈和底部细线分隔
- 深色模式完整覆盖

### 可进一步借鉴
- Gen Speak 更细腻的选中/聚焦状态（蓝色 ring 而非边框变色）
- 输入框更精致的 focus 状态（当前已有雏形）
- 侧边栏/面板更强的层次感（当前 ContextPanel 阴影较轻）
- Toast/Snackbar 通知系统的视觉设计
- 快捷键提示在 tooltip 中显示组合键
