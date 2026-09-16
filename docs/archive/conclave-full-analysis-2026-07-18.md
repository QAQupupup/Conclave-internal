# Conclave 全量问题分析报告

**日期**: 2026-07-18
**范围**: 前端（React+TS+Vite）+ 后端（FastAPI+Python）+ Docker 沙箱架构 + 目录规范
**基于**: 2026-07-18 全量代码审查 + 安全修复总结 + 目录规范文档 + 实际代码验证

---

## 一、已修复问题确认（2026-07-18 安全修复轮次）

根据 `conclave-security-frontend-testing-fix-summary-2026-07-18.md`，以下问题**已修复**，无需再处理：

| 编号 | 问题 | 状态 |
|------|------|------|
| C-01 | SQLAlchemy 错误导入 `sqlalchemy.testing.pickleable.User` | 已修复 |
| C-03 | WebSocket 认证绕过（测试模式双条件不一致） | 已修复 |
| C-04 | API Key 通过 URL query 参数传递 | HTTP 中间件已修复（仅 WS 保留） |
| H-02 | WS 缺少会议级权限校验 | 已修复 |
| H-03 | `safe_fetch` 使用同步 httpx 阻塞事件循环 | 已修复（AsyncClient + 连接池） |
| H-04 | PBKDF2 迭代次数 260k → 600k + 透明升级 | 已修复 |
| H-05 | JWT 缺少 iss/aud/jti 声明 | 已修复 |
| H-06 | deploy_service 原地修改用户 Dockerfile | 已修复（临时副本 + workspace_root） |
| H-07 | 沙箱逃逸风险（Docker 安全参数加固 + 黑名单扩展） | 已修复 |
| H-08 | 速率限制内存永久增长 | 已修复（LRU + 定期清理） |
| M-04 | WS 入站限流缺失 | 已修复（WsInboundRateLimiter） |
| M-08 | SSRF 多跳重定向 | 已修复（手动跟随 5 跳，每跳校验） |
| M-10 | 裸 `asyncio.create_task` 无监督 | 已修复（`create_supervised_task`） |
| WS | 重连 destroyed bug、心跳缺失、onerror 挂起、4403/4429 处理 | 已修复（ws.ts 重写） |
| FE | sanitizeRich href 协议白名单（data:/vbscript: 过滤） | 已修复 |
| FE | Login redirect 开放重定向 | 已修复 |
| FE | logout 未清理 WS/状态/日志 | 已修复 |
| 测试 | conftest 缺少 APP_ENV=test、测试 async 假阳性、CI vitest | 已修复 |

---

## 二、后端现存问题

### Critical（需立即修复）

#### B-C01: 默认管理员密码仍为 `admin123`
- **位置**: `backend/app/auth.py:51`
- **现状**: `DEFAULT_ADMIN_PASSWORD = os.environ.get("CONCLAVE_ADMIN_PASSWORD", "admin123")`
- **影响**: 生产环境忘记配置环境变量时，攻击者可用 `admin/admin123` 直接登录获得完全控制权（执行任意代码、删除数据）
- **修复建议**:
  1. 生产模式（`APP_ENV=production`）未设置密码时：启动时生成随机密码并打印到日志（仅一次），或拒绝启动
  2. 首次登录强制修改密码
  3. 启动日志中添加醒目安全警告
  4. 开发模式（`APP_ENV=dev`，默认）保留 `admin123` 方便开发

#### B-C02: MeetingToolbar CSS `display:none` 导致工具栏不可见
- **位置**: `frontend/src/styles/global.css:476`
- **现状**: `.meeting-toolbar{display:none}` 且 `.meeting-toolbar.show{display:flex}`，但 `MeetingToolbar.tsx` 渲染时没有添加 `show` class
- **影响**: **会议页面右侧的阶段指示器、暂停/介入/终止按钮完全不显示**，用户无法控制会议
- **修复建议**: 去掉 `.meeting-toolbar{display:none}` 和 `.meeting-toolbar.show` 规则（条件渲染 `{isMeeting && <MeetingToolbar />}` 已控制可见性）

---

### High（高危，优先修复）

#### B-H01: 借调批准/拒绝按钮是空实现
- **位置**: `frontend/src/views/Meeting.tsx:140-141`
- **现状**: 两个按钮只调用 `appendLog()`，不发送 API/WS 请求，`borrowRequest` 状态不清空
- **影响**: 用户点击批准/拒绝后无实际效果，弹窗不消失，后端收不到决策
- **修复建议**: 调用 WS control signal（`borrow_approve` / `borrow_reject`），成功后设置 `meeting.borrowRequest = null`

#### B-H02: 消息操作按钮（复制/聚焦/引用）是空实现
- **位置**: `frontend/src/views/Meeting.tsx:185-187`
- **现状**: 三个按钮只有 `e.stopPropagation()`，无任何功能
- **修复建议**:
  - 复制: `navigator.clipboard.writeText(content)` + toast 反馈
  - 聚焦: `scrollIntoView({behavior:'smooth', block:'center'})` + 临时高亮
  - 引用: 将消息内容填入介入面板 textarea 并自动打开

#### B-H03: `abortMeeting` 仍使用浏览器原生 `confirm()`
- **位置**: `frontend/src/state/AppContext.tsx:349`
- **现状**: `if (!confirm('确认终止会议？此操作不可撤销。')) return;`
- **影响**: 原生阻塞弹窗与 Gen Speak 极简风格严重不协调
- **修复建议**: 实现自定义 ConfirmModal 组件（与整体 UI 风格统一），或复用 CommandPalette 样式

#### B-H04: AppContext 单 Context 导致全组件树每秒重渲染
- **位置**: `frontend/src/state/AppContext.tsx`
- **现状**: `meeting` 对象含 `elapsed` 字段，每秒 `setMeeting` 更新导致整个 context value 重建，所有 `useApp()` 消费者重渲染
- **影响**: 长时间开会后页面卡顿，Topbar/NavRail/CommandPalette 等无关组件也被迫重渲染
- **修复建议**:
  - 方案 A: 将 `elapsed` 拆出为独立 state，在 Meeting 视图内部用 `useState` + `useInterval` 基于 `started_at` 时间戳计算
  - 方案 B: 拆分 Context 为 `AuthContext`、`MeetingContext`、`UIContext`，或使用 Zustand 支持选择订阅

#### B-H05: 真实会议无消息时回退显示 MESSAGES mock 数据
- **位置**: `frontend/src/views/Meeting.tsx:51`
- **现状**: `const source: any[] = meeting.messages.length ? meeting.messages : MESSAGES;`
- **影响**: 新会议刚开始或消息尚未到达时，用户看到假数据，产生严重误导
- **修复建议**: `meeting.messages.length === 0` 时显示空状态（"等待主持人开场…" + typing dots 动画），不要回退 mock

#### B-H06: docker-compose v2 插件未安装在后端容器中
- **位置**: `backend/Dockerfile`（apt-get install 只有 `docker-ce-cli`）
- **现状**: 后端容器安装了 `docker-ce-cli`（支持 `docker run/build/pull`），但没有安装 `docker-compose-plugin`（支持 `docker compose up`）
- **影响**: `deploy_service` 当前只支持单容器部署；当 LLM 生成 `docker-compose.yml`（多服务：backend+frontend+db）时无法启动
- **修复建议**: 在 Dockerfile 中添加 `docker-compose-plugin` 安装：
  ```dockerfile
  apt-get install -y --no-install-recommends docker-ce-cli docker-compose-plugin
  ```

---

### Medium（中危）

| 编号 | 问题 | 位置 | 修复建议 |
|------|------|------|----------|
| B-M01 | ContextPanel 数据全是硬编码 mock | `ContextPanel.tsx:13-17` | 从 meeting state 读取真实 EVIDENCE/TOKEN_STATS/ROLES；未加载时显示 skeleton |
| B-M02 | 分页按钮无 disabled 样式 | `Board.tsx:133-151`、`Models.tsx` | 添加 `disabled` 属性 + 透明度降低 + cursor:not-allowed |
| B-M03 | Settings 页偏好设置只读展示 | `Settings.tsx:243-248` | 根据值类型渲染 switch/select/input 控件，调用 API 保存 |
| B-M04 | 缺少 Error Boundary | 全局 | 实现 ErrorBoundary class 组件，包裹懒加载边界 |
| B-M05 | 缺少 Toast/Notification 系统 | 全局 | 实现轻量 Toast（success/error/warning/info，4秒自动消失） |
| B-M06 | CommandPalette 快捷键标签未实现 | `mock.ts:458-460` | 补充全局快捷键注册（⌘K 已有，⌘D/⌘L/⌘N 需实现或移除标签） |
| B-M07 | openMeeting 可能重复连接 WS | `AppContext.tsx:290-311` | 判断若 `id === meeting.currentMeetingId` 且 WS 已连接则直接返回 |
| B-M08 | 大量 `any` 类型 | 全局 | 定义 `MeetingMessage`、`Meeting`、`WsEvent` 等接口，逐步消除 `any` |
| B-M09 | elapsed 计时器前端本地累加，与服务端偏差 | `AppContext.tsx:372-377` | 从 API/WS snapshot 读取 `started_at`，前端基于 `Date.now() - started_at` 计算 |
| B-M10 | Topbar 用户菜单 `position:fixed` 定位错误 | `Topbar.tsx:62` + CSS:331 | 改为 `position:absolute`，确保父元素有 `position:relative` |
| B-M11 | WS 系统级重连后无全量 refresh | `ws.ts:183` | 重连后主动调用 `/meetings/{id}` 或发送 `snapshot` 请求同步错过的事件 |
| B-M12 | API 失败静默回退 mock，用户无感知 | 多个视图 | API 失败时显示错误提示而非静默展示 mock |
| B-M13 | 后端 `_check_port_healthy` 使用同步 urllib（L-04） | `sandbox.py:931-947` | 改为 httpx.AsyncClient（已有依赖） |
| B-M14 | `/debug/auth-info` 端点生产环境暴露信息 | `main.py:261-280` | 仅在 `APP_ENV=dev` 时注册该路由 |
| B-M15 | 宿主机降级路径 `_run_on_host` 仍保留（M-02） | `sandbox.py` | 生产环境强制禁用（`CONCLAVE_SANDBOX_ALLOW_HOST` 默认 False 已做，但代码路径仍存在） |

---

### Low（低危/细节打磨）

| 编号 | 问题 |
|------|------|
| B-L01 | `vite.config.ts` 配置 `appType: 'mpa'` 但只有一个入口 |
| B-L02 | LogPanel 使用数组 index 作为 key，新日志插入顶部时 DOM 复用错误 |
| B-L03 | Report 页时间硬编码 `'2026-07-16 15:08'` |
| B-L04 | 多处 `<div>` 用作按钮无 button 语义、无 aria-label（a11y） |
| B-L05 | 没有 ESLint/Prettier 配置文件 |
| B-L06 | `_run_on_host` 临时文件创建 TOCTOU 竞态（仅 host fallback 路径） |
| B-L07 | Token 存储在 localStorage，XSS 风险（长期建议 HttpOnly Cookie + refresh token） |
| B-L08 | API 层无超时/重试/取消机制（建议 AbortController 30s 超时 + 幂等重试） |
| B-L09 | CSP 允许 `'unsafe-inline'`，可进一步收紧 |
| B-L10 | 没有 404 页面（catch-all 直接重定向首页） |

---

## 三、前端风格与设计问题

### 整体评价
Gen Speak（Notion 风极简）风格还原度**较高**：
- 中性灰配色、衬线标题字体、克制的 150-300ms transition
- ⌘K 命令面板、可折叠面板 chevron、底部细线分隔
- 深色/浅色主题 CSS 变量系统完整

### 需要改进的设计细节

1. **对话框风格不统一**: 原生 `confirm()`/`alert()` 弹窗（abortMeeting、Report 页 TraceTag/附件下载）破坏极简风格，需要统一为自定义 Modal
2. **反馈机制缺失**: 没有 Toast 系统，操作成功/失败只能通过日志面板看到，普通用户无感知
3. **空状态设计缺失**: 无消息时直接展示 mock 数据，应设计优雅的 skeleton/空状态
4. **错误状态设计缺失**: API 失败静默回退 mock，应设计错误提示卡片（带重试按钮）
5. **焦点环样式**: 当前 focus 状态较粗糙，可参考 Linear/Vercel 的蓝色 ring 效果
6. **ContextPanel 层次感**: 面板阴影较轻，视觉层次不够突出
7. **工具栏 tooltip**: 快捷键提示应在 tooltip 中显示组合键（如 `⌘K 打开命令面板`）
8. **响应式断点**: 移动端适配已有基础（850px 断点隐藏 toolbar），但中等屏幕（1024-1280px）下布局可进一步优化

---

## 四、Docker Sandbox / DinD 问题专项分析

这是你提出的核心问题，我做详细分析。

### 4.1 当前架构：Sibling Containers（非 DinD）

```
宿主机 (Docker Desktop / Linux dockerd)
├── Docker daemon (dockerd)
├── docker-socket-proxy 容器 (tecnativa/docker-socket-proxy)
│   └── 只读挂载 /var/run/docker.sock，代理 Docker API
├── Conclave Backend 容器 (conclave-dev-backend)
│   ├── FastAPI 后端
│   ├── docker-ce-cli (通过 DOCKER_HOST=tcp://docker-socket-proxy:2375 连接)
│   └── 通过 Docker API 创建 sibling 容器
├── 沙箱容器 (按需创建的 sibling)
│   └── 挂载 conclave-dev-workspace 卷
└── 部署服务容器 (按需创建的 sibling，conclave-svc-xxx)
    └── 挂载 conclave-dev-workspace 卷 + 映射端口
```

**关键区别**:
- **DinD（Docker-in-Docker）**: 在容器内运行一个完整的 Docker daemon，需要 `--privileged`，安全风险极高
- **Sibling Containers（当前方案）**: 容器内只有 docker CLI，通过 socket 代理连接宿主机 Docker daemon，创建的容器是后端容器的"兄弟"而非"子容器"，不需要 `--privileged`

### 4.2 回答你的问题：沙箱阻止 docker 命令是否会导致问题？

**不会影响可部署服务的 docker-compose 启动**。原因如下：

1. **沙箱容器（run_python/run_command）是一次性执行容器**，它们被严格限制：
   - 网络分级（L1 无网络/L2 DNS 白名单/L3 需授权）
   - 以 `nobody(65534)` 运行，cap-drop ALL
   - 命令黑名单明确禁止 `docker run/exec/build`（sandbox.py:158）
   - **这些容器不能也不应该运行 docker 命令**——这是安全设计，不是 bug

2. **`deploy_service()` 不在沙箱容器内执行**——它在 **Conclave 后端容器本身**中运行 docker CLI，通过 socket proxy 调用宿主机 Docker API：
   - 后端容器有 docker-ce-cli
   - 后端容器通过 `DOCKER_HOST=tcp://docker-socket-proxy:2375` 连接代理
   - socket proxy 已开启 `CONTAINERS=1, IMAGES=1, BUILD=1, NETWORKS=1, VOLUMES=1`（这些权限足够运行 `docker compose up`）
   - 后端容器以 app 用户(uid 1000)运行，但 entrypoint 已配置好 docker socket 权限

3. **数据流方向**:
   - LLM 生成代码/文件 → 写入 `<meeting_id>/` 目录（通过 workspace_tools）
   - 如果检测到是 deployable_service → 调用 `deploy_service()`
   - `deploy_service()` 在**后端容器**中执行 docker 命令 → 调用宿主机 dockerd → 创建服务容器
   - **沙箱容器从未参与部署流程**，所以沙箱禁止 docker 命令不影响部署

### 4.3 当前 docker-compose 多服务部署的缺口

虽然架构上支持，但代码层面有以下缺口需要补齐：

| 缺口 | 现状 | 修复方案 |
|------|------|----------|
| docker-compose-plugin 未安装 | 后端容器只有 docker-ce-cli | Dockerfile apt-get 添加 `docker-compose-plugin` |
| `deploy_service()` 未检测 `docker-compose.yml` | 只检测 `Dockerfile` | 检测到 `docker-compose.yml` 时改用 `docker compose -p conclave-svc-{meeting_id} up -d` |
| 多端口映射 | 当前只映射一个 container_port | 解析 compose 文件获取所有暴露端口，从 18000 池分配 |
| 多服务健康检查 | 当前只检查一个 HTTP 端点 | 遍历 compose 中的所有服务，逐一检查 /health |
| 停止时清理 | 当前 `docker rm -f` 单容器 | 改为 `docker compose -p {project} down -v` 清理网络和卷 |
| Compose 文件安全审计 | 无 | 校验 compose 文件：禁止 privileged、host network、挂载宿主机敏感路径、禁止 cap_add 危险能力 |

### 4.4 Docker Socket Proxy 权限评估

当前 socket proxy 配置：
```
CONTAINERS=1  ✓ (创建/启动/停止/删除容器)
IMAGES=1      ✓ (拉取/列出镜像)
BUILD=1       ✓ (docker build)
NETWORKS=1    ✓ (网络管理，compose 需要创建自定义网络)
VOLUMES=1     ✓ (卷管理，compose 需要创建卷)
INFO=1, VERSION=1, PING=1  ✓ (健康检查)
EXEC=0        ✓ (禁止 docker exec，防横向渗透)
SERVICES=0, SECRETS=0, PLUGINS=0, COMMIT=0, SYSTEM=0  ✓ (危险端点已禁用)
```

**docker compose 需要的 API 权限**:
- containers/create/start/stop/remove → CONTAINERS=1 ✓
- images/create/pull → IMAGES=1 ✓
- networks/create/connect/disconnect/remove → NETWORKS=1 ✓
- volumes/create/remove → VOLUMES=1 ✓
- build → BUILD=1 ✓
- **不需要** EXEC（docker compose 不使用 exec API 创建容器）
- **不需要** SERVICES（这是 Swarm services，不是 compose）

结论：**socket proxy 现有权限足够运行 docker compose**，不需要开放更多端点。

### 4.5 数据科学/代码编写工作的沙箱约束

对于数据科学和代码编写工作（非部署类），沙箱策略正确：
- 代码在沙箱容器内执行（L1/L2/L3 网络分级）
- 禁止 docker 命令（防止容器逃逸）
- 代码文件写入 `<meeting_id>/` 目录，沙箱容器通过 volume 挂载访问
- 如果代码需要启动服务（如 Flask/FastAPI 调试），应通过 `deploy_service()` 部署为独立容器，而非在沙箱内后台运行

---

## 五、沙箱目录规范现状与建议

### 5.1 已有规范（`conclave-sandbox-directory-standard.md` v1.0）

目录规范文档已定义三种交付物类型的标准布局：

| 类型 | 目录结构 | 执行方式 |
|------|----------|----------|
| 数据分析 | `main.py` + `data/` + `output/` + `requirements.txt` | `python main.py` |
| 可测试系统 | `src/` + `tests/` + `requirements.txt` | `pytest tests/ -v` |
| 可部署服务 | `app/main.py` + `frontend/` + `requirements.txt` + `Dockerfile` + `docker-compose.yml` | `deploy_service()` |

### 5.2 需要补充/修复的规范点

1. **docker-compose.yml 规范补充**:
   - 必须指定 `name: conclave-svc-{meeting_id}` 或使用 `-p` 参数做项目隔离
   - 禁止使用 `network_mode: host`、`privileged: true`、`cap_add: [ALL, SYS_ADMIN, NET_ADMIN]`
   - 禁止挂载 `/var/run/docker.sock`、`/etc/shadow`、`/root/.ssh` 等敏感路径
   - 所有服务必须使用内部网络（不映射到宿主机 0.0.0.0，由 Conclave 统一映射）

2. **Node.js 前端项目支持**:
   - 当前前端限制为 CDN 模式（`frontend/index.html` 通过 CDN 引入 React/Vue）
   - 需要补充：`package.json` + npm build 流程规范
   - 需要 Node.js 沙箱镜像（类似数据科学镜像预装 npm/yarn）
   - L2 白名单需要添加 npm 镜像域名（`registry.npmmirror.com`）

3. **`.conclave/` 元数据目录**:
   - 规范中定义了 `.conclave/manifest.json`、`exec_history/`、`artifacts/`
   - 但 workspace_tools.py 中 `list_files` 已过滤 `.` 开头的文件/目录
   - 需要确保 manifest.json 在 deploy_service 时被读取（用于确定入口、端口、健康检查路径等）

4. **入口检测逻辑统一**:
   - 规范中定义了入口检测规则（`app/main.py`、`app.py`、`Dockerfile`、`docker-compose.yml`）
   - 但代码中 `deploy_service` 和 produce 阶段的入口检测逻辑需要对齐
   - 建议将目录规范的检测逻辑实现为 `app/sandbox/_detect_project_type()` 函数，统一使用

5. **代码生成 prompt 中强制注入规范**:
   - 规范第九节定义了给 LLM 的 prompt 约束，但需要在 `app/agents/prompts.py` 的 produce 阶段模板中实际注入
   - 这是确保 LLM 生成代码遵循规范的关键环节

---

## 六、修复优先级排序

### 第一阶段（立即修复，0.5-1天）

1. **修复 MeetingToolbar `display:none`**（B-C02）——用户无法控制会议
2. **修复借调批准/拒绝按钮**（B-H01）——功能阻断
3. **替换 `confirm()` 为自定义 Modal**（B-H03）——体验阻断
4. **修复无消息时回退 mock**（B-H05）——数据误导

### 第二阶段（1-2天）

5. **实现消息操作按钮**（B-H02：复制/聚焦/引用）
6. **默认管理员密码安全加固**（B-C01）
7. **安装 docker-compose-plugin + 实现 compose 多服务部署**（B-H06）
8. **修复 openMeeting 重复连接 WS**（B-M07）
9. **修复用户菜单 position:fixed 定位**（B-M10）

### 第三阶段（3-5天）

10. **拆分 AppContext / 修复 elapsed 性能问题**（B-H04 + B-M09）
11. **实现 Toast 通知系统**（B-M05）
12. **添加 Error Boundary**（B-M04）
13. **ContextPanel 接入真实数据**（B-M01）
14. **API 层添加超时/取消机制**（B-L08）
15. **实现目录规范的自动检测逻辑**（`_detect_project_type()`）

### 第四阶段（1-2周）

16. TypeScript 类型完善消除 `any`（B-M08）
17. Settings 页可编辑（B-M03）
18. 分页 disabled 样式（B-M02）
19. 快捷键实现或清理（B-M06）
20. 系统 WS 重连后全量 refresh（B-M11）
21. Node.js 沙箱镜像 + npm L2 白名单
22. Compose 文件安全审计
23. ESLint + Prettier 工具链
24. 可访问性改进
25. 404 页面

---

## 七、测试覆盖缺口（需后续补充）

### 后端缺失测试
1. JWT 登录流程（`/auth/login`、`/auth/me`）
2. 安全边界测试（未认证 401、角色权限隔离、用户 A 不能访问用户 B 的会议）
3. SSRF 防护测试（内网 IP、DNS rebinding、重定向绕过）
4. 路径穿越测试（`_resolve_path()`）
5. WebSocket 权限测试（未认证 4401、普通用户访问他人会议 4403）
6. 工作区文件 API 集成测试
7. deploy_service docker-compose 多服务部署测试

### 前端缺失测试
1. 认证流程（RequireAuth、SessionExpiredModal、login/logout）
2. API 层（401 拦截、错误处理、token 注入）
3. 核心视图组件测试（Meeting、Report、Board）
4. AppContext 状态转换测试
5. E2E 测试（Playwright 覆盖登录→创建会议→会议运行全流程）
