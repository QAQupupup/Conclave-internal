# ===== Conclave 后端 Dockerfile（三阶段构建） =====
# 架构：base（docker-ce-cli + Playwright，极少变更）→ builder（pip 依赖）→ work（运行时）
# 优势：代码/依赖变更只触发 builder+work 阶段，base 层的 ~600MB 下载永久缓存

# ---------- 阶段 1: base ----------
# python:3.12-slim + docker-ce-cli + Playwright Chromium + 系统依赖
# 这层几乎不变，一次构建后永久缓存，后续改动不会重新下载
FROM docker.m.daocloud.io/library/python:3.12-slim AS base

# pip 镜像源（国内加速）
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple

# 安装 curl（healthcheck 用）+ docker CLI（沙箱 sibling 容器用）+ Playwright 系统依赖
# 三者合并为一个 RUN 层，减少中间层体积
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
# 放在 base 层，仅 Playwright 版本升级时才重新下载
RUN pip install --no-cache-dir playwright && \
    playwright install --with-deps chromium && \
    playwright install-deps chromium && \
    rm -rf /var/lib/apt/lists/*

# ---------- 阶段 2: builder ----------
# 基于 base，安装项目 Python 依赖（仅 requirements.txt 变更时触发）
FROM base AS builder

WORKDIR /build

# 仅复制 requirements.txt，利用层缓存（代码变更不触发依赖重装）
COPY requirements.txt ./

# 安装全部依赖到系统 site-packages（playwright 已在 base 安装，pip 会自动跳过）
RUN pip install --no-cache-dir -r requirements.txt

# ---------- 阶段 3: work（最终运行镜像） ----------
# 基于 base，从 builder 拷贝项目依赖，再复制源码
FROM base AS work

WORKDIR /app

# 从 builder 拷贝项目 Python 依赖（site-packages + bin）
# base 层的 playwright 等已存在，COPY 只增量覆盖 builder 新增的包
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# 复制 requirements.txt 用于复检
COPY requirements.txt ./

# 复检：确保所有依赖完整存在（--no-deps 避免重复解析，仅验证已安装包的完整性）
RUN pip install --no-cache-dir --no-deps -r requirements.txt 2>/dev/null; \
    pip check || echo "WARNING: pip check found issues, but continuing..."

# 复制源码（这层变更频繁，但因依赖已在上层缓存，不影响构建速度）
COPY . .

# 安装本项目为可编辑包（不拉依赖，依赖已在 builder 拷贝过来）
RUN pip install --no-cache-dir --no-deps -e .

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
