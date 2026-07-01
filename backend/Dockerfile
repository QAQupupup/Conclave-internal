# ===== Conclave 后端 Dockerfile =====
# 基于 python:3.12-slim，安装 docker CLI 用于沙箱执行
# 通过 docker socket mounting 创建 sibling 容器（非 dind）

FROM docker.m.daocloud.io/library/python:3.12-slim

# pip 镜像源（国内加速）
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple

# 安装 curl + docker CLI
# 用阿里云 Docker CE 镜像源替代官方源
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl ca-certificates gnupg && \
    install -m 0755 -d /etc/apt/keyrings && \
    curl -fsSL https://mirrors.aliyun.com/docker-ce/linux/debian/gpg -o /etc/apt/keyrings/docker.asc && \
    chmod a+r /etc/apt/keyrings/docker.asc && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://mirrors.aliyun.com/docker-ce/linux/debian $(. /etc/os-release && echo $VERSION_CODENAME) stable" > /etc/apt/sources.list.d/docker.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends docker-ce-cli && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先复制依赖文件，利用层缓存
COPY pyproject.toml ./

# 安装依赖
RUN pip install --no-cache-dir -e ".[dev]"

# 安装 Playwright Chromium 浏览器 + 系统依赖（用于 Web Search 无头浏览器）
RUN playwright install --with-deps chromium

# 复制源码
COPY . .

# 工作区目录
RUN mkdir -p /workspace /app/data
VOLUME ["/workspace"]

# 环境变量默认值
ENV CONCLAVE_WORKSPACE_DIR=/workspace \
    CONCLAVE_DB_PATH=/app/data/conclave.db \
    CONCLAVE_SANDBOX_IMAGE=docker.m.daocloud.io/library/python:3.12-slim \
    CONCLAVE_SANDBOX_MODE=auto

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["python", "-m", "uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
