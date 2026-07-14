# ===== Conclave 前端 Dockerfile =====
# 多阶段构建：先 build 静态文件，再用 nginx serve
# 使用 npm（package-lock.json 是事实源）

FROM swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/node:20-slim AS builder
ENV NPM_CONFIG_REGISTRY=https://registry.npmmirror.com
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm install --registry https://registry.npmmirror.com --fetch-retries=5 --fetch-retry-mintimeout=10000 --fetch-retry-maxtimeout=60000 && \
    npm install @rolldown/binding-linux-x64-gnu --save-optional --registry https://registry.npmmirror.com
COPY . .
RUN npx tsc && npx vite build

FROM swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/nginx:1.27-alpine
# Alpine apk 使用阿里云镜像加速
RUN sed -i 's|https://dl-cdn.alpinelinux.org/alpine/|https://mirrors.aliyun.com/alpine/|g' /etc/apk/repositories && \
    apk update && \
    apk add --no-cache ca-certificates && \
    rm -rf /var/cache/apk/*
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
