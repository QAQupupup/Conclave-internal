# Conclave Backend

[返回项目主页](../README.md) | Python 3.12 + FastAPI + asyncio 后端服务。

## 子模块文档

后端按职责拆分为多个子系统，每个子系统有独立 README 详述架构与扩展方式：

| 子系统 | 文档 | 核心职责 |
|---|---|---|
| **编排核心** | [orchestrator/README.md](app/orchestrator/README.md) | 六阶段会议管线、上下文治理、质量门禁、任务图调度 |
| **Agent 计算层** | [agents/README.md](app/agents/README.md) | LLM 调用封装、7 种角色定义、Prompt 管理、全链路追踪 |
| **检索增强** | [rag/README.md](app/rag/README.md) | 文档分块、混合检索（向量+关键词）、HyDE、Multi-Query、重排序 |
| **插件框架** | [plugins/README.md](app/plugins/README.md) | Hook 机制、三层分级（CORE/RUNTIME/OPTIONAL）、PluginEventBus |
| **可观测性** | [observability/README.md](app/observability/README.md) | 统一日志、成本追踪、指标采集、审计日志 |
| **数据层** | [db/README.md](app/db/README.md) | 异步引擎、ORM 模型、Redis、向量存储抽象 |
| **记忆系统** | [memory/README.md](app/memory/README.md) | 三层记忆（Raw/Feature/Profile）、画像演化 |
| **工具与基础设施** | [tools/README.md](app/tools/README.md) | Web 搜索、浏览器自动化、Docker 沙箱、事件总线 |

## 模块结构

```
backend/
├── app/
│   ├── main.py              # FastAPI 入口，路由注册，生命周期
│   ├── config.py            # 环境变量配置（Pydantic BaseSettings）
│   ├── middleware.py         # CORS、认证、租户上下文中间件
│   │
│   ├── orchestrator/        # 会议编排核心
│   │   ├── runner.py        # 会议运行器（异步任务执行）
│   │   ├── manager.py       # MeetingManager：统一交互层
│   │   ├── stage_runners.py # 六阶段执行逻辑（clarify→produce）
│   │   ├── context_manager.py # 上下文治理（token 预算、压缩、裁剪）
│   │   ├── task_graph.py    # DAG 任务图（拓扑排序、递归子任务）
│   │   └── nodes/           # 各阶段节点（intra_team/cross_team/arbitrate 等）
│   │
│   ├── agents/              # Agent 计算层
│   │   ├── compute.py       # LLM 调用统一入口
│   │   ├── agent_runtime.py # 统一 Agent 运行时
│   │   ├── llm.py           # LLM 客户端管理（单例、重试、fallback）
│   │   ├── prompts.py       # Prompt 模板
│   │   ├── roles.py         # 角色定义与模板
│   │   ├── trace.py         # CallTrace 全链路追踪
│   │   └── task_baseline.py # 领域基线模板
│   │
│   ├── routers/             # API 路由
│   │   ├── meetings.py      # 会议 CRUD + 控制
│   │   ├── ws.py            # WebSocket 实时事件
│   │   ├── docker_hosts.py  # Docker 主机管理
│   │   ├── audit_logs.py    # 审计日志查询
│   │   └── ...
│   │
│   ├── rag/                 # 检索增强生成
│   │   ├── store.py         # 向量存储（Qdrant/内存）
│   │   ├── retriever.py     # 多路召回 + 重排序
│   │   ├── hyde.py          # HyDE 假设文档嵌入
│   │   ├── query_rewriter.py # Multi-Query 查询扩展
│   │   └── chunker.py       # 文档分块
│   │
│   ├── sandbox.py           # Docker 沙箱管理
│   ├── events.py            # 事件总线（内存 + PG + Redis Pub/Sub）
│   ├── lazy_asyncio.py      # 循环感知的 asyncio 原语
│   │
│   ├── plugins/             # 插件框架
│   │   ├── core/            # 插件核心（registry、hooks、event_bus）
│   │   └── builtin/
│   │       └── auth/        # JWT 认证插件（CORE tier）
│   │
│   ├── tenants/             # 多租户隔离
│   │   ├── context.py       # 租户上下文（ContextVar）
│   │   ├── service.py       # 租户服务（自动迁移）
│   │   └── settings_override.py # 租户级配置覆盖
│   │
│   ├── observability/       # 可观测性
│   │   ├── audit.py         # AuditLogger 审计日志
│   │   ├── cost_tracker.py  # Token/成本追踪
│   │   ├── log_bus.py       # LogBus 统一日志总线
│   │   ├── metrics_store.py # MetricsStore 环形缓冲区
│   │   └── sinks.py         # 日志 Sink（文件/控制台/EventBus）
│   │
│   ├── tools/               # 工具集
│   │   ├── playwright_search.py # Playwright Web 搜索
│   │   ├── browser_tool.py  # 浏览器自动化工具
│   │   └── ...
│   │
│   ├── memory/              # 三层记忆
│   │   ├── models.py        # RawMemory/FeatureMemory/ProfileMemory
│   │   ├── profile.py       # 画像演化
│   │   └── store.py         # 记忆存储（PostgreSQL）
│   │
│   ├── db/                  # 数据层
│   │   ├── engine.py        # 异步 SQLAlchemy 引擎（循环感知单例）
│   │   ├── base.py          # Declarative Base
│   │   └── models/          # ORM 模型
│   │
│   ├── dao/                 # 数据访问对象
│   ├── domain/              # 领域模型与枚举
│   └── services/            # 业务服务
│
├── conclave_core/           # 核心算法模块（部分 Cython 编译）
│   ├── anchor.py            # 锚点管理（Pydantic 模型，保留源码）
│   ├── charter.py           # 会议章程（Pydantic 模型，保留源码）
│   ├── conclusion_chain.py  # 结论链（Pydantic 模型，保留源码）
│   └── *.so                 # 编译的核心逻辑（charter_logic/conclusion_logic/confidence/evidence/roles/scheduler/state/text）
│
├── tests/                   # 测试文件（pytest + pytest-asyncio）
├── alembic/                 # 数据库迁移
├── Dockerfile               # 后端容器镜像
├── pyproject.toml           # 项目配置与依赖声明
└── requirements.lock        # 锁定依赖版本
```

## 会议管线

```
clarify → intra_team → cross_team → evidence_check → arbitrate → produce
  │           │            │              │            │          │
  │           │            │              │            │          └─ 生成最终产出物
  │           │            │              │            └─ 仲裁争议、采纳论点
  │           │            │              └─ 对照证据验证论点、降级无证据论点
  │           │            └─ 识别冲突点、跨队辩论
  │           └─ 全并发独立立论（ADR-010，消除锚定偏误）
  └─ 主持人拆解议题、明确团队
```

每个阶段由 `stage_runners.py` 中的 `run_*` 函数执行，通过 `MeetingManager` 统一调度 Storage、EventBus、Sandbox、Agent。

质量门禁：如果某阶段输出不达标，管线自动回流补充（如 evidence_check 发现论点证据不足，触发 supplement 模式让相关角色补充论点）。

## 插件框架

插件分为三个 tier：

| Tier | 启动时机 | 失败影响 | 示例 |
|---|---|---|---|
| CORE | 服务启动前 | 阻止启动 | auth |
| RUNTIME | 服务启动后 | 记录错误，不阻塞 | observability 扩展 |
| OPTIONAL | 按需加载 | 忽略 | 第三方集成 |

插件通过 Hook 机制介入核心流程（`lifecycle`、`llm`、`meeting` 三类钩子），通过 `PluginEventBus` 进行插件间通信。

## 多租户隔离

- 所有业务表包含 `tenant_id` 列，DAO 层自动追加 `WHERE tenant_id = :tid`
- 租户上下文通过 `ContextVar`（`tenants/context.py`）传递
- 系统操作用 `create_system_tenant_ctx()` 包裹
- 外键统一 `ON DELETE SET NULL`，测试清理用 `DELETE + RESTART SEQUENCE` 代替 `TRUNCATE CASCADE`
- 跨租户操作必须显式使用系统租户上下文，否则 tenant_filter fail-closed 返回 FALSE

## API 路由

路由无全局 `/api` 前缀，自动生成 OpenAPI 文档在 `/docs`。

| 路由模块 | 前缀 | 主要端点 |
|---|---|---|
| meetings | `/meetings` | CRUD、run、control、documents |
| ws | `/ws` | `/ws/meetings/{id}` WebSocket |
| docker_hosts | `/docker-hosts` | Docker 主机 CRUD、健康检查 |
| audit_logs | `/audit-logs` | 审计日志查询 |
| auth (plugin) | `/auth` | login、logout、me、refresh、setup |
| tenants (plugin) | `/tenants` | 租户管理 |

## 开发指南

### 环境准备

```bash
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

### 运行

```bash
# 需先启动 PostgreSQL、Redis、Qdrant（可用 docker-compose up -d postgres redis qdrant）
uvicorn app.main:app --reload --port 8000
```

### 代码质量

```bash
# 本地快速检查（非容器，仅作快速反馈）
python -m ruff check app conclave_core tests
python -m ruff format --check app conclave_core tests

# 完整 CI 一致性检查（Docker 容器内，最终验证）
docker compose -f docker-compose.test.yml up --build --exit-code-from backend-test
```

### 测试

```bash
# Docker 容器内全量测试（推荐）
docker compose -f docker-compose.test.yml up --build --exit-code-from backend-test

# 本地快速测试（需配置好数据库连接）
pytest tests/ -v --tb=short
```

### 数据库迁移

```bash
# 创建迁移
alembic revision --autogenerate -m "description"

# 执行迁移
alembic upgrade head
```

注意：`alembic/env.py` 不能直接 `python` 运行，必须通过 `alembic` CLI 调用。

## 关键设计原则

参见项目根目录的 `docs/design/design-principles.md` 和 ADR 文档（`docs/design/adr/`）。核心原则：

1. **asyncio 原生**：禁止阻塞调用，使用 `LazyLock`/`LazySemaphore` 避免事件循环绑定问题
2. **证据诚实**：无证据论点必须降级置信度，禁止编造引用
3. **单例循环感知**：持有 asyncio 原语的单例必须检测循环变化并重建
4. **Docker 沙箱**：代码执行一律在容器内，禁止在主进程执行任意代码
5. **JSONB 扩展槽**：非核心字段优先使用 `meetings.metadata` JSONB，不随意加核心列
