#!/usr/bin/env bash
# Docker CI parity check — 在与 CI 完全相同的 Linux 环境中运行 ruff/mypy
#
# 用途：
#   1. pre-push hook 自动调用（防止版本漂移导致 CI 失败）
#   2. 手动执行：bash scripts/docker-ci-check.sh
#
# 原理：
#   CI 从 requirements.lock 安装 ruff/mypy，本地可能装了不同版本。
#   此脚本在 Docker 容器中用同一个 requirements.lock 安装工具，
#   运行与 CI 完全相同的命令，确保"本地通过 = CI 通过"。
#
# 性能：
#   首次运行 ~30s（拉镜像 + pip install），后续 ~5s（pip cache volume 命中）
#
# 跳过：git push --no-verify（紧急情况）

set -e

REPO_ROOT=$(git rev-parse --show-toplevel)

# Docker 镜像（与项目 Dockerfile 一致，华为 SWR 加速）
PYTHON_IMAGE="swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/python:3.12-slim"

# pip 缓存卷（跨次运行复用，加速 pip install）
PIP_CACHE_VOLUME="conclave-ci-pip-cache"

# 检查 Docker 是否可用
if ! docker info >/dev/null 2>&1; then
    echo "⚠  Docker 未运行，跳过 pre-push Docker 检查"
    echo "   注意：CI 仍会执行完整检查。请确保本地已通过 ruff/mypy。"
    echo "   启动 Docker Desktop 后可获得 CI 环境一致性验证。"
    exit 0
fi

echo "▶ Pre-push: Docker CI parity check (backend)"
echo "  镜像: $PYTHON_IMAGE"
echo "  命令: ruff check + ruff format --check + mypy"
echo ""

# MSYS_NO_PATHCONV=1 防止 Git Bash on Windows 将 /app 转换为 Windows 路径
# 在 Linux/macOS 上此变量无副作用
EXIT_CODE=0

MSYS_NO_PATHCONV=1 docker run --rm \
    -v "$REPO_ROOT/backend:/app" \
    -w /app \
    -v "$PIP_CACHE_VOLUME:/root/.cache/pip" \
    -e PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    "$PYTHON_IMAGE" \
    bash -c '
        set -e
        echo "▶ 安装依赖 (requirements.lock)..."
        pip install --quiet -r requirements.lock 2>&1 | tail -3
        echo ""
        echo "▶ ruff --version"
        ruff --version
        echo ""
        echo "▶ ruff check app conclave_core tests"
        ruff check app conclave_core tests
        echo ""
        echo "▶ ruff format --check app conclave_core tests"
        ruff format --check app conclave_core tests
        echo ""
        echo "▶ mypy --version"
        mypy --version
        echo ""
        echo "▶ mypy app conclave_core (continue-on-error, 与 CI 一致)"
        mypy app conclave_core || {
            echo "⚠  mypy 有 warnings（CI 中设为 continue-on-error，不阻塞）"
            echo "   建议修复以保持类型安全"
        }
        echo ""
        echo "✓ Docker CI parity check 通过"
    ' || EXIT_CODE=$?

if [ $EXIT_CODE -ne 0 ]; then
    echo ""
    echo "✗ Docker CI parity check 失败！"
    echo "  这意味着 CI 也会失败。请修复后再推送。"
    echo "  跳过（紧急情况）: git push --no-verify"
    echo "  参考: AGENTS.md §4.18 CI 稳定性纪律"
fi

exit $EXIT_CODE
