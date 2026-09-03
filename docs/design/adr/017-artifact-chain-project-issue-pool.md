# ADR-017: 产物链、项目命名空间与议题池（Artifact Chain, Project Namespace & Issue Pool）

## 状态

Accepted — 2026-09-04（三个可推翻点经用户裁决确认：D1 独立产物表、D4 三类型一次建齐、Phase 2/3 顺序调整为先议题池后测试闭环）

## 背景

### 问题陈述

用户提出了三个递进场景，代表 Conclave 从"一次一会的讨论工具"向"可持续生产的工程系统"演进：

1. **产物链**：基于一个话题/设想/需求 + 上传的设计文件、描述文件、项目文件夹，分析并生成不同阶段的产物，且**产物可链式续接**——会议 A 生成可行性报告，会议 A1 基于该报告生成 ADR，会议 A2 基于 ADR 生成可部署服务；也可以跳过中间环节直接生成可部署服务。
2. **测试生成闭环**：基于一个仓库/文件夹，生成对应测试用例 → 执行 → 生成测试报告 → 提交 git。
3. **议题池迭代**：基于一个仓库/文件夹不断重复迭代。议题来自该项目专属的议题池——议题可由会议自身在讨论中提出，也可由用户手动发送入池。一系列议题共享一个大 namespace，每个具体议题绑定自己的 workspace。

三个场景的共同底座是：**产物必须成为一等公民**（可被后续会议精确消费），**仓库必须成为组织单位**（议题、会议、产物围绕它聚合）。当前系统在这两点上都是断的。

### 代码核验（全部 grep 核实，2026-09-04）

```bash
# 1. 产物是无类型 dict，锁死在 meetings.payload 内
grep -n "artifact" backend/app/domain/meeting.py
#   → MeetingState.artifact: dict[str, Any] | None（domain/meeting.py:181）
#   → 无独立 artifacts 表，无版本，无跨会议引用能力

# 2. 跨会议引用只是 ID 列表，无产物级血缘
grep -n "reference_meeting_ids" backend/app/domain/meeting.py
#   → reference_meeting_ids: list[str]（domain/meeting.py:229），存于 payload
grep -n "reference_meeting_ids" backend/app/orchestrator/nodes/produce.py
#   → produce.py:726-734：仅 deployable_service 取最近一个引用会议作 baseline

# 3. meetings 表无 metadata 列（ADR-002 仅设计未落地），更无 project/issue 关联
grep -n "metadata" backend/app/db/models/meeting.py   # 零结果

# 4. workspace 隔离是约定而非实体：workspace/{meeting_id}/
grep -rn "workspace/{meeting_id}" backend/app/
#   → sandbox.py / routers/code.py / rag/code_index.py 均按此约定

# 5. 议题池完全不存在
grep -rn "议题池\|issue_pool" .   # 零结果

# 6. 现有 9 种产出类型，无 feasibility_report / adr / test_suite
grep -n "PRODUCE_TEMPLATES" backend/conclave_core/prompts.py
#   → prd_openapi / design_doc / comprehensive / research_report / business_report
#     / code_analysis / data_science / tested_system / deployable_service
```

### 现有能力与缺口

| 能力 | 状态 | 位置 |
|------|------|------|
| 多类型产出生成（9 种 deliverable_type） | ✅ 已有 | `conclave_core/prompts.py` + `orchestrator/nodes/produce.py` |
| 会议级引用（粗粒度续接） | ✅ 已有 | `reference_meeting_ids`（仅 ID，无产物级血缘） |
| 仓库摄入（Git URL + zip） | ✅ 已有 | `routers/code.py`（ADR-016 Phase A） |
| 代码理解与图检索 | ✅ 已有 | `rag/code_*.py`（ADR-016，按 meeting_id 隔离） |
| Docker 沙箱分级执行（L1/L2/L3） | ✅ 已有 | `sandbox.py` |
| 产物独立实体（可查询/可版本化/可血缘追溯） | ❌ 缺失 | 产物是 payload 内无类型 dict |
| 可行性报告 / ADR / 测试套件产出类型 | ❌ 缺失 | 无对应模板（可行性仅是角色立场 `feasibility-first`） |
| 仓库级组织单位（namespace） | ❌ 缺失 | 无 projects 实体 |
| 议题池与议题-工作区绑定 | ❌ 缺失 | 无任何相关实体 |
| 产物驱动的测试执行 + git 提交 | ❌ 缺失 | 无此工作流 |

## 决策

### 核心抽象：三个一等公民

```
Project（项目 = 绑定仓库的 namespace）
  ├── Issue（议题：来自用户手动 或 会议候选经人工确认）
  │     └── Meeting（会议：议题的执行单位，绑定自己的 workspace）
  │           └── Artifact（产物：会议 publish 出的一等实体）
  │                 └── lineage（血缘：derived_from 上游产物）
  └── Artifact 也可直属于 Project（不经过议题的会议产物）
```

- **Artifact**：会议产出从"payload 里的 dict"升格为独立表实体。会议是生产单位，产物是流通单位。
- **Project**：仓库绑定的 namespace，是议题、会议、产物、（未来的）代码库理解索引的聚合根。
- **Issue**：项目下的迭代单元，每个议题绑定一个执行会议，会议 workspace 即议题 workspace。

### 数据模型（核心表，走 Alembic 迁移，遵守 AGENTS.md §5.6）

```sql
-- 产物：一等公民
artifacts (
  id              uuid PK,
  tenant_id       varchar NOT NULL,          -- P8 多租户隔离
  meeting_id      uuid NOT NULL,             -- 生产会议
  project_id      uuid NULL,                 -- 可选归属项目
  type            varchar NOT NULL,          -- feasibility_report | adr | prd | openapi |
                                             -- code_analysis | test_suite | test_report |
                                             -- deployable_service | research_report | ...
  title           varchar(500),
  summary         text,                      -- 供后续会议消费的浓缩摘要（控制 prompt 体积）
  content         jsonb NULL,                -- 小型结构化内容（ADR 正文、报告元数据）
  content_ref     varchar NULL,              -- 大型内容指针：workspace 相对路径（代码/文件不入库）
  version         int DEFAULT 1,             -- 同会议同类型重生成时递增
  parent_id       uuid NULL,                 -- 上一版本（版本链）
  source_artifact_ids jsonb DEFAULT '[]',    -- 血缘：本产物消费了哪些上游产物
  created_at, created_by
)

-- 项目：仓库绑定的 namespace
projects (
  id              uuid PK,
  tenant_id       varchar NOT NULL,
  slug            varchar(100) NOT NULL,     -- namespace 标识，tenant 内唯一
  name            varchar(200) NOT NULL,
  repo_url        varchar NULL,              -- 绑定的仓库（可空：纯文档型项目）
  default_branch  varchar DEFAULT 'main',
  description     text,
  created_by, created_at, updated_at,
  UNIQUE (tenant_id, slug)
)

-- 议题：项目下的迭代单元
issues (
  id              uuid PK,
  tenant_id       varchar NOT NULL,
  project_id      uuid NOT NULL REFERENCES projects,
  title           varchar(500) NOT NULL,
  body            text,
  source          varchar NOT NULL,          -- user（手动）| meeting（会议候选，经确认）
  source_meeting_id uuid NULL,               -- 提出该议题的会议
  status          varchar DEFAULT 'open',    -- open | scheduled | in_progress | resolved | wontfix
  priority        int DEFAULT 50,
  assigned_meeting_id uuid NULL,             -- 当前绑定的执行会议
  resolution_artifact_id uuid NULL,          -- 解决该议题的产物（闭环凭证）
  created_by, created_at, updated_at
)

-- meetings 表增加两个可空外键
ALTER TABLE meetings ADD COLUMN project_id uuid NULL;
ALTER TABLE meetings ADD COLUMN issue_id   uuid NULL;
```

**Publish 模式（关键机制）**：会议运行期间 `state.artifact` 仍是工作副本（不改动编排器现有写入路径）；produce 节点成功 + 质量门禁通过后，由 Runner 统一 `publish` 到 `artifacts` 表——幂等（同 `meeting_id + type + version` 去重）、单向（运行态不回读表）。这避免编排器中途双写带来的状态机契约风险（ADR-013）。

### 关键决策点

| # | 决策 | 理由 | 备选（否决原因） |
|---|------|------|------|
| D1 | 产物走**独立 `artifacts` 表**，不走 `meetings.metadata` JSONB | 产物是核心业务实体而非插件扩展：需要被查询、血缘追溯、版本化、跨会议消费；ADR-002 的 metadata 定位是插件命名空间且至今未落地；payload 内 dict 无类型、无法 SQL 检索 | metadata JSONB：定位不符 + 未落地；继续 payload：锁死在单会议内 |
| D2 | **Publish 模式**：运行态用 `state.artifact`，会议成功后单向发布入表 | 不改编排器中途写入路径，规避状态机契约风险（ADR-013）；发布幂等可重试 | 编排器实时双写：中途失败导致表与 payload 不一致 |
| D3 | 血缘**双轨**：保留 `reference_meeting_ids`（会议级，向后兼容），新增产物级 `source_artifact_ids` | 会议级引用继续服务"参考某次会议的讨论"；产物级血缘服务"精确消费某个上游产物"。新会议创建时可勾选上游产物，系统自动展开其摘要注入 | 只留会议级：无法区分"参考整场会议"与"消费某个具体产物" |
| D4 | 新增产出类型 `feasibility_report` / `adr` / `test_suite`，各配 produce 模板，**三类型一次建齐**（Phase 1 全部落地） | 产物链的每个环节都应有独立类型与质量门禁，而非塞进 `comprehensive`；一次建齐避免后续补建返工（用户裁决 2026-09-04：底座先建，用量上来后再改复杂度高）；`test_report` 作为 `test_suite` 的伴生产物（执行结果），不单设类型 | 复用现有类型：门禁与模板无法差异化；按 Phase 分期建类型：后续补建导致模板/门禁返工 |
| D5 | `projects` 表作为仓库绑定 namespace，`slug` tenant 内唯一 | 议题池、会议、产物、代码库理解索引都需要一个共同聚合根；slug 同时预留为 Qdrant workspace / LightRAG namespace 的隔离键（与代码库理解层对齐，见 ADR-018 D3 `{tenant_id}:{project_slug}`） | 用 metadata 模拟：无实体则无法挂议题与外键 |
| D6 | workspace 层级**保持** `workspace/{meeting_id}/` 为执行单位；`workspace/projects/{slug}/` 仅作项目级共享只读区（仓库缓存/共享文档），随项目 Phase 2 建立（仓库克隆缓存见 Phase 4） | 执行隔离边界不动（沙箱、防穿越、会议间隔离全部复用）；共享区只读，避免并发写冲突 | 议题共享单一工作区：并发会议互相踩踏 |
| D7 | 议题入池**必须人工确认**：会议中主持人收集"候选议题"，用户确认后才写入 `issues`（source=meeting） | 防止 LLM 噪声议题污染池子；与"不令用户意外"的交互原则一致；用户手动入池（source=user）不受限 | 会议自动入池：低质量议题泛滥，治理成本高于收益 |
| D8 | git 操作分级护栏：**commit 可自动**（workspace 内、bot 身份、Conventional Commits）；**push 必须用户显式确认**（API 确认参数 + UI 展示 diff 摘要） | 与 AGENTS.md §0.5.1 不可逆操作策略一致；commit 可回退，push 进入共享空间不可控 | push 也自动：违反既有纪律且风险不可逆 |
| D9 | **自主迭代循环是理想态，不是 MVP**：本 ADR 只定义调度契约（按优先级取 open 议题 → 建会 → 质量门禁 → commit → 更新状态 → 下一条），实施推迟到 Phase 4 且另开 ADR | 自动循环的成本与质量风险（token 爆炸、错误累积、仓库被写坏）需要配额（ADR-007）+ 每日上限 + 人工审批开关先行 | 直接实现：风险敞口过大，属"凭理想编码" |
| D10 | 新表全部带 `tenant_id` + DAO 层隔离，跨租户产物引用拒绝复用 `produce.py:734` 现有模式 | P8 多租户隔离 Checklist 是红线，漏一个 DAO 就跨租户泄露 | — |

### 场景映射（用户三个目标 → 机制）

| 用户场景 | 落地机制 | 阶段 |
|----------|----------|------|
| 话题+资料 → 可行性报告 → ADR → 可部署服务（链式） | 每环节一次会议 + 对应 deliverable_type；创建下游会议时勾选上游产物，`source_artifact_ids` 记血缘，产物 `summary` 注入下游 prompt | Phase 1 |
| 话题 → 直接生成可部署服务（跳级） | 现状已支持（`deliverable_type=deployable_service`），不变 | 已有 |
| 上传设计文件/项目文件夹作为输入 | 现状已支持（`routers/code.py` 摄入到 `workspace/{meeting_id}/`），产物链中作为会议输入而非产物 | 已有 |
| 仓库 → 生成测试用例 → 执行 → 测试报告 → 提交 git | `test_suite` 类型会议：produce 生成测试代码落 workspace → 沙箱执行（L2/L3）→ `test_report` 伴生产物 → 自动 commit / 确认后 push | Phase 3 |
| 项目专属议题池（会议提出 + 用户发送） | `projects` + `issues`；会议候选经确认入池，用户手动直发 | Phase 2 |
| 议题共享 namespace、各绑自己的 workspace | namespace = `projects.slug`；议题 → `assigned_meeting_id` → `workspace/{meeting_id}/`；仓库从项目共享区克隆 | Phase 2（共享区缓存 Phase 4） |
| 不断重复迭代（自动循环） | 调度契约已定义，实施推迟（D9） | Phase 4，另开 ADR |

### 与设计原则及相关 ADR 的对齐

- **原则 7 反架构沉迷 / 原则 8 演进式架构**：四阶段推进，Phase 1 加一张表 + 一次建齐三种产出类型即跑通最小产物链闭环。产出类型一次建齐（用户裁决，避免后续补建返工），但执行闭环与组织层仍按 Phase 演进，机制层不做一次性大而全。
- **ADR-002（JSONB metadata）**：本 ADR 不依赖其落地；产物/项目/议题是核心实体走核心表，metadata 仍留给插件扩展。两者不冲突。
- **ADR-013（状态机契约）**：Publish 模式保证编排器运行态不被新表污染；新产出类型必须注册对应质量门禁评估方法（`runner.py:1129` 分派点）。
- **ADR-014（动态工作流）**：`feasibility_report` / `adr` / `test_suite` 各配 workflow 模板（复用 `workflow_template` 机制，domain/meeting.py:194）。
- **ADR-016（代码知识图谱）**：项目 namespace 是代码库理解索引的天然隔离单位；`projects.slug` 预留为索引 workspace 键。当前图索引按 meeting_id 隔离（内存注册表），项目级共享索引属 Phase 4，由 ADR-018（LightRAG/Qdrant workspace 按 slug 隔离）承接。

## 分阶段实施计划

### Phase 1：产物一等公民 + 产物链最小闭环 + 三类型一次建齐（MVP，3-5 天）

1. Alembic 迁移：`artifacts` 表；`meetings` 加 `project_id` / `issue_id` 可空列（先建列，外键目标表 Phase 2 落地）。
2. `app/db/models/artifact.py` + DAO（含 tenant 隔离）+ schema 层 + 前端类型。
3. Publish 机制：Runner 在会议成功终态处调用 `artifact_service.publish(state)`，幂等去重。
4. **一次建齐 `feasibility_report` / `adr` / `test_suite` 三个 produce 模板与质量门禁**（用户裁决：三类型一次建齐，避免后续补建返工；`test_suite` 的执行闭环在 Phase 3 落地）。
5. 会议创建 API 扩展：`source_artifact_ids` 入参；被引用产物的 `summary` 注入 clarify/produce prompt。
6. 产物：用户能"会议 A 出可行性报告 → 会议 A1 引用该产物出 ADR → 会议 A2 引用 ADR 出可部署服务"，血缘可查。

### Phase 2：项目与议题池（3-5 天）

> 用户裁决 2026-09-04：议题池（底座）提前到 Phase 2 先建，避免后续用量上来后再改、复杂度高（返工成本大）。

1. Alembic 迁移：`projects` / `issues` 表；补 `meetings.project_id/issue_id` 外键。
2. 议题两条入口：用户手动创建（source=user）；会议中主持人汇总候选议题 → 用户在会中/会后确认入池（source=meeting）。
3. 议题 → 会议绑定：从议题发起会议时自动填充 `project_id` / `issue_id`，仓库摄入到该会议 workspace。
4. 议题状态机随会议生命周期流转（in_progress → resolved 需挂 `resolution_artifact_id`）。
5. 产物：一个项目下多议题并行，各会议工作区隔离，议题闭环可追溯。

### Phase 3：测试生成闭环（3-5 天）

1. `test_suite` workflow 模板执行闭环（类型与 produce 模板已在 Phase 1 一次建齐）：分析目标仓库（复用 ADR-016 代码检索）→ 生成测试代码落 `workspace/{meeting_id}/`。
2. 沙箱执行测试（L2/L3 网络分级），捕获结果生成 `test_report` 伴生产物。
3. git 护栏：workspace 内自动 commit（bot 身份、Conventional Commits、禁止混入临时文件）；`POST /artifacts/{id}/push` 需显式确认参数，返回 diff 摘要供 UI 展示。
4. 产物：仓库进 → 测试用例 + 执行报告出 → 提交可追溯。

### Phase 4：理想态（另开 ADR，本 ADR 只留契约）

1. **自主迭代调度器**：按优先级消费议题池，受配额（ADR-007）+ 每日上限 + 人工审批开关约束。
2. **项目级仓库缓存**：`workspace/projects/{slug}/` 共享克隆 + git worktree 派生议题工作区，省去重复 clone。
3. **项目级代码库理解索引**：LightRAG/Qdrant workspace 按 `projects.slug` 隔离，跨会议复用（承接 ADR-016 后续，详见 ADR-018）。
4. **产物版本演进**：同项目同类型产物的 diff/merge 视图。

### 测试策略（用户约定）

- **测试后置、整体实现后统一跑**：各 Phase 开发期间只写测试、不逐次跑容器；全部 Phase 完成后在 Docker 容器内一次性跑 `ruff check` + `ruff format --check` + `mypy` + `pytest` 全套，避免多次容器启停浪费 token/时间（用户裁决 2026-09-04：底座先建、整体实现后再测试）。

## 约束与风险

### payload 与 artifacts 表的双源一致性

- Publish 是单向幂等的（会议成功终态触发，失败可重试）；运行态永远以 `state.artifact` 为准，表只是发布快照。历史会议**不回填**——旧产物仍可从 payload 读取，新产物走新表，读取层做兼容聚合。

### 大产物不入库

- `deployable_service` 的代码、测试套件源文件只存 workspace 文件系统，`artifacts` 表存 `content_ref` 指针 + `summary`。DB 只承载可查询的结构化元数据，防止 TOAST 膨胀。

### 议题池噪声

- 会议候选议题必须人工确认（D7）；`wontfix` 状态保留拒绝痕迹，防止同一议题被反复提出。

### 新表工程量

- 三张核心表意味着 Alembic + DAO + schema + 前端类型四层全动（AGENTS.md §5.6）。因此严格按 Phase 拆分提交，每个 Phase 独立可回退。

### 多租户

- `artifacts` / `projects` / `issues` 全部 `tenant_id` 强制；跨租户引用产物在注入 prompt 前拒绝（复用 `produce.py:734` 的校验模式）。

## 不做的事

- 不建独立产物存储/对象存储服务——workspace 文件系统在本阶段足够。
- 不做议题自动生成（会议候选必须人工确认）。
- 不做跨租户产物共享。
- 不做产物内容级 diff/merge（版本只是递增整数 + `parent_id` 指针）。
- 不做仓库 webhook 持续同步（与 ADR-016 一致）。
- 不在本 ADR 实施自主迭代循环（Phase 4，另开 ADR）。
- 不动 `reference_meeting_ids` 现有行为（只增不改）。
