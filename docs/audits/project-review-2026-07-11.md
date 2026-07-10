# Conclave 项目全面梳理报告

> **日期**: 2026-07-11  
> **范围**: 全项目代码架构 + 文档组织 + 偏好系统 + 工程质量  
> **方法**: AST 语法校验全量 83 文件 + 逐模块阅读 + 测试执行 + 文档清点

---

## 一、项目概览

Conclave 是一个会议型多智能体系统，核心链路：

```
HTTP /api/meetings/{id}/run → Runner.run() 主循环 → 六阶段节点序列 → 事件总线广播 → WS 推前端 + SQLite 持久化
```

**六阶段**: clarify → intra_team → cross_team → evidence_check → arbitrate → produce  
**五层确定性**: 参数固定 → 结论锁定链 → LLM 自检 → 调用追踪 → StubLLM 降级

### 技术栈

| 层 | 实现 |
|---|---|
| 后端 | Python 3.13+ / FastAPI / Pydantic / httpx |
| 编排 | 六阶段状态机 + 控制信号（pause/resume/abort/inject/loan） |
| Agent | LocalAgentCompute + GRPCAgentCompute（Protocol 抽象） |
| LLM | OpenAI 兼容接口（SiliconFlow/Qwen）+ StubLLM 自动降级 |
| 检索 | bge-m3 embedding + bge-reranker-v2-m3 + Qdrant / 内存伪向量 |
| 沙箱 | Docker sibling 容器（L1/L2/L3 网络分级、资源限制、只读） |
| 前端 | React 19 + TypeScript + Vite 8 + Monaco / d3-force / echarts |
| 部署 | docker-compose（backend + frontend/nginx + qdrant + postgres + redis） |

### 模块职责速查

| 模块 | 职责 |
|---|---|
| `orchestrator/state.py` | 控制信号机 + 阶段流转（STAGE_ORDER / next_stage / is_terminal） |
| `orchestrator/nodes.py` | 六阶段节点实现 + NODES 注册表 + decide_next_stage 元认知路由 |
| `orchestrator/runner.py` | Runner.run() 主循环 + 进程级状态注册表 + 崩溃恢复 |
| `orchestrator/charter.py` | 会议宪章（不可变锚点 + 漂移检查 + 流程裁剪 simple/standard/full） |
| `orchestrator/conclusion_chain.py` | 结论锁定链（content_hash 一致性校验） |
| `orchestrator/react_loop.py` | ReAct 多轮工具循环（证据核验） |
| `orchestrator/refine_loop.py` | 代码自修复循环（产出阶段代码自修正） |
| `orchestrator/task_graph.py` | DAG 任务图调度器 — **死代码，无引用** |
| `agents/compute.py` | 计算抽象（Registry 模式消除 if/elif 分派） |
| `agents/llm.py` | RealLLM + StubLLM + 熔断器 + JSON schema 校验 |
| `agents/trace.py` | LLM 调用追踪（ContextVar + Pydantic 模型） |
| `events.py` | InMemoryEventBus（topic 订阅 + SQLite 持久化 + replay） |
| `sandbox.py` | Docker sibling 容器沙箱（网络分级 + 资源限制 + 降权） |
| `db/` | 新 SQLAlchemy 层（与 db_legacy.py 并存迁移中） |
| `rag/` | 检索增强（chunker + query_rewriter + retriever + store） |
| `memory/` | 三层记忆（Raw + Feature + Profile） |
| `observability/` | LogBus + metrics_store + cost_tracker + sinks |

---

## 二、问题清单

### P0 — 阻断性（已修复）

| # | 问题 | 影响 | 状态 |
|---|------|------|------|
| 1 | `runner.py` while 循环体缩进回归（AUDIT-FIX P0-4 引入） | 后端启动即崩溃 + 测试无法收集 | ✅ 本次修复 |
| 2 | `nodes.py` L1613 `break` 在 for 循环外（AUDIT-FIX P0-3 引入） | produce_node 导入失败 | ✅ 本次修复 |

**根因**: 上次审计修复在 runner.py 添加 try/except 时未同步缩进 while 循环体；在 nodes.py 添加连续失败 break 时放在了 for 循环外。**建议在 CI 加入 `python -m py_compile` 全量编译门禁，防止此类回归。**

### P1 — 严重

| # | 问题 | 维度 | 影响 |
|---|------|------|------|
| 1 | **双数据库层长期并存**: `db_legacy.py`(SQLite) 与 `db/`(SQLAlchemy) 同时使用，events.py publish 硬依赖 db_legacy | 架构 | 双写不一致风险，迁移未完成 |
| 2 | **进程内状态不可水平扩展**: `_states`、`_running_tasks`、`bus` 均为进程级单例 | 架构 | 多 uvicorn worker 下同一会议状态分裂 |
| 3 | **`_stage_loop_count` 用 setattr 挂在 Pydantic 模型上** (nodes.py L1822) | 代码质量 | 绕过校验、不持久化、重启丢失，元认知路由可能误判 |
| 4 | **`task_graph.py` 死代码** (完整 DAG 调度器，零引用) | 代码质量 | 过度设计未接入，增加维护负担 |
| 5 | **`@app.on_event("shutdown")` 已弃用** (main.py L183) | 代码质量 | 应并入 lifecycle yield |
| 6 | **`/health` 每次请求 spawn `docker info`** (timeout=3s) | 性能 | 高频探活开销大，应缓存 |
| 7 | **pyproject.toml 与 requirements.txt 不同步**: requirements.txt 多 8 个依赖未写入 pyproject.toml | 工程规范 | `pip install -e backend` 安装不完整 |

### P2 — 中等

| # | 问题 | 维度 | 影响 |
|---|------|------|------|
| 8 | **事件总线隐藏耦合**: `events.py` publish() 直接 `from app.db_legacy import save_event` | 架构 | 领域事件层反向依赖旧持久化层 |
| 9 | **日志体系不统一**: react_loop.py 用 `log_bus` 当 logger，其他用 `get_logger()` | 代码质量 | 日志格式不一致 |
| 10 | **认证/网络安全文件分散**: `net_auth.py`、`net_auth_manager.py`、`network_security.py`、`middleware.py` 四处涉及安全 | 可维护性 | 职责边界不清 |
| 11 | **db/ 层文件重叠**: `repository` vs `sqlalchemy_repo`、`vector_store` vs `qdrant_store` | 可维护性 | 分层需靠阅读 import 理解 |
| 12 | **CORS 默认 `*`** (dev 模式) | 安全 | 生产需限制 |
| 13 | **`/debug/auth-info` 路由始终挂载** (dev 模式返回明文 token) | 安全 | 生产网关需屏蔽 |
| 14 | **前端双锁文件**: `package-lock.json` + `pnpm-lock.yaml` 并存 | 工程规范 | packageManager 指定 pnpm，应删 npm lock |
| 15 | **测试覆盖空白**: routers (ws/documents/workspace/regression/preferences) 无独立路由级测试；安全模块无专项测试 | 测试 | 路由层和安全层回归风险 |

---

## 三、文档与偏好系统

### 3.1 文档分类结构（已归档）

```
docs/
├── design/          # 核心设计文档（6 篇）— 项目"宪法"级
│   ├── ideal-design.md           # 终态架构愿景
│   ├── design-principles.md      # 设计原则与固化条款
│   ├── mvp-plan.md               # v1 可执行计划
│   ├── architecture-review.md    # 架构评审与风险裁判
│   ├── iteration-1-design.md     # 迭代一详细设计
│   └── iteration-2-design.md     # 迭代二详细设计
├── research/        # 演进与研究文档（5 篇）
│   ├── architecture-evolution.md  # 架构演进方向
│   ├── skill-system-architecture.md  # Skill 系统设计
│   ├── mcp-research.md            # MCP 协议预研
│   ├── optimization-backlog.md    # 代码优化待办
│   └── test-rag-doc.md            # 测试用 RAG 素材
├── audits/          # 审计与修复报告（6 篇 .md + 5 个 HTML 报告目录）
│   ├── audit-2026-07-01.md
│   ├── audit-fix-report-v1.md
│   ├── audit-fix-report-2026-07-11.md
│   ├── fix-archive-2026-07-01.md
│   ├── browsertool-review-archive-2026-07-01.md
│   ├── e2e-verification-report.md
│   └── conclave-audit-v{2,3,4,5}/  # HTML 审计报告包
└── sessions/        # 会话归档（6 篇）— 按日期
    ├── session-archive-2026-06-28.md
    └── session-archive-2026-06-2{9,9-2,9-3,9-4,30}.md
```

### 3.2 偏好/配置文件

| 文件 | 类型 | 用途 |
|------|------|------|
| `backend/app/skills/ui_design_system.yaml` | Skill (优先级 90) | UI 设计规则、品牌色 #335c8e、CSS 反模式清单 |
| `backend/app/skills/code_conventions.yaml` | Skill (优先级 85) | 代码生成规范（项目结构/安全/Docker） |
| `backend/app/skills/communication_style.yaml` | Skill (优先级 80) | Agent 发言风格约束（标签格式/禁止 emoji） |
| `backend/app/skills/deliverable_quality.yaml` | Skill (优先级 75) | 产出质量验收清单 + Bug 严重等级定义 |
| `backend/app/prompts/bug_patterns.yaml` | Bug Pattern | 代码生成负面清单（30+ 条错误模式） |
| `backend/workspace/constraints.yaml` | 系统约束 | 7 条 hard/soft 约束（议题边界/借调审批等） |
| `.env.example` | 环境变量 | LLM/Embedding/Reranker/DB/Redis 配置模板 |

### 3.3 已清理的冗余

- ❌ `workspace/constraints.yaml` — 与 `backend/workspace/constraints.yaml` 重复，已删除
- ❌ `backend/app/observability/sink.py` — 与 `sinks.py` 重复且无引用，已删除

---

## 四、测试覆盖

### 当前状态

- **14 个测试文件**，覆盖核心流程、确定性、事件回放、记忆、可观测性、角色库、代码自修复等
- **15 passed / 1 failed**（`test_pause_resume_signal` — `KeyError: 'meeting_id'`，pre-existing，非本次引入）
- **1 error**（`psutil` 模块缺失，需 `pip install psutil`）
- `conftest.py` 有 autouse 状态重置，MockLLM fixture 可控

### 覆盖空白

| 缺失 | 风险 |
|------|------|
| routers/ws.py 独立测试 | WebSocket 连接管理回归 |
| routers/documents.py 独立测试 | 文档上传/分块回归 |
| 安全模块专项测试 (prompt_injection/sandbox) | 安全防护回归 |
| task_graph.py 测试 | 与死代码状态一致（应删或接入后补测）|

---

## 五、优先级建议

### 立即（CI 门禁）

1. **加入 `py_compile` 全量编译门禁** — 防止缩进/语法回归（本次 2 个 P0 均为此类）
2. **同步 pyproject.toml ≤ requirements.txt** — 确保 `pip install -e backend` 完整安装
3. **安装 psutil** — 修复测试套件 error

### 短期（1-2 周）

4. 删除 `task_graph.py` 死代码（或接入）
5. `_stage_loop_count` 改为 `MeetingState` 显式字段
6. `@app.on_event("shutdown")` 迁入 lifecycle yield
7. `/health` docker info 探测加缓存（30s TTL）
8. 修复 `test_pause_resume_signal` pre-existing 失败
9. 删除前端 `package-lock.json`（保留 `pnpm-lock.yaml`）

### 中期（持续推进）

10. 推进 `db_legacy.py` → `db/`(SQLAlchemy) 收敛，消除双写风险
11. 评估进程级状态外置（Redis/DB），为多 worker 做准备
12. 补充路由级测试和安全模块专项测试
13. 统一日志风格（去 `log_bus` 当 logger）
14. 收敛认证/网络安全文件到单一包

### 长期（v3 方向）

15. Chunk Graph + 术语归一
16. 多租户 + 自动借调
17. 完整执行风险分级 (L3)

---

## 六、值得肯定的设计

| 设计点 | 价值 |
|--------|------|
| 控制信号 + 节点 + 角色模板均用命令/注册表模式 | 符合开闭原则，扩展性好 |
| LLMClient/AgentCompute 用 Protocol 抽象 | Stub 与 Real 双路径保证可测试性 |
| 五层确定性保障 | 设计严谨，从参数固定到降级全覆盖 |
| LLM 熔断器 + 崩溃恢复 + 安全沙箱三网分级 | 工程化程度高 |
| 部署安全加固 | cap_drop ALL / no-new-privileges / 资源限制 / seccomp / --read-only + tmpfs |
| Skill + Bug Pattern 正负两面规范体系 | 知识沉淀可复用，避免同类错误重复 |

---

*调研时间: 2026-07-11*  
*调研人: SOLO AI Assistant*
