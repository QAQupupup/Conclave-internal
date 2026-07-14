# ===== Conclave 前端 Dockerfile =====
# 多阶段构建：先 build 静态文件，再用 nginx serve

FROM swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/node:20-slim AS builder
ENV NPM_CONFIG_REGISTRY=https://registry.npmmirror.com
WORKDIR /app
COPY package.json ./
# 1. npm install 从 package.json 全新安装（不用 lock 文件，避免跨平台 optional dep 问题）
# 2. 显式安装匹配版本的 rolldown Linux 原生绑定
RUN npm install --registry https://registry.npmmirror.com --fetch-retries=5 --fetch-retry-mintimeout=10000 --fetch-retry-maxtimeout=60000 && \
    ROLLDOWN_VER=$(node -e "console.log(require('rolldown/package.json').version)") && \
    echo "Installing @rolldown/binding-linux-x64-gnu@$ROLLDOWN_VER" && \
    npm install @rolldown/binding-linux-x64-gnu@$ROLLDOWN_VER --no-save --registry https://registry.npmmirror.com
COPY . .
RUN npx tsc && npx vite build

FROM swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/nginx:1.27-alpine
RUN sed -i 's|https://dl-cdn.alpinelinux.org/alpine/|https://mirrors.aliyun.com/alpine/|g' /etc/apk/repositories && \
    apk update && \
    apk add --no-cache ca-certificates && \
    rm -rf /var/cache/apk/*
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
