# ===== Conclave 后端 Dockerfile（三阶段构建） =====
# 架构：base（docker-ce-cli + Playwright，极少变更）→ builder（pip 依赖）→ work（运行时）
# 优势：代码/依赖变更只触发 builder+work 阶段，base 层的 ~600MB 下载永久缓存
#
# 运行时：entrypoint.sh 以 root 启动 → 配置 Docker socket 权限 → 预拉取沙箱镜像 → 降权到 uid 1000 运行 uvicorn

# ---------- 阶段 1: base ----------
FROM docker.m.daocloud.io/library/python:3.12-slim AS base

# pip 镜像源（国内加速）
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple

# 安装 curl（healthcheck 用）+ docker CLI（沙箱 sibling 容器用）+ Playwright 系统依赖
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl ca-certificates gnupg && \
    install -m 0755 -d /etc/apt/keyrings && \
    curl -fsSL https://mirrors.aliyun.com/docker-ce/linux/debian/gpg -o /etc/apt/keyrings/docker.asc && \
    chmod a+r /etc/apt/keyrings/docker.asc && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://mirrors.aliyun.com/docker-ce/linux/debian $(. /etc/os-release && echo $VERSION_CODENAME) stable" > /etc/apt/sources.list.d/docker.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends docker-ce-cli && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# 安装 Playwright Python 包 + Chromium 浏览器 + 浏览器系统依赖（~600MB，最耗时）
RUN pip install --no-cache-dir playwright && \
    playwright install --with-deps chromium && \
    playwright install-deps chromium && \
    rm -rf /var/lib/apt/lists/*

# ---------- 阶段 2: builder ----------
FROM base AS builder

WORKDIR /build

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# ---------- 阶段 3: work（最终运行镜像） ----------
FROM base AS work

WORKDIR /app

COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

COPY requirements.txt ./
RUN pip install --no-cache-dir --no-deps -r requirements.txt 2>/dev/null; \
    pip check || echo "WARNING: pip check found issues, but continuing..."

# 复制源码
COPY . .

RUN pip install --no-cache-dir --no-deps -e .

# 创建 app 用户（uid 1000），用于降权运行
# 注意：不在这里 chown，entrypoint.sh 启动时会处理
RUN groupadd -g 1000 app 2>/dev/null || true && \
    useradd -u 1000 -g 1000 -m -d /home/app -s /bin/bash app 2>/dev/null || true && \
    mkdir -p /workspace /app/data /home/app && \
    chown -R 1000:1000 /home/app

# 给 app 用户创建 .docker 目录（docker pull 需要写入配置）
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
ENV CONCLAVE_WORKSPACE_DIR=/workspace \
    CONCLAVE_DB_PATH=/app/data/conclave.db \
    CONCLAVE_SANDBOX_IMAGE=docker.m.daocloud.io/library/python:3.12-slim \
    CONCLAVE_SANDBOX_IMAGE_DATASCIENCE=conclave-python-datascience:latest \
    CONCLAVE_SANDBOX_MODE=auto \
    DATASCIENCE_DOCKERFILE=/app/docker/sandbox-datascience/Dockerfile \
    HOME=/home/app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# entrypoint 以 root 运行（负责 Docker socket 权限 + 镜像预拉取），完成后降权到 app 用户
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
