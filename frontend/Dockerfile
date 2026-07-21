# ===== Conclave 前端 Dockerfile =====
# 多阶段构建：node 编译 React 工程 → nginx serve dist
# 产物：portal(/) + 主应用(/app, SPA) + 演示页(/demo)

# ---------- 1. 构建阶段 ----------
FROM swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/library/node:20-alpine AS build
WORKDIR /app
# 先拷依赖描述以利用 Docker 层缓存
COPY package.json package-lock.json ./
RUN npm config set registry https://registry.npmmirror.com && npm ci
# 拷源码并构建
COPY tsconfig.json vite.config.ts app.html ./
COPY public ./public
COPY src ./src
RUN npm run build

# ---------- 2. 运行阶段 ----------
FROM swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/nginx:1.27-alpine
RUN sed -i 's|https://dl-cdn.alpinelinux.org/alpine/|https://mirrors.aliyun.com/alpine/|g' /etc/apk/repositories && \
    apk update && \
    apk add --no-cache ca-certificates && \
    rm -rf /var/cache/apk/*
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
