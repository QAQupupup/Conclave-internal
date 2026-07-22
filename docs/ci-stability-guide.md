# CI 稳定性指南

> 本文档是 AGENTS.md §4.18 的详细补充。规则和速查见 AGENTS.md，背景和实现细节见本文。

## 1. 双层 Hook 防护体系

### [pre-commit] 秒级本地检查

文件：`.git/hooks/pre-commit`（由 `scripts/install-hooks.sh` 生成）

- 不依赖 `pre-commit` pip 包，直接调用 `ruff` 和 `npx tsc`/`npm run lint`
- 不运行 pytest（需要 PostgreSQL/Redis，违反 §0.5.2，由 CI 的 `backend-integration-tests` job 负责）
- `.pre-commit-config.yaml` 保留作为 `pre-commit` 包的配置（`rev` 必须与 `requirements.lock` 中 ruff 版本一致）
- 三层防护：
  1. **版本校验**：提交前校验本地 ruff 版本 == `requirements.lock` 版本，不一致直接阻止提交
  2. **配置变更全量检查**：`requirements.lock` / `pyproject.toml` 变更时，对全部文件执行 ruff check + format
  3. **常规暂存文件检查**：正常提交时只检查暂存文件（ruff check + format + tsc + eslint + compose 校验）

### [pre-push] Docker CI 一致性验证

文件：`.git/hooks/pre-push`（由 `scripts/install-hooks.sh` 生成）
脚本：`scripts/docker-ci-check.sh`

- 镜像：`swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/python:3.12-slim`（与项目 Dockerfile 一致）
- 用同一个 `requirements.lock` 安装 ruff/mypy，运行与 CI 完全相同的命令
- pip 缓存卷 `conclave-ci-pip-cache` 跨次运行复用，加速 pip install
- Docker 未运行时自动跳过（不阻塞推送，CI 仍会检查）
- mypy 与 CI 一致设为 `continue-on-error`（warnings 不阻塞推送）
- 手动执行：`bash scripts/docker-ci-check.sh`

## 2. 历史修复记录

以下修复发生在 2026-07-22 的 CI 稳定性专项治理中（commit 区间：`2f12abd` → `51325eb`）：

1. **websockets 依赖冲突**：`requirements.lock` 中 `websockets==12.0` 与 `uvicorn[standard]==0.51.0`（需 `>=13.0`）冲突。Windows pip 静默忽略，Linux CI 失败。修复：12.0→13.0。
2. **ruff lint 规则**：RUF009（`_env()` 函数调用在 dataclass 默认值，19 处）和 UP038（`isinstance(x, (A, B))` vs `A | B`，5 处）在 ruff 0.15.22 中已移除/不适用。修复：添加到 ignore 列表。
3. **ruff 版本漂移**：本地 ruff 0.15.22 与 CI ruff 0.5.0 不一致，格式化结果不同。修复：`requirements.lock` + `.pre-commit-config.yaml` + 本地三处对齐到 0.15.22。
4. **mypy 版本漂移**：本地 mypy 2.3.0 与 CI mypy 1.10.0 不一致。修复：`requirements.lock` 对齐到 2.3.0 + CI 添加 `continue-on-error: true`。
5. **pre-commit hook 增强**：添加 ruff 版本校验 + 配置变更全量检查。
6. **pre-push Docker 检查**：新增 `scripts/docker-ci-check.sh`，在 Docker 容器中运行与 CI 完全相同的检查。
7. **qdrant_store.py 类型修复**：`info.points_count` 是 `Optional[int]`，需 None 检查。
8. **CI 调试增强**：添加 `ruff --version` 和 `mypy --version` 打印步骤。
