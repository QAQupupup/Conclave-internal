# Conclave 项目工程规范

> 本文档是 Conclave 项目的**唯一权威工程规范**。所有贡献者、AI 助手、CI/CD 流水线在操作本项目时必须遵守本文档中的规则。
>
> 模型初次加载项目时应优先阅读本文档，了解项目的工程约束和约定。

---

## 1. 部署与测试原则

### 1.1 Docker Compose 优先

**所有部署和测试必须通过 Docker Compose 执行，禁止在宿主机本地直接运行测试或服务。**

| 操作 | 正确方式 | 禁止方式 |
|------|---------|---------|
| 启动开发环境 | `docker compose up -d --build` | 本地 `python main.py` / `npm run dev` |
| 运行测试 | `docker compose -f docker-compose.test.yml up --build` | 本地 `pytest` / `npm test` |
| 集成测试 | `docker compose -f docker-compose.websearch-test.yml up --build` | 本地直接调 Playwright |
| 生产部署 | `docker compose -f docker-compose.oss.yml up -d` | 裸进程部署 |

**设计理由**：
- 消除"在我机器上能跑"问题 —— Docker 提供一致的运行时环境
- 跨平台兼容（Windows/macOS/Linux 统一使用 Docker 环境）
- 依赖隔离 —— 不污染宿主机 Python/Node 环境
- 环境变量通过 `docker-compose.yml` 统一注入，避免遗漏

### 1.2 异步测试策略

**当 pytest + pytest-asyncio 框架导致事件循环冲突或浏览器断连等问题时，采用手写测试脚本替代 pytest。**

背景：pytest-asyncio 为每个测试函数创建新的事件循环，导致 Playwright 浏览器的 subprocess transport 绑定到旧事件循环后 `new_context()` 挂死。手写脚本在单个 `asyncio.run(main())` 事件循环中顺序执行所有测试，浏览器只启动一次。

| 场景 | 方案 |
|------|------|
| 纯逻辑单元测试（无 I/O 依赖） | `pytest` + `unittest.mock` |
| 涉及 Playwright 浏览器 | 手写 `run_*_tests.py` 脚本 |
| 涉及真实 LLM 调用 | 手写测试脚本 + StubLLM 降级 |
| 涉及 Docker 容器 | `docker compose -f docker-compose.test.yml` |

**手写测试脚本模板**：参见 `backend/tests/run_web_search_tests.py`，所有测试在单个事件循环中顺序执行，测试报告包含 pass/fail/skip 计数和耗时统计。

---

## 2. 镜像构建规范

### 2.1 多阶段构建（强制要求）

**所有 Dockerfile 必须采用多阶段构建**，将构建依赖与运行时依赖分离，减小最终镜像体积。

已合规：
- `backend/Dockerfile`：4 阶段（system-deps → playwright → builder → work）
- `frontend/Dockerfile`：2 阶段（builder → nginx）

待改进：
- `backend/Dockerfile.cython-build`：单阶段，需改为多阶段
- `backend/Dockerfile.core-test`：单阶段，需改为多阶段
- `backend/web_search_service/Dockerfile`：单阶段，需改为多阶段
- `backend/docker/sandbox-datascience/Dockerfile`：单阶段（沙箱场景可豁免）
- `docker/Dockerfile.qdrant`：单阶段（第三方镜像封装可豁免）
- `docker/Dockerfile.postgres`：单阶段（第三方镜像封装可豁免）

### 2.2 基础镜像选择

- 优先使用 `-slim` 变体（减小体积）
- 所有镜像必须通过国内镜像源拉取（`docker.m.daocloud.io`）
- 禁止使用 `latest` 标签，必须指定具体版本号

---

## 3. 依赖镜像源（强制要求）

### 3.1 总则

**所有依赖，无论是系统层（apt/yum/apk）还是程序层（pip/npm/pnpm/cargo），必须使用国内镜像源。**

### 3.2 Dockerfile 中的镜像源配置

| 层级 | 镜像源 | 配置方式 |
|------|--------|---------|
| Docker 基础镜像 | `docker.m.daocloud.io` | FROM 指令 |
| Python pip | `https://pypi.tuna.tsinghua.edu.cn/simple` | `pip config set global.index-url` |
| Debian/Ubuntu apt | `https://mirrors.tuna.tsinghua.edu.cn` | DEB822 格式 sources.list |
| Alpine apk | `https://mirrors.aliyun.com` | `sed -i` 替换 |
| Node.js npm | `https://registry.npmmirror.com` | `ENV NPM_CONFIG_REGISTRY` |
| Playwright 浏览器 | `https://npmmirror.com/mirrors/playwright` | `PLAYWRIGHT_DOWNLOAD_HOST` 环境变量 |
| Docker CE (沙箱) | `https://mirrors.aliyun.com/docker-ce/linux/debian` | apt source |
| GitHub 下载代理 | `https://ghproxy.com` | URL 前缀替换 |

### 3.3 本地开发环境

本地开发也必须配置镜像源：

**npm（项目根目录 `.npmrc`）**：
```
registry=https://registry.npmmirror.com
```

**pip（项目根目录 `pip.conf` 或环境变量）**：
```bash
export PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
```

**pnpm（如使用）**：
```bash
pnpm config set registry https://registry.npmmirror.com
```

**Docker 守护进程**（`/etc/docker/daemon.json`）：
```json
{
  "registry-mirrors": ["https://docker.m.daocloud.io"]
}
```

---

## 4. 代码提交规范

### 4.1 Conventional Commits（强制要求）

所有 commit message 必须遵循 [Conventional Commits](https://www.conventionalcommits.org/) 规范：

```
<type>(<scope>): <description>

[optional body]

[optional footer(s)]
```

**允许的 type**：
- `feat`：新功能
- `fix`：缺陷修复
- `refactor`：重构（不改变功能）
- `docs`：文档变更
- `test`：测试相关
- `chore`：构建/工具/依赖变更
- `perf`：性能优化
- `style`：代码风格（不影响逻辑）
- `ci`：CI/CD 变更

**scope 示例**：`backend`、`frontend`、`docker`、`tools`、`orchestrator`、`docs`

### 4.2 提交归档（强制要求）

**每次提交必须伴随归档文件**，记录以下内容：

1. **问题描述**：修复了什么 / 实现了什么
2. **修复/变更内容**：具体改了什么，涉及哪些文件
3. **变更原因**：为什么这样改，设计决策的权衡

**归档文件位置**：`docs/audits/` 或 `docs/sessions/`，按日期命名：
- 审计修复：`docs/audits/audit-fix-report-YYYY-MM-DD.md`
- 会话归档：`docs/sessions/session-archive-YYYY-MM-DD-N.md`
- 项目审查：`docs/audits/project-review-YYYY-MM-DD.md`

**归档文件模板**：
```markdown
# {标题}

> **日期**: YYYY-MM-DD
> **范围**: {涉及的模块/会议}
> **修复状态**: {状态}

## 一、{发现/变更}总览

## 二、{问题/变更}详情

### {编号} — {标题}
- **位置**: `path/to/file.py:行号`
- **问题**: {描述}
- **修复**: {描述}
- **原因**: {为什么这样修}

## 三、验证结果
- {测试结果}
```

---

## 5. 前端审校规范

### 5.1 UI 设计原则

- 浅色主题为主，充足留白，精心设计的字体、间距和边距
- 扁平、简约、信息密度高的设计风格，参考 Linear / Notion / Vercel / Cursor
- 禁止渐变色、3D 效果、重阴影
- 可折叠 UI 元素（侧边栏、拓扑图、会议列表），使用优雅的小箭头实现弹性折叠
- 标签使用内联显示而非右侧分组
- Notion 风格软表格：中性灰表头、浅灰行线、中性灰标签
- 聊天流全宽平铺，右侧功能（证据/输出/报告/Token）放在浮动小徽章上，鼠标悬停显示功能名，点击弹窗展开内容
- 侧边栏默认折叠，点击议题后打开聊天面板聚焦内容
- Token 图标：白底黑字 'T'（极简风格）
- 图标和名称之间保持适当间距
- 输入框不阻塞聊天流，不浪费右侧空间
- 右侧浮动徽章打开交互窗口展示输入内容和回复
- 消息历史在窗口关闭/打开时持久化
- 带新标签的消息用换行分隔增强可读性
- 页面级边距：非会议视图内容区 padding 为 24px 32px 32px
- 值守按钮：右侧吸边隐藏，默认显示浅蓝色小盾牌图标，鼠标移入展开开关与状态，移出后自动收回

### 5.2 技术选型倾向

- 前端框架：React + TypeScript + Vite
- UI 组件库：Ant Design（当前使用）
- 状态管理：优先 React 内置状态（useState/useReducer/Context），避免过早引入全局状态库
- 样式方案：CSS Modules 或 Tailwind CSS
- 代码编辑器：Monaco Editor
- 图表：ECharts / d3-force
- 测试：Vitest

### 5.3 前端构建

- 所有前端构建在 Docker 多阶段构建中完成，不在本地构建
- 生产构建产物通过 Nginx 提供静态服务
- SPA fallback 路由在 nginx.conf 中配置

---

## 6. 代码保护与开源

### 6.1 开源前处理

源代码在同步到开源仓库前必须经过以下处理：

- 敏感信息提取：移除 API Key、内部地址、凭证
- 加密或编译：敏感逻辑在公开前进行混淆或编译
- 部分仓库代码需脱敏后才能开源

### 6.2 仓库管理

- 当前仓库可见性：public
- 认证方式：SSH
- 开发版与开源版通过 `docker-compose.yml` 和 `docker-compose.oss.yml` 分离
- 开源版镜像通过 `Dockerfile.oss` 构建，排除内部工具和敏感配置

---

## 7. 环境隔离

### 7.1 Python 环境

- 项目使用 Python 虚拟环境（venv），不依赖系统 Python
- `requirements.txt` 锁定所有依赖版本
- `pyproject.toml` 管理项目元数据和构建配置

### 7.2 编译环境

- 所有编译操作必须在 Docker 容器内执行，禁止在宿主机编译
- Cython 编译通过 `Dockerfile.cython-build` 完成

### 7.3 容器命名空间

- 开发环境：`conclave-dev`
- 测试环境：`conclave-test`
- 开源环境：`conclave-oss`
- 各环境通过 Docker Compose 命名空间隔离，端口错开避免冲突

---

## 8. 预提交卡点

项目使用 `pre-commit` 框架，提交前自动执行以下检查（配置见 `.pre-commit-config.yaml`）：

| 卡点 | 阶段 | 说明 |
|------|------|------|
| ruff lint | commit | Python 代码风格检查 |
| ruff format | commit | Python 代码格式化 |
| pytest smoke | commit | 后端冒烟测试 |
| tsc --noEmit | commit | 前端类型检查 |
| compose validate | commit | Docker Compose 配置校验 |
| frontend build | push | 前端生产构建 |
| OSS manifest validate | commit | 开源清单 JSON 校验 |

**安装**：`pip install pre-commit && pre-commit install`

### 8.1 CI/CD 流水线

项目已配置 GitHub Actions 流水线（`.github/workflows/`），所有 CI 任务均使用国内镜像源：

| 流水线文件 | 触发条件 | Job |
|-----------|---------|-----|
| `ci.yml` | push/PR 到 main、refactor/v3 | backend-checks（ruff + mypy）、frontend-checks（ESLint + tsc + build）、frontend-tests（vitest）、compose-check（docker compose config 校验）、backend-integration-tests（docker compose test）、publish-oss（自动同步到开源仓库） |
| `release-oss.yml` | ci.yml 调用或手动触发 | Cython 编译（Docker 容器内）、SSH 认证、auto-sync 分支推送 |

**镜像源**：CI 中通过 `PIP_INDEX_URL: https://pypi.tuna.tsinghua.edu.cn/simple` 和 `NPM_CONFIG_REGISTRY: https://registry.npmmirror.com` 环境变量注入。

---

## 9. LLM 与 Agent 规范

### 9.1 确定性与稳定性

- 系统追求确定性和稳定性，而非随机性
- LLM 行为应可预测、可复现
- 关键路径上使用 StubLLM 降级确保系统不因 LLM 故障中断
- 五层确定性保障：参数约束 → 结论锁定链 → 一致性自检 → 全链路追踪 → 自动降级

### 9.2 日志与监控

- 健全的日志系统：结构化日志总线 + 多 sink 输出
- 数据监控统计夹具：指标采集（环形缓冲）+ 成本追踪
- 运行真实 LLM 进行验证并观察日志，不绕过问题
- 保持系统扩散性和动态性

### 9.3 Agent 设计

- Agent 拟人化：独立人格、视角、风险偏好、证据偏好
- 系统自优化和迭代能力（meta-agent）
- 动态流程组装优于固定阶段
- 实时交互优于批量处理
- 反"vibe coding"理念：禁止 AI 凭感觉编码，强制执行工程纪律

---

## 10. 文档规范

### 10.1 文档组织

| 目录 | 内容 |
|------|------|
| `docs/design/` | 设计文档（ideal-design、design-principles、iteration-1-design） |
| `docs/audits/` | 审计报告和修复归档 |
| `docs/research/` | 调研文档（skill-system-architecture、optimization-backlog） |
| `docs/sessions/` | 会话归档 |
| `.trae/documents/` | 实施计划和完成报告 |

### 10.2 文档引用

- 文档中引用代码文件时，必须使用当前实际存在的文件路径
- 历史文档中引用已重构的文件时，应在文档顶部添加历史注记说明映射关系
- 行号引用在代码重构后失效，应改用函数名引用

---

## 11. 快速检查清单

在提交代码前，确认以下所有项：

- [ ] 所有变更通过 Docker Compose 测试（非本地）
- [ ] 新增 Dockerfile 采用多阶段构建
- [ ] 所有依赖配置了国内镜像源（apt/pip/npm/apk）
- [ ] 提交信息符合 Conventional Commits 格式
- [ ] 提交附带归档文件（问题 + 修复 + 原因）
- [ ] 前端变更符合 UI 设计原则（无渐变/3D/重阴影）
- [ ] 敏感信息已脱敏（如涉及开源同步）
- [ ] 预提交卡点全部通过（`pre-commit run --all-files`）
- [ ] 文档引用路径与实际代码一致

---

## 12. 已知待修复项

> 最后更新：2026-07-14。全部已修复。

| # | 问题 | 修复措施 | 状态 |
|---|------|---------|------|
| 1 | `FROM conclave-backend:latest` 使用 `latest` 标签 + 单阶段构建 | 重写为四阶段构建（system-deps → playwright → builder → work），基础镜像 `python:3.12-slim`，不再依赖外部镜像 | 已修复 |
| 2 | `packageManager: pnpm` 但实际使用 npm，双锁文件并存 | 删除 `pnpm-lock.yaml`，移除 `packageManager` 字段，全链路统一 npm | 已修复 |
| 3 | 缺少本地 `pip.conf` | 创建 `pip.conf`（清华 TUNA 镜像源） | 已修复 |
| 4 | `nginx:alpine` 未锁定版本号 | 改为 `nginx:1.27-alpine` | 已修复 |
| 5 | `Dockerfile.cython-build` / `Dockerfile.core-test` 单阶段 | 构建/测试容器，豁免多阶段要求 | 可豁免 |