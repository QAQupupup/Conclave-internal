# Conclave 开发版与开源版隔离及自动同步改动汇总

> 本文汇总了 2026-07-13 围绕「开发仓库 / 开源仓库 / CI/CD / Docker Compose 命名空间」所做改动的目的、规则与落地方式。

---

## 1. 背景与目标

### 1.1 为什么要做这些改动

- **核心算法与知识产权隔离**：`conclave_core` 中的核心算法源码只在私有开发仓库维护，对外发布时替换为编译后的二进制扩展（`.so`/`.pyd`）+ 必要的 `__init__.py`。
- **开发版与开源版并行运行**：本地需要同时调试开发版和开源版 Docker Compose，必须避免容器名、卷名、端口冲突。
- **自动同步 + 人工审批**：日常开发在私有仓库进行，CI 通过后自动同步到开源仓库的 `auto-sync` 分支；合并到 `release`/`main` 仍然由人工决定。
- **本地网络不稳定时的兜底**：开发机到 GitHub 网络不稳定时，可通过 SSH 隧道 + SOCKS5 代理让 Git/浏览器流量经阿里云 ECS 转发（这部分属于本地环境配置，不在代码仓库中）。

---

## 2. 核心改动清单

### 2.1 前端 UI 与交互

| 文件 | 改动说明 |
|------|---------|
| `frontend/src/App.tsx` | 值守按钮改为「常态浅蓝色小盾牌 + 悬停展开值守面板 + 移出 800ms 自动收回」的吸边设计，避免遮挡右上角主题/设置按钮。 |
| `frontend/src/components/TaskBoard.tsx` | 会议列表表格增加行垂直居中对齐；议题单元格改为 `inline-flex`，与行内其他单元格垂直对齐。 |
| `frontend/src/components/ModelsView.tsx` | 厂商卡片增加 `models-provider-card` 类，统一图标、名称、底部标签的对齐。 |
| `frontend/src/index.css` | 新增 `.task-board` 行垂直居中、`.models-provider-card` 卡片底部对齐样式。 |

### 2.2 Docker Compose 命名空间隔离

| 文件 | 改动说明 |
|------|---------|
| `docker-compose.yml` | 开发版使用 `name: conclave-dev`，所有容器/卷名以 `conclave-dev-` 为前缀。 |
| `docker-compose.oss.yml` | 新增开源版源配置，使用 `name: conclave-oss`，端口与开发版错开。 |
| `scripts/oss_manifest.json` | 将同步源从 `docker-compose.yml` 改为 `docker-compose.oss.yml`，发布时成为开源仓库的 `docker-compose.yml`。 |

端口隔离对照：

| 服务 | 开发版 | 开源版 |
|------|--------|--------|
| 前端 | 5173 | 5174 |
| 后端 | 8000 | 8001 |
| noVNC | 6080 | 6081 |
| Qdrant | 6333/6334 | 6335/6336 |
| Postgres | 5432 | 5433 |
| Redis | 6379 | 6380 |

### 2.3 CI/CD 与本地卡点

| 文件 | 改动说明 |
|------|---------|
| `.github/workflows/ci.yml` | 后端检查（ruff、mypy、pytest）、前端检查（ESLint、tsc、build）、Compose 校验（同时校验 dev 与 OSS）。 |
| `.github/workflows/release-oss.yml` | CI 通过后自动调用 `publish_open_source.py --branch auto-sync --push`，把可开源内容同步到开源仓库。 |
| `.pre-commit-config.yaml` | 本地提交卡点：ruff、pytest smoke、tsc、npm build（push 阶段）、dev/OSS Compose 校验、manifest JSON 校验。 |
| `scripts/install-hooks.ps1` | Windows 下安装 pre-commit hooks 的脚本。 |
| `scripts/publish_open_source.py` | 增加 `--branch` 参数，支持指定推送到的开源分支（默认 `auto-sync`）。 |

### 2.4 流程文档

| 文件 | 改动说明 |
|------|---------|
| `.trae/documents/open-source-release-flow.md` | 定义仓库/分支模型、卡点规则、自动同步规则、CI/CD 配置方法、Docker Compose 隔离表、常见命令速查。 |
| `.trae/documents/development-oss-sync-summary.md` | 本文档，汇总上述所有改动的目的与规则。 |

---

## 3. 发布与同步规则

### 3.1 仓库与分支模型

| 仓库 | 可见性 | 关键分支 | 用途 |
|------|--------|---------|------|
| `Conclave` | private | `main` / `refactor/v3-manager-agent-runtime` | 日常开发、敏感算法、内部文档 |
| `Conclave-OSS` | public | `auto-sync` / `release` / `main` | 开源发布、可审计代码 |

### 3.2 分支流转规则

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
  人工决定：创建 PR auto-sync → release
        │
        ▼
  人工决定：创建 PR release → main
```

- `auto-sync`：机器自动维护，**禁止人工直接推送**。
- `release`：发布候选分支，人工审批。
- `main`：稳定发布分支，人工审批。

### 3.3 清单驱动同步

- 同步清单：`scripts/oss_manifest.json`。
- 白名单复制：只有清单中列出的文件/目录才会进入开源版。
- 增量同步：基于 SHA256 哈希，只复制变更文件。
- 源码保护：`backend/conclave_core` 中的 `.py` 源码会被删除，仅保留二进制扩展和 `__init__.py`。
- 审计报告：每次同步生成 `AUDIT_REPORT.md`。

---

## 4. CI/CD 卡点规则

### 4.1 本地提交卡点（pre-commit）

安装方式：

```powershell
.\scripts\install-hooks.ps1
```

提交时自动运行：

| 卡点 | 范围 |
|------|------|
| ruff lint + format | `backend/app`、`conclave_core`、`tests`、`scripts` |
| pytest smoke | 后端测试 |
| tsc --noEmit | 前端 TypeScript |
| docker compose config | `docker-compose.yml` + `docker-compose.oss.yml` |
| JSON 校验 | `scripts/oss_manifest.json` |
| npm run build | 前端生产构建（push 阶段） |

### 4.2 CI 卡点（GitHub Actions）

- `ci.yml`：push / PR 到 `main` 或 `refactor/v3-manager-agent-runtime` 时触发。
- `release-oss.yml`：`ci.yml` 成功且仓库为开发版时触发，自动同步到开源仓库。

---

## 5. GitHub Secrets 配置

已在开发仓库配置：

| Secret | 说明 |
|--------|------|
| `OSS_DEPLOY_KEY` | 能写开源仓库的 SSH 私钥 |
| `OSS_REPO_URL` | 开源仓库 SSH 地址，例如 `git@github.com:QAQupupup/Conclave-OSS.git` |

开源仓库需配置对应的 Deploy Key 公钥，并勾选 **Write access**。

---

## 6. 本地 SOCKS5 代理（可选）

当本地到 GitHub 网络不稳定时，可通过阿里云 ECS 建立 SSH 隧道：

```powershell
ssh -D 1080 -N -q dev
```

浏览器：ZeroOmega 配置 SOCKS5 `127.0.0.1:1080`。

Git HTTPS（当前终端临时生效）：

```powershell
$env:HTTP_PROXY="socks5://127.0.0.1:1080"
$env:HTTPS_PROXY="socks5://127.0.0.1:1080"
```

注意：代理未开启时，配置了全局代理的 Git 会报错。日常推荐用环境变量临时启用，或把代理配置限定在 SSH 的 `Host github.com` 段。

---

## 7. 常用命令速查

| 目标 | 命令 |
|------|------|
| 安装本地提交卡点 | `.\scripts\install-hooks.ps1` |
| 手动运行全部卡点 | `pre-commit run --all-files` |
| 手动同步到 OSS（不推送） | `python scripts/publish_open_source.py --oss-repo ../Conclave-OSS` |
| 干跑查看同步内容 | `python scripts/publish_open_source.py --oss-repo ../Conclave-OSS --dry-run` |
| 启动开发版 | `docker compose up -d`（在 `Conclave` 目录） |
| 启动开源版 | `docker compose up -d`（在 `Conclave-OSS` 目录） |

---

## 8. 关键注意事项

1. **不要手动修改 `Conclave-OSS` 仓库的 `auto-sync` 分支**：该分支由 CI 自动维护，人工修改会被下次同步覆盖。
2. **新增文件默认不会进入开源版**：必须显式加入 `scripts/oss_manifest.json` 的 `copy` 列表。
3. **Windows 本地同步时跳过核心编译**：因为 Windows 主机编译出来的是 `.pyd`，而 OSS Docker 镜像需要 Linux 的 `.so`。CI 在 Ubuntu  runner 上会自动完成正确的编译。
4. **命名空间隔离已验证**：dev 与 OSS 的容器名、卷名、网络名、端口均不冲突，可以同时启动。
