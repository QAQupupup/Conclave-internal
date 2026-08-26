# 快速上手

本指南带你在 5 分钟内从零跑起 Conclave，完成你的第一场 AI 会议。

## 你需要准备什么

- Docker Desktop（Windows / macOS）或 Docker Engine + Docker Compose（Linux）
- 无需安装 Python 或 Node.js —— 所有服务都在容器里跑
- 可选：一个 OpenAI 兼容的模型接口（如硅基流动、DeepSeek、通义千问）用于真实推理；不配置也能用 Stub 模式演示完整流程

## 第一步：克隆并启动

```bash
git clone https://github.com/QAQupupup/Conclave.git
cd Conclave
docker compose up -d --build
```

首次构建需要拉取依赖和镜像，耗时取决于网络。启动后等待各容器就绪（可查看 `docker compose ps` 状态，backend 出现 healthy 即可）。

## 第二步：打开界面

浏览器访问 http://localhost:5174 。

## 第三步：发起你的第一场会议

1. 在输入框里写一个议题，例如「设计一个骑行情侣的轻量级拼车 App 的 MVP」
2. 选择产出物类型（推荐先选「研究报告」或「PRD」）
3. 点击「开始会议」
4. 观察六阶段自动跑完：澄清 → 队内讨论 → 跨队辩论 → 证据校验 → 仲裁 → 产出
5. 结束后在右侧「产出」面板查看结果

> 提示：默认 Stub 模式会返回演示性结论，用于体验流程。想得到真实推理，请参考下方配置。

## 可选：配置真实模型

在项目根目录创建 `.env`（或复制 `.env.example`）：

```env
CONCLAVE_LLM_API_KEY=你的密钥
CONCLAVE_LLM_BASE_URL=https://api.siliconflow.cn/v1
CONCLAVE_LLM_MODEL=deepseek-ai/DeepSeek-V3.2
```

修改后重启后端服务：`docker compose restart backend`。也可以在前端「模型中心」页面直接填写。

## 服务地址一览

| 服务 | 地址 |
|---|---|
| 前端界面 | http://localhost:5174 |
| 后端 API 文档 | http://localhost:8001/docs |
| PostgreSQL | localhost:5433 |
| Redis | localhost:6380 |
| Qdrant 向量库 | localhost:6335 |

## 遇到问题了？

看 [FAQ](FAQ.md)，或到 [Issue](https://github.com/QAQupupup/Conclave/issues) 提一个带日志的问题。