#!/bin/bash
# Conclave Gitea 自动初始化 entrypoint
# 首次启动：自动生成配置 + 创建管理员 + 创建默认组织，零人工干预
# 后续启动：直接启动服务

set -e

GITEA_BIN="/usr/local/bin/gitea"
GITEA_CONF="/data/gitea/conf/app.ini"
INIT_MARKER="/data/.conclave-init-done"
SU_EXEC="/sbin/su-exec"
ENV_TO_INI="/usr/local/bin/environment-to-ini"
GITEA_USER="git"

# ── 准备目录结构（需要 root 权限）──
for FOLDER in /data/gitea/conf /data/gitea/log /data/git /data/ssh; do
    mkdir -p ${FOLDER}
done

# 确保所有数据目录权限正确（git 用户需要读写）
chown -R ${GITEA_USER}:${GITEA_USER} /data

# ── 生成 app.ini（将环境变量写入配置文件）──
echo "[conclave-init] Generating app.ini from environment variables..."
${ENV_TO_INI} -config "${GITEA_CONF}" || true

# 确保 INSTALL_LOCK 已设置
if ! grep -q "INSTALL_LOCK" "${GITEA_CONF}" 2>/dev/null; then
    echo "[security]" >> "${GITEA_CONF}"
    echo "INSTALL_LOCK = true" >> "${GITEA_CONF}"
fi

# 确保文件权限正确
chown -R ${GITEA_USER}:${GITEA_USER} /data/gitea

# ── 首次启动：自动初始化 ──
if [ ! -f "${INIT_MARKER}" ]; then
    echo "[conclave-init] First boot detected. Starting auto-initialization..."

    # 以 git 用户启动 Gitea Web（后台，用于初始化 DB）
    ${SU_EXEC} ${GITEA_USER} ${GITEA_BIN} web -c "${GITEA_CONF}" &
    GITEA_PID=$!

    # 等待 Web 服务就绪
    echo "[conclave-init] Waiting for Gitea to be ready..."
    for i in $(seq 1 60); do
        if curl -sf http://localhost:3000/ > /dev/null 2>&1; then
            echo "[conclave-init] Gitea is ready."
            break
        fi
        sleep 2
    done

    # 以 git 用户创建管理员账号
    ADMIN_NAME="${GITEA_ADMIN_NAME:-conclave}"
    ADMIN_EMAIL="${GITEA_ADMIN_EMAIL:-admin@conclave.local}"
    ADMIN_PASSWORD="${GITEA_ADMIN_PASSWORD:-conclave_dev}"

    echo "[conclave-init] Creating admin user: ${ADMIN_NAME}..."
    ${SU_EXEC} ${GITEA_USER} ${GITEA_BIN} admin user create \
        -c "${GITEA_CONF}" \
        --username "${ADMIN_NAME}" \
        --password "${ADMIN_PASSWORD}" \
        --email "${ADMIN_EMAIL}" \
        --admin \
        --must-change-password=false && echo "[conclave-init] Admin user created." || echo "[conclave-init] Admin user creation failed or already exists."

    # 创建默认组织（Agent 协作仓库统一放在此组织下）
    echo "[conclave-init] Creating organization: conclave-agents..."
    ${SU_EXEC} ${GITEA_USER} ${GITEA_BIN} admin org create \
        -c "${GITEA_CONF}" \
        --username conclave-agents \
        --full-name "Conclave Agent Workspace" && echo "[conclave-init] Organization created." || echo "[conclave-init] Organization creation failed or already exists."

    # 写入初始化完成标记
    touch "${INIT_MARKER}"
    chown ${GITEA_USER}:${GITEA_USER} "${INIT_MARKER}"
    echo "[conclave-init] Auto-initialization complete!"

    # ── 打印凭证（醒目格式，方便用户查找）──
    echo ""
    echo "========================================================"
    echo "  Gitea Git 托管服务已就绪！"
    echo "========================================================"
    echo "  Web UI  : http://localhost:3000"
    echo "  API     : http://localhost:3000/api/v1"
    echo "  SSH     : localhost:3022"
    echo "--------------------------------------------------------"
    echo "  管理员  : ${ADMIN_NAME}"
    echo "  密  码  : ${ADMIN_PASSWORD}"
    echo "  邮  箱  : ${ADMIN_EMAIL}"
    echo "--------------------------------------------------------"
    echo "  组织    : conclave-agents (Agent 协作仓库)"
    echo "========================================================"
    echo "  修改密码: 在 .env 中设置 GITEA_ADMIN_PASSWORD 后重建"
    echo "========================================================"
    echo ""

    # 等待后台 Web 进程（容器保持运行）
    wait ${GITEA_PID}
else
    # ── 后续启动：直接启动服务 ──
    echo "[conclave-init] Initialization already done. Starting Gitea..."
    # 后续启动也打印访问信息（不含密码）
    ADMIN_NAME="${GITEA_ADMIN_NAME:-conclave}"
    echo ""
    echo "========================================================"
    echo "  Gitea Git 托管服务已启动"
    echo "========================================================"
    echo "  Web UI  : http://localhost:3000"
    echo "  API     : http://localhost:3000/api/v1"
    echo "  SSH     : localhost:3022"
    echo "  管理员  : ${ADMIN_NAME}"
    echo "========================================================"
    echo ""
    exec ${SU_EXEC} ${GITEA_USER} ${GITEA_BIN} web -c "${GITEA_CONF}"
fi
