#!/usr/bin/env bash
# Docker CI parity check — 在与 CI 完全相同的 Linux 环境中运行 ruff/mypy
#
# 用途：
#   1. pre-push hook 自动调用（防止版本漂移导致 CI 失败）
#   2. 手动执行：bash scripts/docker-ci-check.sh
#
# 原理：
#   CI 从 requirements.lock 安装 ruff/mypy，本地可能装了不同版本。
#   此脚本在 Docker 容器中安装与 requirements.lock 完全相同版本的
#   ruff 和 mypy，运行与 CI 相同的命令，确保"本地通过 = CI 通过"。
#
# 性能：
#   首次运行 ~15s（拉镜像 + pip install ruff+mypy），后续 ~3s（pip cache 命中）
#   注意：不安装完整 requirements.lock（那需要编译工具且很慢），
#   仅安装 ruff 和 mypy 两个纯 wheel 包，保证版本一致即可。
#
# 跳过：git push --no-verify（紧急情况）
#
# 注意：所有诊断输出重定向到 stderr（>&2）。
# Git hooks 的 stdout 用于协议通信，在 PowerShell/Git Bash 环境下
# 向 stdout 写入可能触发 "Bad file descriptor" 错误导致 hook 误报失败。

set -eo pipefail

# 将后续所有输出重定向到 stderr，避免 fd 问题
exec >&2

REPO_ROOT=$(git rev-parse --show-toplevel)

# Docker 镜像（python:slim 足够运行 ruff/mypy，无需构建工具）
PYTHON_IMAGE="swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/python:3.12-slim"

# pip 缓存卷（跨次运行复用，加速 pip install）
PIP_CACHE_VOLUME="conclave-ci-pip-cache"

# 从 requirements.lock 提取 ruff 和 mypy 的精确版本
RUFF_VERSION=$(grep '^ruff==' "$REPO_ROOT/backend/requirements.lock" | head -1 | sed 's/ruff==//' | tr -d ' \r')
MYPY_VERSION=$(grep '^mypy==' "$REPO_ROOT/backend/requirements.lock" | head -1 | sed 's/mypy==//' | tr -d ' \r')

if [ -z "$RUFF_VERSION" ] || [ -z "$MYPY_VERSION" ]; then
    echo "[pre-push] 无法从 requirements.lock 提取 ruff/mypy 版本，跳过检查"
    exit 0
fi

# 检查 Docker 是否可用
if ! docker info >/dev/null 2>&1; then
    echo "[pre-push] Docker 未运行，跳过 Docker CI 检查"
    echo "  注意：CI 仍会执行完整检查。请确保本地已通过 ruff/mypy。"
    echo "  启动 Docker Desktop 后可获得 CI 环境一致性验证。"
    exit 0
fi

echo "[pre-push] Docker CI parity check (backend)"
echo "  镜像: $PYTHON_IMAGE"
echo "  ruff==$RUFF_VERSION  mypy==$MYPY_VERSION"
echo ""

EXIT_CODE=0

# MSYS_NO_PATHCONV=1 防止 Git Bash on Windows 将 /app 转换为 Windows 路径
MSYS_NO_PATHCONV=1 docker run --rm \
    -v "$REPO_ROOT/backend:/app" \
    -w /app \
    -v "$PIP_CACHE_VOLUME:/root/.cache/pip" \
    -e PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    -e http_proxy="${http_proxy:-}" \
    -e https_proxy="${https_proxy:-}" \
    -e no_proxy="${no_proxy:-}" \
    "$PYTHON_IMAGE" \
    bash -c "
        set -eo pipefail
        echo '  安装 ruff==$RUFF_VERSION mypy==$MYPY_VERSION...'
        if ! pip install --quiet ruff==$RUFF_VERSION mypy==$MYPY_VERSION 2>&1; then
            echo '  网络不可用，无法安装 ruff/mypy，跳过 Docker 检查'
            echo '  （这通常是因为 Docker 容器无法访问外网，请配置 Docker Desktop 代理）'
            echo '  CI 仍会执行完整检查。'
            exit 0
        fi
        echo ''
        echo '  ruff --version'
        ruff --version
        echo ''
        echo '  ruff check app conclave_core tests'
        ruff check app conclave_core tests
        echo ''
        echo '  ruff format --check app conclave_core tests'
        ruff format --check app conclave_core tests
        echo ''
        echo '  mypy --version'
        mypy --version
        echo ''
        echo '  mypy app conclave_core (continue-on-error, 与 CI 一致)'
        mypy app conclave_core || {
            echo '  mypy 有 warnings（CI 中设为 continue-on-error，不阻塞）'
            echo '  建议修复以保持类型安全'
        }
        echo ''
        echo '  Docker CI parity check 通过'
    " || EXIT_CODE=$?

if [ $EXIT_CODE -ne 0 ]; then
    echo ""
    echo "  Docker CI parity check 失败！"
    echo "  这意味着 CI 也会失败。请修复后再推送。"
    echo "  跳过（紧急情况）: git push --no-verify"
    echo "  参考: AGENTS.md 4.18 CI 稳定性纪律"
fi

exit $EXIT_CODE
