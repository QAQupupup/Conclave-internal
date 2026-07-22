#!/usr/bin/env bash
# Conclave Git Hooks 安装脚本
# 用法：bash scripts/install-hooks.sh
#
# 安装 pre-commit hook 到 .git/hooks/pre-commit
# 无需 pip install pre-commit，直接用 ruff + tsc 做本地卡点
# 前提：ruff 和 node 已安装并在 PATH 中
#
# 防护层级（防止 CI 反复失败）：
# 1. ruff 版本校验：本地 ruff 版本必须与 requirements.lock 一致
# 2. 配置变更全量检查：当 requirements.lock / pyproject.toml 变更时，检查全部文件
# 3. 常规暂存文件检查：正常提交时只检查暂存的文件

set -e

HOOK_DIR=".git/hooks"
HOOK_FILE="$HOOK_DIR/pre-commit"

mkdir -p "$HOOK_DIR"

cat > "$HOOK_FILE" << 'HOOK_EOF'
#!/usr/bin/env bash
# Conclave pre-commit hook（无需 pre-commit 包）
# 卡点：ruff 版本校验 + ruff check + ruff format --check + 前端 tsc + eslint
# 集成测试不在 hook 中运行（需要 Docker + PG + Redis），由 CI 负责
#
# 防护层级：
# 1. ruff 版本校验：防止本地/CI 版本漂移导致格式不一致（§4.18 根因）
# 2. 配置变更全量检查：ruff 版本/规则变更可能影响所有文件，必须全量检查
# 3. 常规暂存文件检查：只检查本次变更的文件

set -e

# 获取暂存的文件
STAGED_PY=$(git diff --cached --name-only --diff-filter=ACM | grep '^backend/.*\.py$' || true)
STAGED_TS=$(git diff --cached --name-only --diff-filter=ACM | grep '^frontend/.*\.\(ts\|tsx\)$' || true)
STAGED_COMPOSE=$(git diff --cached --name-only --diff-filter=ACM | grep '^docker-compose.*\.yml$' || true)
STAGED_RUFF_CONFIG=$(git diff --cached --name-only --diff-filter=ACM | grep -E '^backend/(requirements\.lock|pyproject\.toml)$' || true)

EXIT_CODE=0

# ── Ruff 版本校验（防止本地/CI 版本漂移）──
# 根因：CI 从 requirements.lock 安装 ruff，本地可能装了不同版本
# 版本不一致 → 格式化结果不同 → 本地通过但 CI 失败
if [ -n "$STAGED_PY" ] || [ -n "$STAGED_RUFF_CONFIG" ]; then
    EXPECTED_RUFF=$(grep '^ruff==' backend/requirements.lock | head -1 | sed 's/ruff==//' | tr -d ' \r')
    LOCAL_RUFF=$(python -m ruff --version 2>/dev/null | sed 's/ruff //' | tr -d ' \r')
    if [ -z "$LOCAL_RUFF" ]; then
        echo "✗ 未检测到 ruff，请安装: pip install ruff==$EXPECTED_RUFF"
        EXIT_CODE=1
    elif [ "$EXPECTED_RUFF" != "$LOCAL_RUFF" ]; then
        echo "✗ Ruff 版本不一致！这是 CI 反复失败的最常见根因。"
        echo "  requirements.lock 要求: ruff==$EXPECTED_RUFF"
        echo "  本地安装版本:           ruff==$LOCAL_RUFF"
        echo "  修复: pip install ruff==$EXPECTED_RUFF"
        echo "  参考: AGENTS.md §4.18 CI 稳定性纪律"
        EXIT_CODE=1
    fi
fi

# 如果版本校验失败，跳过后续 ruff 检查（版本不对检查结果也不可信）
if [ $EXIT_CODE -ne 0 ]; then
    # 仍然检查前端（如果有前端变更）
    if [ -n "$STAGED_TS" ]; then
        echo "▶ Frontend tsc type check..."
        cd frontend
        if ! npx tsc --noEmit 2>&1; then
            echo "✗ TypeScript 类型检查失败"
            EXIT_CODE=1
        fi
        echo "▶ Frontend eslint..."
        if ! npm run lint 2>&1; then
            echo "✗ ESLint 检查失败"
            EXIT_CODE=1
        fi
        cd ..
    fi
    exit $EXIT_CODE
fi

# ── 当 requirements.lock 或 pyproject.toml 变更时，全量检查 ──
# 原因：ruff 版本升级或规则变更可能影响所有文件的格式和 lint 结果
# 只检查暂存文件会漏掉未变更但受影响的其他文件
if [ -n "$STAGED_RUFF_CONFIG" ]; then
    echo "▶ 检测到 ruff 配置/版本变更，执行全量检查（防止版本变更影响未暂存文件）..."
    cd backend
    if ! python -m ruff check app conclave_core tests; then
        echo "✗ ruff check 失败（全量检查）"
        echo "  提示：运行 cd backend && python -m ruff check --fix app conclave_core tests"
        EXIT_CODE=1
    fi
    if ! python -m ruff format --check app conclave_core tests; then
        echo "✗ ruff format 检查失败（全量检查）"
        echo "  提示：运行 cd backend && python -m ruff format app conclave_core tests"
        EXIT_CODE=1
    fi
    cd ..
fi

# ── Backend: ruff check + format（仅暂存文件）──
if [ -n "$STAGED_PY" ]; then
    echo "▶ Backend ruff check..."
    cd backend
    # 只检查暂存的 Python 文件（相对于 backend/ 目录）
    PY_FILES=$(echo "$STAGED_PY" | sed 's|^backend/||' | tr '\n' ' ')
    if ! python -m ruff check $PY_FILES; then
        echo "✗ ruff check 失败，请修复后再提交"
        echo "  提示：运行 cd backend && python -m ruff check --fix app conclave_core tests"
        EXIT_CODE=1
    fi
    echo "▶ Backend ruff format check..."
    if ! python -m ruff format --check $PY_FILES; then
        echo "✗ ruff format 检查失败，请格式化后再提交"
        echo "  提示：运行 cd backend && python -m ruff format app conclave_core tests"
        EXIT_CODE=1
    fi
    cd ..
fi

# ── Frontend: tsc + eslint ──
if [ -n "$STAGED_TS" ]; then
    echo "▶ Frontend tsc type check..."
    cd frontend
    if ! npx tsc --noEmit 2>&1; then
        echo "✗ TypeScript 类型检查失败"
        EXIT_CODE=1
    fi
    echo "▶ Frontend eslint..."
    if ! npm run lint 2>&1; then
        echo "✗ ESLint 检查失败"
        EXIT_CODE=1
    fi
    cd ..
fi

# ── Docker Compose 配置校验 ──
if [ -n "$STAGED_COMPOSE" ]; then
    echo "▶ Docker Compose config validation..."
    for f in $STAGED_COMPOSE; do
        if ! docker compose -f "$f" config --quiet 2>&1; then
            echo "✗ $f 配置校验失败"
            EXIT_CODE=1
        fi
    done
fi

if [ $EXIT_CODE -eq 0 ]; then
    echo "✓ Pre-commit checks passed"
fi

exit $EXIT_CODE
HOOK_EOF

chmod +x "$HOOK_FILE"
echo "✓ Pre-commit hook installed to $HOOK_FILE"
echo ""
echo "Hook 检查项（三层防护）："
echo "  1. Ruff 版本校验：本地 ruff 必须与 requirements.lock 一致（防止版本漂移）"
echo "  2. 配置变更全量检查：requirements.lock / pyproject.toml 变更时检查全部文件"
echo "  3. 常规检查：ruff check + format（暂存文件）+ tsc + eslint + compose 校验"
echo ""
echo "注意：集成测试（pytest）不在 hook 中运行，由 CI 负责（§0.5.2）"
echo "如需跳过 hook：git commit --no-verify（仅限紧急情况）"
