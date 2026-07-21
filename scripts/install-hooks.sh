#!/usr/bin/env bash
# Conclave Git Hooks 安装脚本
# 用法：bash scripts/install-hooks.sh
#
# 安装 pre-commit hook 到 .git/hooks/pre-commit
# 无需 pip install pre-commit，直接用 ruff + tsc 做本地卡点
# 前提：ruff 和 node 已安装并在 PATH 中

set -e

HOOK_DIR=".git/hooks"
HOOK_FILE="$HOOK_DIR/pre-commit"

mkdir -p "$HOOK_DIR"

cat > "$HOOK_FILE" << 'HOOK_EOF'
#!/usr/bin/env bash
# Conclave pre-commit hook（无需 pre-commit 包）
# 卡点：ruff check + ruff format --check + 前端 tsc + eslint
# 集成测试不在 hook 中运行（需要 Docker + PG + Redis），由 CI 负责

set -e

# 获取暂存的文件
STAGED_PY=$(git diff --cached --name-only --diff-filter=ACM | grep '^backend/.*\.py$' || true)
STAGED_TS=$(git diff --cached --name-only --diff-filter=ACM | grep '^frontend/.*\.\(ts\|tsx\)$' || true)
STAGED_COMPOSE=$(git diff --cached --name-only --diff-filter=ACM | grep '^docker-compose.*\.yml$' || true)

EXIT_CODE=0

# ── Backend: ruff check + format ──
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
echo "Hook 检查项："
echo "  - Backend: ruff check + ruff format --check（仅暂存文件）"
echo "  - Frontend: tsc --noEmit + eslint（有 .ts/.tsx 变更时）"
echo "  - Docker Compose: config validation（有 compose yml 变更时）"
echo ""
echo "注意：集成测试（pytest）不在 hook 中运行，由 CI 负责（§0.5.2）"
echo "如需跳过 hook：git commit --no-verify（仅限紧急情况）"
