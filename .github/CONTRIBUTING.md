# 贡献指南

感谢你对 Conclave 的兴趣！我们欢迎任何形式的贡献。

## 快速开始

1. Fork 本仓库
2. 克隆到本地：`git clone https://github.com/<your-username>/Conclave.git`
3. 安装 Docker Desktop（推荐）或本地 Python 3.12+ / Node.js 20+
4. 启动开发环境：`docker compose up -d --build`
5. 访问 http://localhost:5173

## 开发规范

### 代码风格

- **后端**：遵循现有代码风格，`ruff check` 和 `ruff format` 必须通过
- **前端**：ESLint 规则保持现有宽松策略，新代码自觉遵守 TypeScript 类型规范
- **提交信息**：使用 Conventional Commits 格式：`<type>(<scope>): <中文描述>`
  - type: `feat` / `fix` / `refactor` / `docs` / `test` / `chore`
  - scope: `backend` / `frontend` / `docker` / `orchestrator` / `agents` / `tools` / `db` / `docs`

### 测试要求

- 新增功能必须加测试
- Bug 修复先加能复现 bug 的失败用例，再修复
- 所有测试通过 Docker Compose 运行：`docker compose -f docker-compose.test.yml up --build --exit-code-from backend-test`
- 禁止提交会导致 CI 红的代码

### 禁止事项

- 禁止硬编码 API Key、密码、内网地址
- 禁止提交个人临时文件、虚拟环境、`__pycache__`
- 禁止为了消类型错误而加 `# type: ignore` 或 `as any`，先理解根因
- 禁止引入未审核的外部依赖（后端 pip 包、前端 npm 包需在 PR 中说明理由）

## 提交 PR 流程

1. 从 `main` 分支创建 feature 分支：`git checkout -b feat/your-feature main`
2. 开发并在本地通过测试
3. 提交代码（小步提交，每个 commit 做一件事）
4. 推送到你的 Fork 并创建 Pull Request
5. PR 描述中说明：改了什么、为什么改、如何验证
6. 等待 CI 通过和代码审查

## 报告 Bug

使用 Issue 模板报告 Bug，请包含：
- 环境信息（OS、Docker 版本、Conclave 版本/commit）
- 复现步骤
- 预期行为 vs 实际行为
- 相关日志（`docker logs conclave-backend`）

## 功能建议

使用 Feature Request 模板，说明：
- 你想要解决的问题
- 建议的方案
- 替代方案（如有）

## 问题讨论

- 技术问题和使用疑问：GitHub Discussions
- Bug 报告：GitHub Issues
- 安全漏洞：请私信维护者，不要公开提 Issue

## 许可

贡献的代码将以 MIT 许可证发布。
