# ===== Web Search Service — 独立 Docker 镜像（多阶段构建）=====
#
# 分层策略（从底到顶，变更频率递增）：
#   1. system-deps : apt 源配置 + Playwright 浏览器系统依赖
#   2. playwright  : pip install playwright + playwright install chromium（~600MB，极少变更）
#   3. builder     : pip install requirements.txt（依赖变更时触发）
#   4. work        : COPY 源码 + 启动服务（代码变更时只重建这一层）
#
# 与主 backend 镜像的差异：
#   - 不含 Docker CE CLI（不需要沙箱能力）
#   - 不含 Xvfb/VNC/noVNC（不需要值守模式）
#   - 不含中文字体（不需要截图/headed 模式）
#   - 不含 Cython 编译工具链
#
# 构建:
#   docker build -f web_search_service/Dockerfile -t conclave-web-search ..
# 运行:
#   docker run -p 9100:9100 \
#     -e CONCLAVE_LLM_API_KEY=xxx \
#     -e CONCLAVE_LLM_BASE_URL=https://api.siliconflow.cn/v1 \
#     conclave-web-search

# ---------- 阶段 1: system-deps（系统依赖，最底层，永久缓存） ----------
FROM swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/python:3.12-slim AS system-deps

# pip 镜像源（国内加速）
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple

# === 替换 apt 源为清华 TUNA 镜像（兼容 Debian Bookworm DEB822 格式）===
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

# 安装 Playwright Chromium 浏览器运行依赖（精简版，不含值守/VNC/字体）
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl ca-certificates \
        libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
        libdbus-1-3 libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 \
        libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2t64 \
        libxshmfence1 && \
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

# 安装项目依赖（复用 backend requirements.lock）
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock

# 安装 Web Search Service 额外依赖
COPY web_search_service/requirements.txt /tmp/ws-requirements.txt
RUN pip install --no-cache-dir -r /tmp/ws-requirements.txt

# ---------- 阶段 4: work（最终运行镜像，代码变更时只重建这层） ----------
FROM system-deps AS work

WORKDIR /app

# 从 playwright 层复制 Playwright 包 + 浏览器
COPY --from=playwright /usr/local/lib/python3.12/site-packages/ /usr/local/lib/python3.12/site-packages/
COPY --from=playwright /usr/local/bin/ /usr/local/bin/
COPY --from=playwright /root/.cache/ms-playwright/ /root/.cache/ms-playwright/

# 从 builder 层复制 Python 依赖
COPY --from=builder /usr/local/lib/python3.12/site-packages/ /usr/local/lib/python3.12/site-packages/
COPY --from=builder /usr/local/bin/ /usr/local/bin/

# 复制源码（含 app/ 和 web_search_service/）
COPY pyproject.toml ./
COPY app/ ./app/
COPY web_search_service/ ./web_search_service/

# 环境变量
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# 服务端口
EXPOSE 9100

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:9100/health', timeout=5).raise_for_status()" || exit 1

# Cookie 持久化数据目录
RUN mkdir -p /app/data
VOLUME ["/app/data"]

# 启动服务
CMD ["python", "-m", "uvicorn", "web_search_service.main:app", "--host", "0.0.0.0", "--port", "9100"]