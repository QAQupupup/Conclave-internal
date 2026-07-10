# ===== Conclave 前端 Dockerfile =====
# 多阶段构建：先 build 静态文件，再用 nginx serve
#
# 修复：原版 `npm ci` 在没有 package-lock.json / lockfile 不一致时报错。
# 项目实际用 pnpm（package-lock.json 缺失，pnpm-lock.yaml 是事实源）。
# 改用 `pnpm install --frozen-lockfile` 走 pnpm 缓存（lockfile 一致时跳过解析）。

FROM docker.m.daocloud.io/library/node:20-slim AS builder
# 启用 pnpm + 国内镜像
# 修复：corepack 默认装 pnpm 11.x 要求 Node 21+，与 Node 20.20 不兼容（ERR_UNKNOWN_BUILTIN_MODULE）
# 显式装 pnpm 9.15.0（Node 20 兼容）
ENV PNPM_HOME="/pnpm" \
    PATH="$PNPM_HOME:$PATH" \
    NPM_CONFIG_REGISTRY=https://registry.npmmirror.com
RUN npm install -g pnpm@9.15.0 --registry https://registry.npmmirror.com
WORKDIR /app
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile --registry https://registry.npmmirror.com
COPY . .
RUN pnpm run build

FROM docker.m.daocloud.io/library/nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
