# 常见问题（FAQ）

## 使用与环境

**启动后访问 http://localhost:5174 没反应？**

容器可能尚未就绪。运行 `docker compose ps` 查看状态，backend 变为 healthy 后再访问。首次启动需要拉取镜像，耐心等待。若一直失败，看 `docker compose logs backend` 排查。

**不配置 LLM 密钥能用吗？**

能。默认走 Stub 演示模式，会返回演示性结论，方便先体验完整流程。想得到真实推理，按 [快速上手](GETTING_STARTED.md) 配置 OpenAI 兼容接口。

**提示端口占用 / 端口冲突？**

服务固定占用 5174/8001/5433/6380/6335 等端口。若被占用，可在 `docker-compose.yml` 中修改端口映射。

## 模型与推理

**支持哪些模型？**

支持任何 OpenAI 兼容接口：硅基流动、DeepSeek、通义千问、OpenAI、本地 vLLM / Ollama 网关等。在 `.env` 中设置 `CONCLAVE_LLM_BASE_URL` 与 `CONCLAVE_LLM_MODEL` 即可。

**逻辑推理很慢 / 卡住？**

六阶段会议会调用大量 LLM 请求，速度取决于模型与网络。可通过模型中心调整模型、增大超时或简化议题。

## 功能与限制

**代码执行沙箱没生效？**

沙箱依赖宿主机 Docker。若在无 Docker 环境运行，需设置 `CONCLAVE_DOCKER_DISABLED=true`（沙箱相关产出物不可用）。否则检查后端容器是否有 Docker socket 权限。

**我的数据安全吗？**

默认单机部署，数据存储在本机 PostgreSQL / Redis / Qdrant 卷中。生产部署请参考 [部署指南](DEPLOYMENT.md) 的安全建议。

## 开源与版权

**这个项目是完全开源吗？**

本仓库是 [Conclave-internal](https://github.com/QAQupupup/Conclave-internal) 的**开源简化版（Community Edition）**，以 AGPL v3 协议开放核心能力，用于演示、学习与二次开发。六阶段决策管线、7 种内置角色、RAG 证据检索等均在此开源；完整版的全部决策算法与高级能力保留在私有仓库中。详见 [开源说明](../README.md)。

**我可以基于它做商业项目吗？**

在遵守 AGPL v3 的前提下可以。注意：基于本仓库公开部分的任何衍生作品必须以相同协议开源源代码。涉及核心算法的私有实现不受本仓库代码约束，但请自行评估合规边界。