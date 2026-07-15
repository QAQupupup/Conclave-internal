#!/bin/bash
# ===== Conclave 后端启动入口 =====
# 不使用 set -e：镜像拉取/构建失败不应阻止后端启动（沙箱是可选功能）
set -u  # 未定义变量时报错

APP_UID=1000
APP_GID=1000
APP_USER=app
SANDBOX_IMAGE="${CONCLAVE_SANDBOX_IMAGE:-swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/python:3.12-slim}"
DATASCIENCE_IMAGE="${CONCLAVE_SANDBOX_IMAGE_DATASCIENCE:-conclave-python-datascience:latest}"
DATASCIENCE_DOCKERFILE="${DATASCIENCE_DOCKERFILE:-/app/docker/sandbox-datascience/Dockerfile}"

echo "[entrypoint] Conclave backend starting..."

# ---- 0. 时区配置 ----
TZ="${TZ:-Asia/Shanghai}"
if [ -f "/usr/share/zoneinfo/$TZ" ]; then
    ln -sf "/usr/share/zoneinfo/$TZ" /etc/localtime
    echo "$TZ" > /etc/timezone
    echo "[entrypoint] Timezone set to $TZ"
else
    echo "[entrypoint] WARNING: Timezone $TZ not found, using UTC"
fi

# 确保 app 用户存在（Dockerfile 中已创建，这里做兜底）
if ! id "$APP_USER" >/dev/null 2>&1; then
    groupadd -g "$APP_GID" "$APP_USER" 2>/dev/null || true
    useradd -u "$APP_UID" -g "$APP_GID" -m -d /home/app -s /bin/bash "$APP_USER" 2>/dev/null || true
fi
mkdir -p /home/app/.docker /workspace /app/data
chown -R "$APP_UID:$APP_GID" /home/app /workspace /app/data 2>/dev/null || true

# ---- 1. Docker socket 权限自动配置 ----
DOCKER_READY=0
if [ -S /var/run/docker.sock ]; then
    SOCK_PERMS=$(stat -c '%a' /var/run/docker.sock)
    SOCK_UID=$(stat -c '%u' /var/run/docker.sock)
    SOCK_GID=$(stat -c '%g' /var/run/docker.sock)
    echo "[entrypoint] Docker socket: uid=$SOCK_UID gid=$SOCK_GID perms=$SOCK_PERMS"

    # 方法 A：socket 是 root:root 且权限为 660/600 → 需要将 app 加入 root 组
    if [ "$SOCK_GID" = "0" ] && [ "$SOCK_UID" = "0" ]; then
        # Docker Desktop (Windows/macOS) 的 socket 是 root:root 660
        # 将 app 加入 root 组(gid=0)即可读 socket
        usermod -aG 0 "$APP_USER" 2>/dev/null || true
        echo "[entrypoint] Added $APP_USER to root group (gid=0) for Docker Desktop socket access"
        # 只读挂载时 chmod 会失败，忽略
        chmod a+r /var/run/docker.sock 2>/dev/null && \
            echo "[entrypoint] Set socket world-readable" || \
            true
    fi

    # 方法 B：socket 属于一个非 root 组（宿主 docker 组）→ 将 app 用户加入该组
    if [ "$SOCK_GID" != "0" ]; then
        EXISTING_GROUP=$(getent group "$SOCK_GID" 2>/dev/null | cut -d: -f1 || true)
        if [ -z "$EXISTING_GROUP" ]; then
            groupadd -g "$SOCK_GID" docker-host 2>/dev/null || true
            EXISTING_GROUP="docker-host"
        fi
        usermod -aG "$EXISTING_GROUP" "$APP_USER" 2>/dev/null || true
        echo "[entrypoint] Added $APP_USER to group $EXISTING_GROUP (gid=$SOCK_GID)"
    fi

    # 方法 C：如果以上都不行，最后尝试 chmod 666
    # SECURITY: chmod 666 允许容器内所有用户读写 Docker socket，存在安全风险。
    # 在生产多用户主机上，请设置 CONCLAVE_DISABLE_CHMOD666=1 禁用此 fallback，
    # 并通过正确配置 docker 组 GID 映射来授予权限。
    if ! su -s /bin/bash "$APP_USER" -c "docker version --format '{{.Server.Version}}'" >/dev/null 2>&1; then
        if [ "${CONCLAVE_DISABLE_CHMOD666:-0}" = "1" ]; then
            echo "[entrypoint] SECURITY: chmod 666 fallback disabled by CONCLAVE_DISABLE_CHMOD666=1"
        else
            echo "[entrypoint] WARNING: Using chmod 666 fallback for Docker socket - this is insecure on multi-user hosts"
            chmod 666 /var/run/docker.sock 2>/dev/null && \
                echo "[entrypoint] Set socket 666 as fallback" || true
        fi
    fi

    # 验证
    if su -s /bin/bash "$APP_USER" -c "docker version --format '{{.Server.Version}}'" >/dev/null 2>&1; then
        DOCKER_VER=$(su -s /bin/bash "$APP_USER" -c "docker version --format '{{.Server.Version}}'" 2>/dev/null)
        echo "[entrypoint] Docker daemon accessible as $APP_USER: v$DOCKER_VER"
        DOCKER_READY=1
    else
        echo "[entrypoint] WARNING: Docker CLI cannot reach daemon as $APP_USER"
        # root 能否访问？
        if docker version --format '{{.Server.Version}}' >/dev/null 2>&1; then
            DOCKER_VER=$(docker version --format '{{.Server.Version}}' 2>/dev/null)
            echo "[entrypoint] Docker works as root (v$DOCKER_VER) but not as $APP_USER - socket permission issue"
        fi
        DOCKER_READY=0
    fi
else
    echo "[entrypoint] No Docker socket mounted at /var/run/docker.sock"
    DOCKER_READY=0
fi

# ---- 2. 预拉取沙箱镜像（以 app 用户执行，避免 root 拥有 ~/.docker） ----
if [ "$DOCKER_READY" = "1" ]; then
    echo "[entrypoint] Ensuring sandbox image: $SANDBOX_IMAGE"
    if su -s /bin/bash "$APP_USER" -c "docker image inspect '$SANDBOX_IMAGE' 2>/dev/null" >/dev/null 2>&1; then
        echo "[entrypoint] Sandbox image already present locally"
    else
        echo "[entrypoint] Pulling sandbox image (may take a moment)..."
        if su -s /bin/bash "$APP_USER" -c "docker pull '$SANDBOX_IMAGE'" 2>&1; then
            echo "[entrypoint] Sandbox image pulled successfully"
        else
        echo "[entrypoint] Primary pull failed, trying fallback swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/python:3.12-slim..."
        su -s /bin/bash "$APP_USER" -c "docker pull swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/python:3.12-slim" 2>&1 || echo "[entrypoint] WARNING: fallback pull also failed"
    fi
    fi

    # ---- 3. 构建数据科学沙箱镜像 ----
    if [ -f "$DATASCIENCE_DOCKERFILE" ]; then
        if su -s /bin/bash "$APP_USER" -c "docker image inspect '$DATASCIENCE_IMAGE' 2>/dev/null" >/dev/null 2>&1; then
            echo "[entrypoint] Data-science sandbox image already present"
        else
            echo "[entrypoint] Building data-science sandbox image (pandas/numpy/matplotlib/sklearn...)..."
            DS_CONTEXT=$(dirname "$DATASCIENCE_DOCKERFILE")
            if su -s /bin/bash "$APP_USER" -c "docker build -t '$DATASCIENCE_IMAGE' -f '$DATASCIENCE_DOCKERFILE' '$DS_CONTEXT'" 2>&1 | tail -50; then
                echo "[entrypoint] Data-science image built successfully"
            else
                echo "[entrypoint] WARNING: Failed to build data-science image; analysis features will use standard image"
            fi
        fi
    else
        echo "[entrypoint] No data-science Dockerfile at $DATASCIENCE_DOCKERFILE, skipping build"
    fi
fi

# ---- 4. 最终权限确认 ----
chown -R "$APP_UID:$APP_GID" /workspace /app/data 2>/dev/null || true

echo "[entrypoint] Starting uvicorn as $APP_USER (uid=$APP_UID)..."
exec su -s /bin/bash "$APP_USER" -c "cd /app && exec python -m uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000"
