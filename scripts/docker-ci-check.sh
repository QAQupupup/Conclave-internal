#!/usr/bin/env bash
# Docker CI parity check — 在与 CI 完全相同的 Linux 环境中运行 ruff/mypy
#
# 用途：
#   1. pre-push hook 自动调用（防止版本漂移导致 CI 失败）
#   2. 手动执行：bash scripts/docker-ci-check.sh
#
# 核心原则：所有输出走 stderr，不碰 stdout（Git hook stdout 是协议通道）

# ── fd 安全设置 ──
# 用 {} 将整个脚本体包裹并将 stdout 重定向到 stderr，
# 这是最可靠的方式，避免 exec 重定向与子 shell 的复杂交互。
# stdin 重定向到 /dev/null 防止 docker 子进程读取 git 协议管道数据。
exec </dev/null

{
set -u

REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)

PYTHON_IMAGE="swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/python:3.12-slim"
PIP_CACHE_VOLUME="conclave-ci-pip-cache"

RUFF_VERSION=$(grep '^ruff==' "$REPO_ROOT/backend/requirements.lock" 2>/dev/null | head -1 | sed 's/ruff==//' | tr -d ' \r')
MYPY_VERSION=$(grep '^mypy==' "$REPO_ROOT/backend/requirements.lock" 2>/dev/null | head -1 | sed 's/mypy==//' | tr -d ' \r')

if [ -z "$RUFF_VERSION" ] || [ -z "$MYPY_VERSION" ]; then
    echo "[pre-push] 无法从 requirements.lock 提取 ruff/mypy 版本，跳过检查"
    exit 0
fi

if ! docker info >/dev/null 2>&1; then
    echo "[pre-push] Docker 未运行，跳过 Docker CI 检查"
    echo "  注意：CI 仍会执行完整检查。请确保本地已通过 ruff/mypy。"
    exit 0
fi

echo "[pre-push] Docker CI parity check (backend)"
echo "  镜像: $PYTHON_IMAGE"
echo "  ruff==$RUFF_VERSION  mypy==$MYPY_VERSION"
echo ""

EXIT_CODE=0

if ! docker image inspect "$PYTHON_IMAGE" >/dev/null 2>&1; then
    echo "  镜像未本地存在，尝试拉取..."
    if ! docker pull "$PYTHON_IMAGE" >/dev/null 2>&1; then
        echo "  无法拉取 Docker 镜像（网络问题），跳过 Docker CI 检查"
        echo "  CI 仍会执行完整检查。"
        exit 0
    fi
fi

MSYS_NO_PATHCONV=1 \
PIP_PROGRESS_BAR=off \
docker run --rm \
    --network=bridge \
    -v "$REPO_ROOT/backend:/app:ro" \
    -w /app \
    -v "$PIP_CACHE_VOLUME:/root/.cache/pip" \
    -e PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    -e PIP_PROGRESS_BAR=off \
    -e PIP_DISABLE_PIP_VERSION_CHECK=1 \
    -e http_proxy="${http_proxy:-}" \
    -e https_proxy="${https_proxy:-}" \
    -e no_proxy="${no_proxy:-}" \
    --entrypoint bash \
    "$PYTHON_IMAGE" \
    -c "
        set +e
        echo '  安装 ruff=='$RUFF_VERSION' mypy=='$MYPY_VERSION'...'
        pip install --quiet --no-warn-script-location 'ruff=='$RUFF_VERSION 'mypy=='$MYPY_VERSION >/dev/null 2>&1
        if [ \$? -ne 0 ]; then
            echo '  网络不可用，无法安装 ruff/mypy，跳过 Docker 检查'
            echo '  （Docker 容器无法访问外网，请配置 Docker Desktop 代理）'
            echo '  CI 仍会执行完整检查。'
            exit 0
        fi
        echo ''
        echo '  ruff --version'
        ruff --version
        echo ''
        echo '  ruff check app conclave_core tests'
        ruff check app conclave_core tests
        RUFF_RC=\$?
        echo ''
        echo '  ruff format --check app conclave_core tests'
        ruff format --check app conclave_core tests
        FORMAT_RC=\$?
        echo ''
        echo '  mypy --version'
        mypy --version
        echo ''
        echo '  mypy app conclave_core (continue-on-error, 与 CI 一致)'
        mypy app conclave_core
        MYPY_RC=\$?
        if [ \$MYPY_RC -ne 0 ]; then
            echo '  mypy 有 warnings（CI 中 continue-on-error，不阻塞）'
            echo '  建议修复以保持类型安全'
        fi
        echo ''
        if [ \$RUFF_RC -eq 0 ] && [ \$FORMAT_RC -eq 0 ]; then
            echo '  Docker CI parity check 通过'
            exit 0
        else
            echo '  ruff 检查失败！'
            exit 1
        fi
    " 2>&1 || EXIT_CODE=$?

if [ "$EXIT_CODE" -ne 0 ]; then
    echo ""
    echo "  Docker CI parity check 失败！"
    echo "  这意味着 CI 也会失败。请修复后再推送。"
    echo "  紧急跳过: git push --no-verify"
fi

exit "$EXIT_CODE"
} >&2
