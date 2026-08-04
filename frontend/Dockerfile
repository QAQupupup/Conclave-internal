# ===== Conclave 前端 Dockerfile =====
# 多阶段构建：node 编译 React 工程 → nginx serve dist
# 安全加固：server_tokens off + proxy_hide_header 隐藏后端指纹

# ---------- 1. 构建阶段 ----------
FROM swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/library/node:20-slim AS build
WORKDIR /app
# 国内镜像源
RUN npm config set registry https://registry.npmmirror.com
# 先拷依赖描述以利用 Docker 层缓存
COPY package.json package-lock.json ./
# npm ci 严格按 lock 文件安装，BuildKit 缓存挂载加速 npm 下载
RUN --mount=type=cache,target=/root/.npm \
    npm ci && npm install @rollup/rollup-linux-x64-gnu
# 拷源码并构建（源码常变，放最后）
COPY tsconfig.json vite.config.ts app.html eslint.config.js components.json vitest.config.ts ./
COPY public ./public
COPY src ./src
RUN npm run build

# ---------- 2. 运行阶段 ----------
FROM swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/nginx:1.27-alpine
# 国内镜像源 + ca-certificates
RUN sed -i 's|https://dl-cdn.alpinelinux.org/alpine/|https://mirrors.aliyun.com/alpine/|g' /etc/apk/repositories && \
    apk update && \
    apk add --no-cache ca-certificates curl && \
    rm -rf /var/cache/apk/*
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
