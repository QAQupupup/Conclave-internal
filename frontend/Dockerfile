# ===== Conclave 前端 Dockerfile =====
# 原型版（纯 HTML）— 无需编译，直接 nginx serve
# 保持与原版相同的端口(5173→80)和 nginx 代理配置

FROM swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/nginx:1.27-alpine
RUN sed -i 's|https://dl-cdn.alpinelinux.org/alpine/|https://mirrors.aliyun.com/alpine/|g' /etc/apk/repositories && \
    apk update && \
    apk add --no-cache ca-certificates && \
    rm -rf /var/cache/apk/*
COPY index.html app.html demo.html /usr/share/nginx/html/
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
