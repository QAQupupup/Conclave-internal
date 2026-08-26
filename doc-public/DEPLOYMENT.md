# 部署指南

本文面向需要把 Conclave 部署到自有服务器或生产环境的用户。

## 快速部署（单机）

推荐使用 Docker Compose 一键部署：

```bash
git clone https://github.com/QAQupupup/Conclave.git
cd Conclave

# 准备环境变量
cp .env.example .env
# 编辑 .env，填入 CONCLAVE_LLM_API_KEY 等必要配置

docker compose up -d --build
```

默认服务端口见下表：

| 服务 | 地址 |
|---|---|
| 前端界面 | http://localhost:5174 |
| 后端 API 文档 | http://localhost:8001/docs |
| PostgreSQL | localhost:5433 |
| Redis | localhost:6380 |
| Qdrant 向量库 | localhost:6335 |

## 环境变量

关键配置集中在 `.env` 文件。常用项：

| 变量 | 说明 |
|---|---|
| `CONCLAVE_LLM_API_KEY` | LLM 服务密钥 |
| `CONCLAVE_LLM_BASE_URL` | OpenAI 兼容接口地址 |
| `CONCLAVE_LLM_MODEL` | 使用的模型名 |
| `CONCLAVE_SECRET_KEY` | 服务端密钥（务必改成随机强值） |
| `CONCLAVE_DOCKER_DISABLED` | 设为 `true` 可在无 Docker 环境运行（沙箱功能受限） |

## 沙箱说明

代码执行沙箱依赖宿主机的 Docker。后端容器以 root 启动，自动配置 Docker socket 权限、预拉取基础镜像，再降权运行。若部署环境无 Docker，请设置 `CONCLAVE_DOCKER_DISABLED=true`，沙箱相关功能会被降级（部分需要执行代码的产出物类型不可用）。

## 常见运维操作

```bash
# 查看服务状态
docker compose ps

# 跟踪后端日志
docker compose logs -f backend

# 停止服务
docker compose down

# 升级（重新构建并拉取）
docker compose up -d --build --pull always
```

## 生产建议

- 将 `CONCLAVE_SECRET_KEY` 改为随机强值，不要使用默认值
- 通过反向代理（如 Caddy / Nginx）终止 TLS，仅对外暴露 HTTPS
- 按需限制 PostgreSQL、Redis、Qdrant 的对外端口暴露
- 定期备份 PostgreSQL 数据卷与工作区卷