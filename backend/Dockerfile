# ===== Conclave 后端 Dockerfile（四阶段构建，最大化缓存命中）=====
# 分层策略（从底到顶，变更频率递增）：
#   1. system-deps : apt 源配置 + 所有系统依赖（curl/gnupg/Xvfb/VNC/字体/docker-cli/Playwright 浏览器依赖）
#   2. playwright  : pip install playwright + playwright install chromium（~600MB，极少变更）
#   3. builder     : pip install requirements.txt（依赖变更时触发）
#   4. work        : COPY 前三层产物 + 源码（代码变更时只重建这一层）
#
# 运行时：entrypoint.sh 以 root 启动 → 配置 Docker socket 权限 → 预拉取沙箱镜像 → 降权到 uid 1000 运行 uvicorn

# ---------- 阶段 1: system-deps（系统依赖，最底层，永久缓存） ----------
FROM swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/python:3.12-slim AS system-deps

# pip 镜像源（国内加速）
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple

# === 替换 apt 源为清华 TUNA 镜像（兼容 Debian Bookworm/Trixie DEB822 格式）===
RUN rm -f /etc/apt/sources.list.d/*.sources /etc/apt/sources.list && \
    { echo "Types: deb"; \
      echo "URIs: https://mirrors.tuna.tsinghua.edu.cn/debian"; \
      echo "Suites: $(. /etc/os-release && echo $VERSION_CODENAME) $(. /etc/os-release && echo $VERSION_CODENAME)-updates"; \
      echo "Components: main"; \
      echo "Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg"; \
      echo ""; \
      echo "Types: deb"; \
      echo "URIs: https://mirrors.tuna.tsinghua.edu.cn/debian-security"; \
      echo "Suites: $(. /etc/os-release && echo $VERSION_CODENAME)-security"; \
      echo "Components: main"; \
      echo "Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg"; \
    } > /etc/apt/sources.list.d/tuna.sources

# 一次性安装所有系统依赖（减少镜像层数 + Docker cache 粒度最粗）
# 包含：
#   - curl/ca-certificates/gnupg : 基础工具 + Docker GPG key
#   - xvfb/x11vnc/websockify/novnc : CAPTCHA 值守模式虚拟显示 + VNC + Web VNC
#   - fonts-wqy-zenhei/fonts-noto-cjk : 中文字体（浏览器截图/headed 模式显示中文）
#   - docker-ce-cli : 沙箱 sibling 容器
#   - Playwright 浏览器运行依赖（lib 系列）
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl ca-certificates gnupg tzdata \
        xvfb x11vnc websockify novnc \
        fonts-wqy-zenhei fonts-noto-cjk \
        libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
        libdbus-1-3 libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 \
        libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2t64 \
        libxshmfence1 && \
    install -m 0755 -d /etc/apt/keyrings && \
    curl -fsSL https://mirrors.aliyun.com/docker-ce/linux/debian/gpg -o /etc/apt/keyrings/docker.asc && \
    chmod a+r /etc/apt/keyrings/docker.asc && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://mirrors.aliyun.com/docker-ce/linux/debian $(. /etc/os-release && echo $VERSION_CODENAME) stable" > /etc/apt/sources.list.d/docker.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends docker-ce-cli && \
    ln -sf /usr/share/novnc/vnc.html /usr/share/novnc/index.html 2>/dev/null || true && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# ---------- 阶段 2: playwright（浏览器安装，~600MB，极少变更） ----------
FROM system-deps AS playwright

# Playwright 浏览器下载使用国内镜像加速
ENV PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright

RUN pip install --no-cache-dir playwright && \
    playwright install --with-deps chromium && \
    rm -rf /var/lib/apt/lists/* /tmp/*

# ---------- 阶段 3: builder（Python 依赖，requirements.lock 变更时重建） ----------
FROM playwright AS builder

WORKDIR /build

COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock

# ---------- 阶段 4: work（最终运行镜像，代码变更时只重建这层） ----------
FROM system-deps AS work

WORKDIR /app

# 从 playwright 层复制 Playwright 包 + 浏览器
COPY --from=playwright /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=playwright /usr/local/bin /usr/local/bin
COPY --from=playwright /root/.cache/ms-playwright /root/.cache/ms-playwright

# 从 builder 层复制 Python 依赖
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# 复制源码（最常变，放最后）
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock && \
    pip check

COPY . .

RUN pip install --no-cache-dir --no-deps -e .

# 创建 app 用户（uid 1000），用于降权运行
RUN groupadd -g 1000 app 2>/dev/null || true && \
    useradd -u 1000 -g 1000 -m -d /home/app -s /bin/bash app 2>/dev/null || true && \
    mkdir -p /workspace /app/data /home/app && \
    chown -R 1000:1000 /home/app

RUN mkdir -p /home/app/.docker && chown -R 1000:1000 /home/app/.docker

# 复制 entrypoint 脚本
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# 工作区目录 + 默认约束文件
COPY workspace/constraints.yaml /workspace/constraints.yaml
COPY --chown=1000:1000 workspace/constraints.yaml /workspace/constraints.yaml
RUN chown -R 1000:1000 /workspace /app/data && chmod 755 /workspace /app/data
VOLUME ["/workspace", "/app/data"]

# 环境变量默认值
ENV TZ=Asia/Shanghai \
    CONCLAVE_WORKSPACE_DIR=/workspace \
    CONCLAVE_DB_PATH=/app/data/conclave.db \
    CONCLAVE_SANDBOX_IMAGE=python:3.12-slim \
    CONCLAVE_SANDBOX_IMAGE_DATASCIENCE=conclave-python-datascience:latest \
    CONCLAVE_SANDBOX_MODE=auto \
    DATASCIENCE_DOCKERFILE=/app/docker/sandbox-datascience/Dockerfile \
    HOME=/home/app \
    DISPLAY=:99

EXPOSE 8000 6080 9222

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# entrypoint 以 root 运行（负责 Docker socket 权限 + 镜像预拉取），完成后降权到 app 用户
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
