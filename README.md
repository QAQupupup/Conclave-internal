# Conclave

<div align="center">

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/Python-3.12+-green.svg)](https://www.python.org/)
[![Docker](https://img.shields.io/badge/Docker-Compose-blue.svg)](https://docs.docker.com/compose/)
[![FastAPI](https://img.shields.io/badge/Backend-FastAPI-teal.svg)](https://fastapi.tiangolo.com/)
[![React 18](https://img.shields.io/badge/Frontend-React%2018-61DAFB.svg)](https://react.dev/)

**多智能体结构化决策系统** — 让 AI Agent 像开会一样产出高质量决策

*Multi-Agent Structured Decision-Making System. Run AI agents through a formal meeting pipeline: clarify, debate, evidence-check, arbitrate, and deliver.*

</div>

> Conclave（闭门会议）：一场有流程、有证据、有裁决、有落地交付的 AI 协作会议。每个 Agent 拥有独立视角与风险偏好，通过多角色结构化辩论消除单一大模型的盲区，保障产出质量与可靠性。

---

## 界面预览

<table>
  <tr>
    <td width="50%" align="center"><img src="assets/screenshots/meeting-discussion.jpg" alt="会议讨论界面" /><br><sub>多 Agent 结构化辩论</sub></td>
    <td width="50%" align="center"><img src="assets/screenshots/topology-graph.jpg" alt="流程拓扑图" /><br><sub>服务联通视图</sub></td>
  </tr>
  <tr>
    <td width="50%" align="center"><img src="assets/screenshots/produce-output.jpg" alt="产出物界面" /><br><sub>PRD 与 OpenAPI 产出</sub></td>
    <td width="50%" align="center"><img src="assets/screenshots/metrics-dashboard.jpg" alt="指标面板" /><br><sub>实时日志与质量指标</sub></td>
  </tr>
</table>

---

## 与通用方案的差异

| 维度 | 单模型对话 | 通用 Agent 框架 | **Conclave** |
|---|---|---|---|
| 决策模式 | 单视角输出 | 角色分工但缺流程 | **六阶段会议管线**：澄清→辩论→证据→仲裁→交付 |
| 观点质量 | 受限于模型偏见 | 易产生群体思维 | **多角色对抗辩论**，强制暴露冲突点 |
| 证据诚实性 | 幻觉率高 | 可选工具调用 | **证据强制校验**：无证据时诚实降级置信度 |
| 产出物 | 文本回复 | 文本回复 | **可交付物**：PRD+OpenAPI、可部署服务、分析报告 |
| 可观测性 | 黑盒 | 基础日志 | **全链路追踪**：日志、Token/成本、漂移检查、审计 |
| 部署门槛 | SaaS 依赖 | 需自行编排 | **Docker Compose 一键启动**，全容器化 |

核心原则：不追求 Agent 数量多，而追求决策质量高。宁可诚实标注"证据不足"，也不编造伪引用。

---

## 核心特性

- **六阶段会议管线**：clarify（澄清）→ intra_team（队内立论）→ cross_team（跨队辩论）→ evidence_check（证据校验）→ arbitrate（仲裁裁决）→ produce（产出交付），带质量门禁与自动回流
- **7 种独立角色**：产品架构师、工程师、安全专家、UX 设计师、数据工程师、市场专家、主持人，每个角色有独立视角、风险偏好与证据偏好
- **动态借调机制**：主持人可根据议题复杂度动态申请补充专家角色
- **证据诚实性保障**：论点必须标注证据来源（文档/网页/常识/假设），无证据论点自动降级置信度
- **Docker 沙箱隔离**：代码执行在独立容器中，支持多主机分布式调度（5 种调度策略）
- **可部署服务交付**：会议结论可直接生成 FastAPI 后端 + React 前端 + Docker 配置，自动部署到沙箱运行
- **实时可观测性**：实时日志面板、级别着色、进度追踪、Token/成本监控、审计日志
- **RAG 检索增强**：bge-m3 多语言 Embedding + bge-reranker-v2-m3 重排序 + HyDE 假设文档嵌入
- **多租户隔离**：租户级数据隔离、配置覆盖与 RBAC 权限控制
- **插件框架**：支持认证、可观测性等模块通过插件热插拔

---

## 快速开始

### 环境要求

- Docker Desktop（Windows/macOS）或 Docker Engine + Docker Compose（Linux）
- 无需本地 Python/Node 环境（全部容器化）

### 一键启动

```bash
git clone https://github.com/QAQupupup/Conclave.git
cd Conclave
docker compose up -d --build
```

启动后访问：

| 服务 | 地址 |
|---|---|
| 前端界面 | http://localhost:5173 |
| 后端 API 文档 | http://localhost:8000/docs |
| PostgreSQL | localhost:5432（容器内） |
| Redis | localhost:6379（容器内） |
| Qdrant 向量库 | localhost:6333（容器内） |

### 配置 LLM（可选，不配置走 Stub 模式）

在项目根目录创建 `.env` 文件（或复制 `.env.example`）：

```env
# OpenAI 兼容接口（支持硅基流动、DeepSeek、通义千问等）
CONCLAVE_LLM_API_KEY=your-api-key
CONCLAVE_LLM_BASE_URL=https://api.siliconflow.cn/v1
CONCLAVE_LLM_MODEL=deepseek-ai/DeepSeek-V3.2
```

也可在前端"模型中心"页面直接配置。

### 使用流程

1. 打开 http://localhost:5173
2. 输入议题，选择产出物类型
3. 点击"开始会议"，观察六阶段自动执行
4. 会议完成后在"产出"面板查看结果

---

## 架构概览

```
┌──────────────────────────────────────────────────┐
│                Frontend (React + AntD)            │
│  聊天面板 │ 日志面板 │ 联通图 │ 运维面板 │ 监控    │
└─────────────────────┬────────────────────────────┘
                      │ WebSocket / REST
┌─────────────────────┼────────────────────────────┐
│              Backend (FastAPI + asyncio)          │
│  ┌──────────────────┴──────────────────┐          │
│  │     EventBus 事件总线                │          │
│  │  内存缓存 + PG 持久化 + Redis Pub/Sub│          │
│  └──────────────────┬──────────────────┘          │
│  ┌──────────────────┴──────────────────┐          │
│  │   Runner/Manager 编排器              │          │
│  │  clarify → intra_team → cross_team  │          │
│  │  → evidence → arbitrate → produce   │          │
│  └────┬──────┬──────┬──────┬───────────┘          │
│  ┌────▼──┐┌──▼──┐┌──▼───┐┌──▼──┐                  │
│  │Agents ││ RAG ││Sand- ││Tools│                  │
│  │(LLM)  ││     ││box   ││     │                  │
│  └───┬───┘└─────┘└──┬───┘└─────┘                  │
│      │              │ Docker API                   │
│      │         ┌────┴────┐                         │
│      │         ▼         ▼                         │
│      │   ┌──────────┐ ┌──────────┐                 │
│      │   │ 本地Docker│ │RemoteHost│                │
│      ▼   └──────────┘ └──────────┘                 │
│  ┌─────────────────────────────┐                   │
│  │ PostgreSQL │ Redis │ Qdrant │                   │
│  └─────────────────────────────┘                   │
└───────────────────────────────────────────────────┘
```

---

## 技术栈

| 层 | 技术选型 |
|---|---|
| 后端 | Python 3.12 + FastAPI + asyncio + SQLAlchemy (async) |
| 前端 | React 18 + TypeScript + Vite + Ant Design |
| 数据库 | PostgreSQL（主存储，含 pgvector）+ Redis（缓存/会话） |
| 向量检索 | Qdrant / 内存向量库（开发模式） |
| 嵌入模型 | bge-m3（多语言）+ bge-reranker-v2-m3（重排序） |
| 容器化 | Docker + Docker Compose（Sibling Containers 沙箱） |
| 实时通信 | WebSocket + 事件总线 |
| 浏览器自动化 | Playwright + Chromium |

---

## API 概览

路由无全局 `/api` 前缀，完整列表见 `http://localhost:8000/docs`。

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/meetings` | 创建会议 |
| GET | `/meetings` | 会议列表 |
| GET | `/meetings/{id}` | 会议详情 |
| POST | `/meetings/{id}/run` | 启动会议（后台异步执行） |
| POST | `/meetings/{id}/control` | 控制（pause/resume/abort/inject） |
| POST | `/meetings/{id}/documents` | 上传参考文档 |
| DELETE | `/meetings/{id}` | 删除会议（清理关联资源） |
| WS | `/ws/meetings/{id}` | WebSocket 实时事件流 |
| GET/POST | `/docker-hosts` | Docker 主机管理 |
| POST | `/auth/login` | 登录 |
| GET | `/auth/me` | 当前用户信息 |

---

## 项目结构

```
Conclave/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI 入口
│   │   ├── config.py            # 环境变量配置
│   │   ├── orchestrator/        # 编排核心（runner/manager/stage_runners/context_manager）
│   │   ├── agents/              # Agent 计算层（LLM 调用 + 运行时）
│   │   ├── routers/             # API 路由
│   │   ├── rag/                 # 检索增强（HyDE/Multi-Query/Reranker）
│   │   ├── sandbox.py           # Docker 沙箱管理
│   │   ├── plugins/             # 插件系统
│   │   ├── tenants/             # 多租户隔离
│   │   ├── db/                  # 数据层（ORM 模型/引擎）
│   │   ├── tools/               # 工具集（搜索/浏览器/域名可信度）
│   │   ├── observability/       # 可观测性（日志/指标/成本/审计）
│   │   └── domain/              # 领域模型与枚举
│   ├── tests/                   # 测试文件
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── views/               # 页面（Board/Meeting/Models/Topology/Monitor/DevOpsPanel）
│   │   ├── components/          # 可复用组件
│   │   └── lib/                 # 工具库（api/ws/auth）
│   └── Dockerfile
├── docker-compose.yml           # 开发环境编排
├── docker-compose.oss.yml       # 开源版编排
├── .env.example                 # 环境变量模板
└── LICENSE
```

---

## 开发

### 本地开发（非 Docker）

```bash
# 后端
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1   # Windows
pip install -e .
uvicorn app.main:app --reload

# 前端（另开终端）
cd frontend
npm install
npm run dev
```

注意：本地开发需自行启动 PostgreSQL、Redis、Qdrant。

### 测试与质量检查

所有检查建议在 Docker 容器内执行：

```bash
# 全量测试（含 ruff/mypy/pytest）
docker compose -f docker-compose.test.yml up --build --exit-code-from backend-test
```

### 贡献

欢迎提交 Issue 和 Pull Request。提交前请确保：
- 代码通过 lint 检查（ruff）
- 新增功能配有对应测试
- Commit Message 遵循 Conventional Commits

---

## License

[MIT License](LICENSE)
