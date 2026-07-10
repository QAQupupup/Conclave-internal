# Conclave

> 会议型多智能体系统：议题 → 多 Agent 结构化辩论 → 证据支撑裁决 → 产出可验证的 PRD / 接口规范。
>
> 名称取自"Conclave（闭门会议 / 枢机主教团集会）"，对应系统的核心隐喻——一场有流程、有证据、有裁决的结构化会议。早期架构讨论曾使用代号 *Zore*，统一归并为 **Conclave**。

---

## 这是什么

Conclave 是一个**可演化的会议型智能体系统**。它把一次议题拆解为多智能体结构化辩论、证据支撑裁决、产物输出的完整闭环，并在迭代中沉淀智能体行为特征。

终态系统有三个判定特征：

1. **结构化知识系统**——检索不靠全文 embedding top-k，而靠保真原文、概念抽取、按需激活的知识图。
2. **事件驱动协作**——实时性不绑死 WebSocket，由事件广播 runner 统一负责。
3. **可迭代的个体**——发言全量留底，选择性提炼为长期行为特征与稳定画像，反哺下次会议。

---

## 快速开始

### 环境要求
- Python 3.13+（在 3.14.6 验证通过）
- 无需 API key 即可跑通（内置 stub 模式）

### 后端

```bash
# 1. 创建虚拟环境（依赖隔离）
python -m venv .venv

# 2. 激活
# Windows PowerShell:
.\.venv\Scripts\Activate.ps1
# macOS/Linux:
source .venv/bin/activate

# 3. 安装依赖
pip install -e backend
pip install -r backend/requirements.txt  # 补全 pyproject.toml 未覆盖的额外依赖

# 4. 配置（可选，留空走 stub）
cp .env.example .env

# 5. 跑测试
pytest backend/tests/ -v

# 6. 启动服务
uvicorn app.main:app --reload --app-dir backend
```

服务启动后访问 http://127.0.0.1:8000/docs 查看 API 文档。

### 一次完整会议

```bash
# 创建会议
curl -X POST http://127.0.0.1:8000/api/meetings \
  -H "Content-Type: application/json" \
  -d '{"topic":"设计一个待办事项 API"}'

# 上传资料（可选）
curl -X POST http://127.0.0.1:8000/api/meetings/{meeting_id}/documents \
  -F "file=@spec.md"

# 触发完整流程（六阶段自动跑通，产出 PRD + OpenAPI）
curl -X POST http://127.0.0.1:8000/api/meetings/{meeting_id}/run

# 查看结果
curl http://127.0.0.1:8000/api/meetings/{meeting_id}
```

WebSocket 连接：`ws://127.0.0.1:8000/ws/meetings/{meeting_id}`，连接时回放状态快照，之后实时推送 `agent.spoke` / `stage.changed` / `evidence.attached` / `artifact.generated` 等事件。

### 切换到真实 LLM

在 `.env` 中填入 `CONCLAVE_LLM_API_KEY`，系统自动从 StubLLM 切换到真实 LLM（OpenAI 兼容接口）。向量库同理，留空走内存伪向量。

---

## 技术栈（按演进阶段）

| 层 | v1 | 终态 |
|---|---|---|
| 后端编排 | Python + FastAPI | Python（异构热点可换 Go/Rust） |
| 状态机 | 纯 Python 六阶段 | 七阶段 + 控场信号 |
| LLM | Qwen3.5-4B（硅基流动）+ StubLLM 自动切换 | 多模型路由 + 分阶段温度 |
| 确定性保障 | 五层约束（参数/锁定链/自检/追踪/降级） | + 结论演化与人格提炼 |
| 检索 | bge-m3 embedding + bge-reranker-v2-m3 + 内存向量库 | Chunk Graph + 术语归一 + 惰性管道 |
| 感知层 | Web Search stub（Tavily 预留） | + 浏览器自动化 + 桌面感知 |
| 证据分级 | [doc]/[web]/[common_knowledge]/[assumption] 四级 | + 证据质量评分 |
| 记忆 | 三层记忆（Raw + Feature + Profile）+ 画像注入 | + SQLite 持久化 + 画像演化 |
| 实时 | 内存 WebSocket + 事件序列号 + 增量回放 | Event Runner + 多 sink / MQ |
| 执行 | 可选容器 lint/test | L1/L2/L3 风险分级 |
| 前端 | React 四块布局 + 置信度 + 证据着色 + 力导向图 | + 拓扑交互 |
| 存储 | SQLite | PostgreSQL + 向量库 |

---

## 演进路线

- **v1** ✅：极简会议闭环——议题 → 多 Agent 辩论 → 证据 → PRD（可选代码骨架验证）。六阶段 + 五层确定性 + 证据分级 + 感知层接口。
- **v2** ✅：三层记忆、动态角色库、力导向图、事件总线增量回放、run 异步化、审计端点。75 个测试通过。
- **v3**：Chunk Graph、术语归一、自动借调、多租户、完整执行风险分级。

原则：不妥协愿景，但不被愿景绑架。先跑通主闭环，再以插件方式逐项引入终态特性。

---

## 文档索引

> 文档按用途分为四类，存放在 `docs/` 下对应子目录。

### 核心设计文档（`docs/design/`）

项目"宪法"级文档，变更需评审。

| 文档 | 内容 | 何时读 |
|---|---|---|
| [ideal-design.md](./docs/design/ideal-design.md) | 终态架构愿景（理想设计稿） | 想看系统最终长什么样 |
| [design-principles.md](./docs/design/design-principles.md) | 设计原则与固化条款 | 做取舍决策、评审方案时 |
| [mvp-plan.md](./docs/design/mvp-plan.md) | v1 可执行计划与两周开发表 | 准备动手开工时 |
| [architecture-review.md](./docs/design/architecture-review.md) | 架构评审与风险裁判 | 判断"该不该现在做"时 |
| [iteration-1-design.md](./docs/design/iteration-1-design.md) | 迭代一详细设计：状态机/Prompt/模型/事件/目录树 | 写代码时的工程依据 |
| [iteration-2-design.md](./docs/design/iteration-2-design.md) | 迭代二详细设计：三层记忆/动态角色库/事件回放/力导向图 | 做迭代二开发时 |

文档间关系：`ideal-design` 是上限，`mvp-plan` 是地基，`design-principles` 与 `architecture-review` 是两者间的裁判与约束。

### 研究与演进文档（`docs/research/`）

方向性文档，记录架构思考和技术预研。

| 文档 | 内容 |
|---|---|
| [architecture-evolution.md](./docs/research/architecture-evolution.md) | 架构演进方向（三阶段路径） |
| [skill-system-architecture.md](./docs/research/skill-system-architecture.md) | Agent Skill 系统设计（YAML 知识模块） |
| [mcp-research.md](./docs/research/mcp-research.md) | MCP 协议预研（知识库挂载/写入/审核） |
| [optimization-backlog.md](./docs/research/optimization-backlog.md) | 代码优化待办（设计模式方向） |
| [test-rag-doc.md](./docs/research/test-rag-doc.md) | 测试用 RAG 素材文档 |

### 审计与修复报告（`docs/audits/`）

按时间线归档的审计发现与修复记录，支持可追溯性。

| 文档 | 内容 |
|---|---|
| [project-review-2026-07-11.md](./docs/audits/project-review-2026-07-11.md) | 全项目架构/代码/文档梳理报告（含问题清单与优先级建议） |
| [audit-fix-report-2026-07-11.md](./docs/audits/audit-fix-report-2026-07-11.md) | 七维度审计修复（P0-P2 共 10 项问题全部修复） |
| [audit-fix-report-v1.md](./docs/audits/audit-fix-report-v1.md) | 30 个审计发现 100% 修复 |
| [audit-2026-07-01.md](./docs/audits/audit-2026-07-01.md) | 18 个问题确认清单 |
| [fix-archive-2026-07-01.md](./docs/audits/fix-archive-2026-07-01.md) | 18 个审核问题修复归档（56 测试通过） |
| [browsertool-review-archive-2026-07-01.md](./docs/audits/browsertool-review-archive-2026-07-01.md) | BrowserTool 架构交叉评审 |
| [e2e-verification-report.md](./docs/audits/e2e-verification-report.md) | 端到端真实 LLM 验证报告 |
| `conclave-audit-v{2~5}/` | HTML 格式可分享审计报告包 |

### 会话归档（`docs/sessions/`）

历次开发会话的完整记录，按日期组织。

| 文档 | 内容 |
|---|---|
| [session-archive-2026-06-28.md](./docs/sessions/session-archive-2026-06-28.md) | 设计模式优化 + 产品质量缺口修复 + 三阶段升级规划 |
| [session-archive-2026-06-29.md](./docs/sessions/session-archive-2026-06-29.md) ~ [-4.md](./docs/sessions/session-archive-2026-06-29-4.md) | 沙箱网络分级 / 产出验证 / 前端渲染 / 安全闭环 + 可靠性闭环 |
| [session-archive-2026-06-30.md](./docs/sessions/session-archive-2026-06-30.md) | WebSocket 断线重连 + RAG chunk 邻居链 + 议题路由 |

---

## 偏好与约束系统

Conclave 的 Agent 行为由 Skill（正面规范）和 Bug Pattern（负面清单）两套 YAML 知识模块控制，运行时按阶段动态注入。

### Skill 文件（`backend/app/skills/`）

| 文件 | 优先级 | 适用阶段 | 内容 |
|------|--------|----------|------|
| `ui_design_system.yaml` | 90（最高） | produce | 品牌色 #335c8e、4px 间距基准、CSS 反模式清单 |
| `code_conventions.yaml` | 85 | produce/review/bugfix | 项目结构、错误处理、安全要求、Docker 部署规范 |
| `communication_style.yaml` | 80 | clarify → arbitrate | 自然中文、标签格式 [事实]/[假设]/[风险] |
| `deliverable_quality.yaml` | 75 | review/arbitrate/produce | 验收清单 + Bug 严重等级定义 |

### Bug Pattern（`backend/app/prompts/bug_patterns.yaml`）

30+ 条代码生成负面清单，分 5 大类：python_fastapi / docker_deployment / frontend_react / architecture / review_checklist。每条含 id、pattern、fix、severity。

### 系统约束（`backend/workspace/constraints.yaml`）

7 条 hard/soft 约束：议题边界、禁止重复裁决、借调审批、阶段对齐、证据优先、用户尊重、简洁表达。

---

## 项目结构概览

```
Conclave/
├── backend/
│   ├── app/
│   │   ├── main.py               # FastAPI 入口
│   │   ├── config.py             # 环境变量配置（缺省走 stub）
│   │   ├── models.py             # Pydantic 模型 + 枚举
│   │   ├── events.py             # 事件总线（内存 + SQLite 持久化）
│   │   ├── sandbox.py            # Docker 沙箱（L1/L2/L3 网络分级）
│   │   ├── orchestrator/         # 编排核心
│   │   │   ├── state.py          # 控制信号 + 阶段流转
│   │   │   ├── nodes.py          # 六阶段节点
│   │   │   ├── runner.py         # 主循环 + 崩溃恢复
│   │   │   ├── charter.py        # 会议宪章
│   │   │   ├── conclusion_chain.py  # 结论锁定链
│   │   │   ├── react_loop.py     # ReAct 循环
│   │   │   └── refine_loop.py    # 代码自修复
│   │   ├── agents/               # Agent 计算层
│   │   ├── routers/              # 9 个 API 路由
│   │   ├── db/                   # SQLAlchemy 层（迁移中）
│   │   ├── rag/                  # 检索增强
│   │   ├── memory/               # 三层记忆
│   │   ├── observability/        # 日志/指标/成本追踪
│   │   ├── skills/, prompts/     # YAML 技能与约束
│   │   └── tools/                # Web 搜索/浏览器工具
│   └── tests/                    # 14 个测试文件
├── frontend/                     # React 19 + TS + Vite
├── docs/                         # 项目文档（分类归档）
│   ├── design/                   # 核心设计（6 篇）
│   ├── research/                 # 研究演进（5 篇）
│   ├── audits/                   # 审计报告（6 篇 + HTML 报告）
│   └── sessions/                 # 会话归档（6 篇）
├── docker-compose.yml            # 5 服务编排
└── .env.example                  # 环境变量模板
```

---

## 当前阶段

迭代一（主闭环）与迭代二（系统化升级）均已完成。已知问题和下一步方向见 [项目全面梳理报告](./docs/audits/project-review-2026-07-11.md)。摘要：

- 接入真实 LLM 做端到端验证（需配置 `CONCLAVE_LLM_API_KEY`）
- 三层记忆 SQLite 持久化（当前内存存储，接口已预留）
- 同步 pyproject.toml 与 requirements.txt
- 推进 db_legacy → SQLAlchemy 收敛
- Chunk Graph + 术语归一（v3 核心检索升级）
- Docker 容器化部署 + Demo 录制
