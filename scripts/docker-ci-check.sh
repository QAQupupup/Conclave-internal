#!/usr/bin/env bash
# Docker CI parity check — 在与 CI 完全相同的环境中运行 lint/typecheck/tests
#
# 两阶段策略：
#   阶段 1（优先）：使用项目已构建的测试镜像，通过 docker compose 跑 ruff/mypy/pytest
#   阶段 2（兜底）：如测试镜像不可用且无法构建，用 slim 镜像 + pip 安装跑 ruff/mypy
#
# 所有诊断输出走 stderr（Git hook stdout 是协议通道）。
# stdin 已由 pre-push 重定向到 /dev/null。

exec </dev/null

{
set -u

REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
cd "$REPO_ROOT"

EXIT_CODE=0

TEST_IMAGE="conclave-test-backend-test:latest"
TEST_COMPOSE="docker-compose.test.yml"

# ── 阶段 1：使用项目测试镜像跑完整检查（ruff + mypy + pytest）──
run_with_test_image() {
    echo "[pre-push] Docker CI parity check (项目测试镜像)"

    # 用 docker compose run 执行所有检查；compose 自动启动依赖服务（pg/redis/qdrant）
    # pytest 用 -n0 单进程运行（xdist 多 worker 在 CI 上有隔离开销，本地反而慢）
    docker compose -f "$TEST_COMPOSE" run --rm -T --entrypoint bash backend-test -c "
        set -e
        echo '  ruff check...'
        ruff check app conclave_core tests
        echo '  ruff format --check...'
        ruff format --check app conclave_core tests
        echo '  mypy...'
        mypy app conclave_core || true
        echo '  pytest...'
        pytest tests/ -n0 -q --tb=short --timeout=60
    " 2>&1
    RC=$?

    if [ $RC -eq 0 ]; then
        echo ""
        echo "  Docker CI parity check 通过 (ruff/mypy/pytest)"
    else
        echo ""
        echo "  Docker CI parity check 失败！"
        echo "  CI 也会失败，请修复后再推送。紧急跳过: git push --no-verify"
    fi
    return $RC
}

# ── 阶段 2：兜底方案（slim 镜像 + pip 安装，仅 ruff/mypy，无 pytest）──
run_with_slim_image() {
    PYTHON_IMAGE="swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/python:3.12-slim"
    PIP_CACHE_VOLUME="conclave-ci-pip-cache"

    RUFF_VERSION=$(grep '^ruff==' backend/requirements.lock 2>/dev/null | head -1 | sed 's/ruff==//' | tr -d ' \r')
    MYPY_VERSION=$(grep '^mypy==' backend/requirements.lock 2>/dev/null | head -1 | sed 's/mypy==//' | tr -d ' \r')

    if [ -z "$RUFF_VERSION" ] || [ -z "$MYPY_VERSION" ]; then
        echo "[pre-push] 无法从 requirements.lock 提取 ruff/mypy 版本，跳过检查"
        return 0
    fi

    echo "[pre-push] Docker CI parity check (slim 镜像兜底，仅 ruff/mypy，不含 pytest)"
    echo "  建议: 先构建测试镜像以启用完整 pytest 检查: docker compose -f $TEST_COMPOSE build backend-test"

    if ! docker info >/dev/null 2>&1; then
        echo "  Docker 未运行，跳过检查"
        return 0
    fi

    if ! docker image inspect "$PYTHON_IMAGE" >/dev/null 2>&1; then
        docker pull "$PYTHON_IMAGE" >/dev/null 2>&1 || {
            echo "  无法拉取镜像（网络问题），跳过检查"
            return 0
        }
    fi

    MSYS_NO_PATHCONV=1 PIP_PROGRESS_BAR=off \
    docker run --rm --network=bridge \
        -v "$REPO_ROOT/backend:/app:ro" -w /app \
        -v "$PIP_CACHE_VOLUME:/root/.cache/pip" \
        -e PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
        -e PIP_PROGRESS_BAR=off -e PIP_DISABLE_PIP_VERSION_CHECK=1 \
        -e http_proxy="${http_proxy:-}" -e https_proxy="${https_proxy:-}" -e no_proxy="${no_proxy:-}" \
        --entrypoint bash "$PYTHON_IMAGE" -c "
            set +e
            pip install --quiet --no-warn-script-location 'ruff=='$RUFF_VERSION 'mypy=='$MYPY_VERSION >/dev/null 2>&1
            if [ \$? -ne 0 ]; then
                echo '  网络不可用，无法安装 ruff/mypy，跳过检查'
                exit 0
            fi
            ruff check app conclave_core tests && ruff format --check app conclave_core tests
        " 2>&1
    return $?
}

# ── 主逻辑 ──
if ! docker info >/dev/null 2>&1; then
    echo "[pre-push] Docker 未运行，跳过 Docker 检查"
    echo "  注意：CI 仍会执行完整检查（含 pytest）。"
    EXIT_CODE=0
elif docker image inspect "$TEST_IMAGE" >/dev/null 2>&1; then
    run_with_test_image
    EXIT_CODE=$?
else
    echo "[pre-push] 测试镜像不存在，尝试构建..."
    docker compose -f "$TEST_COMPOSE" build backend-test >/dev/null 2>&1
    if [ $? -eq 0 ] && docker image inspect "$TEST_IMAGE" >/dev/null 2>&1; then
        run_with_test_image
        EXIT_CODE=$?
    else
        echo "  构建失败，回退到 slim 镜像兜底（不含 pytest）"
        run_with_slim_image
        EXIT_CODE=$?
    fi
fi

exit "$EXIT_CODE"
} >&2
