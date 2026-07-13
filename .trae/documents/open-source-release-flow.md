# Conclave 开源发布与 CI/CD 流程体系

> 本文档定义开发版仓库（私有）与开源版仓库（公开）之间的代码同步规则、卡点检查规则以及分支合并策略。

## 1. 仓库与分支模型

| 仓库 | 可见性 | 用途 | 关键分支 |
|---|---|---|---|
| `Conclave-internal` | private | 日常开发、敏感算法、内部文档 | `main` / `refactor/v3-manager-agent-runtime` |
| `Conclave-OSS` | public | 开源发布、可审计的代码 | `auto-sync`（自动同步） / `release`（发布候选） / `main`（正式发布） |

### 分支策略

1. **开发版 `main`（或 `refactor/v3-manager-agent-runtime`）**
   - 所有功能开发、Bug 修复、重构都在此分支进行。
   - 任何 push / PR 必须通过 CI 卡点。

2. **开源版 `auto-sync`**
   - 由 GitHub Actions 自动维护，**禁止人工直接推送**。
   - 每次开发版 CI 通过后，`publish_open_source.py` 会自动把可开源内容同步到这里。

3. **开源版 `release`**
   - 发布候选分支。
   - 当准备发布时，从 `auto-sync` 创建 PR 合并到 `release`。

4. **开源版 `main`**
   - 稳定发布分支。
   - 只有经过测试验证的 `release` 分支才能合并进来。

### 人工决策点

- 你**不需要**手动执行同步脚本。
- 你**只需要**决定：何时把 `auto-sync` 合并到 `release`，以及何时把 `release` 合并到 `main`。

## 2. 卡点检查（Gates）

### 2.1 本地提交卡点（pre-commit）

配置文件：`.pre-commit-config.yaml`

安装命令（Windows）：

```powershell
.\scripts\install-hooks.ps1
```

Linux / macOS / Git Bash：

```bash
pip install pre-commit
pre-commit install
```

提交时会自动运行：

| 卡点 | 范围 | 触发时机 |
|---|---|---|
| `ruff` lint + format | `backend/app`, `conclave_core`, `tests`, `scripts` | commit |
| `pytest` smoke | 后端测试 | commit |
| `tsc --noEmit` | 前端 TypeScript | commit |
| `docker compose config` | `docker-compose.yml` + `docker-compose.oss.yml` | commit |
| JSON 校验 | `scripts/oss_manifest.json` | commit |
| `npm run build` | 前端生产构建 | push |

任何卡点失败都会阻止 `git commit`（`push` 阶段的失败会阻止 `git push`）。紧急情况下可用 `git commit --no-verify` 跳过，但不推荐。

### 2.2 CI 卡点（GitHub Actions）

工作流文件：

- `.github/workflows/ci.yml`：每次 push / PR 触发
- `.github/workflows/release-oss.yml`：CI 成功后触发，自动同步到开源版

`ci.yml` 包含：

| Job | 检查内容 |
|---|---|
| `backend-checks` | `ruff` 检查/格式化、`mypy` 类型检查、`pytest` 测试 |
| `frontend-checks` | ESLint、`tsc` 类型检查、生产构建 |
| `compose-check` | `docker compose config` 配置校验 |

所有 job 通过且仓库为开发版时，`release-oss.yml` 才会执行。

## 3. 自动同步规则

### 3.1 清单驱动

同步清单：`scripts/oss_manifest.json`

清单决定哪些文件/目录会被复制到开源仓库、哪些文本需要替换、哪些文件需要删除。

核心规则：

- **白名单复制**：只复制清单中列出的文件/目录，新增文件默认不会同步，必须显式加入清单。
- **增量同步**：基于文件 SHA256 哈希，仅复制变更文件。
- **文本替换**：例如移除内部域名、替换容器名前缀等。
- **源码保护**：`conclave_core` 中的敏感算法源码会被删除，只保留编译后的二进制扩展（`.pyd`/`.so`）和必要的 `__init__.py`。
- **审计报告**：每次同步生成 `AUDIT_REPORT.md`，记录变更文件、删除文件和二进制扩展。

### 3.2 同步脚本

脚本：`scripts/publish_open_source.py`

常用命令：

```bash
# 干跑：查看会同步哪些文件
python scripts/publish_open_source.py --oss-repo ../Conclave-OSS --dry-run

# 本地手动同步（不推送）
python scripts/publish_open_source.py --oss-repo ../Conclave-OSS

# 同步并推送到指定分支
python scripts/publish_open_source.py \
  --oss-repo ../Conclave-OSS \
  --version 0.9.0 \
  --branch auto-sync \
  --push
```

CI 中默认推送到 `auto-sync` 分支。

## 4. CI/CD 配置方法

### 4.1 开发版仓库配置

1. 把 `.github/workflows/ci.yml` 和 `.github/workflows/release-oss.yml` 提交到开发版仓库。
2. 在 GitHub 设置中添加 Secrets：
   - `OSS_DEPLOY_KEY`：用于写开源仓库的 SSH 私钥。
   - `OSS_REPO_URL`（可选）：开源仓库 SSH 地址，默认 `git@github.com:QAQupupup/Conclave-OSS.git`。

### 4.2 开源版仓库配置

1. 在开源版仓库 Settings → Deploy keys 中添加 `OSS_DEPLOY_KEY` 对应的公钥，勾选 **Write access**。
2. 开源版仓库也需要 `.github/workflows/ci.yml`（用于在 `auto-sync` / `release` / `main` 上运行基本检查）。
   - 可以在 OSS 仓库中保留一个简化版 CI，只运行 Docker Compose 配置校验和前端构建。

### 4.3 发布流程

```text
开发版 main/refactor 提交
        │
        ▼
   CI 卡点通过
        │
        ▼
  自动同步到 Conclave-OSS:auto-sync
        │
        ▼
  你决定发布时创建 PR:
  auto-sync ──► release
        │
        ▼
  你决定正式上线时创建 PR:
  release ──► main
```

## 5. Docker Compose 命名空间隔离

为避免开发版与开源版同时运行时冲突，开发仓库维护两份 Compose 文件：

- `docker-compose.yml`：本地开发版配置（命名空间 `conclave-dev`）。
- `docker-compose.oss.yml`：开源版源配置（命名空间 `conclave-oss`），通过清单同步为开源仓库的 `docker-compose.yml`。

隔离规则如下：

| 项目 | 开发版 | 开源版 |
|---|---|---|
| project name | `conclave-dev` | `conclave-oss` |
| container name | `conclave-dev-*` | `conclave-oss-*` |
| volume name | `conclave-dev-*` | `conclave-oss-*` |
| 前端端口 | `5173` | `5174` |
| 后端端口 | `8000` | `8001` |
| noVNC 端口 | `6080` | `6081` |
| Qdrant 端口 | `6333/6334` | `6335/6336` |
| Postgres 端口 | `5432` | `5433` |
| Redis 端口 | `6379` | `6380` |

这意味着两个版本的容器、网络、卷完全独立，可以同时启动。

## 6. 安全与审计

1. **敏感信息不出仓库**：内部 API Key、业务文档、核心算法源码不会进入开源版。
2. **二进制审计**：每次发布生成 `AUDIT_REPORT.md`，明确列出删除了哪些源码、新增了哪些二进制。
3. **自动化不可绕过**：CI 与 pre-commit 共同构成两道卡点，只有都通过才能进入开源版。
4. **人工最终审批**：自动同步只到 `auto-sync`，合并到 `release` / `main` 必须由你手动审批。

## 7. 常见操作速查

| 目标 | 命令 |
|---|---|
| 本地安装提交卡点 | `.\scripts\install-hooks.ps1` |
| 手动运行全部卡点 | `pre-commit run --all-files` |
| 跳过本次卡点 | `git commit --no-verify` |
| 手动同步到 OSS（不推送） | `python scripts/publish_open_source.py --oss-repo ../Conclave-OSS` |
| 干跑查看同步内容 | `python scripts/publish_open_source.py --oss-repo ../Conclave-OSS --dry-run` |
| 启动开发版 | `docker compose up -d`（在 `Conclave` 目录，使用 `docker-compose.yml`） |
| 启动开源版 | `docker compose up -d`（在 `Conclave-OSS` 目录，使用同步后的 `docker-compose.yml`） |
