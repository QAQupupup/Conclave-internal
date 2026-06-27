# ===== Conclave 前端 Dockerfile =====
# 多阶段构建：先 build 静态文件，再用 nginx serve

FROM docker.m.daocloud.io/library/node:20-slim AS builder
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --registry https://registry.npmmirror.com
COPY . .
RUN npm run build

FROM docker.m.daocloud.io/library/nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
