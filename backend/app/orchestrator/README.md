[返回上级文档](../../README.md)

# Orchestrator 编排模块

会议编排核心 —— 六阶段多 Agent 辩论管线、上下文治理、质量门禁与自动回流。

---

## 1. 模块定位

Orchestrator 是 Conclave 的"操作系统内核"，位于 Agent 网络之上，负责：

- **管线调度**：将一次会议目标拆解为六个有序阶段，驱动多 Agent 协同完成从议题澄清到产物交付的全流程。
- **上下文治理**：在 token 预算约束下，为每次 LLM 调用准备分层上下文切片，超预算时自动摘要压缩而非硬截断。
- **质量门禁**：produce 阶段完成后多维度评分（部署、测试、架构完整性、代码真实性等），不达标则自动触发迭代重产出。
- **模式分流**：入口处通过 LLM 语义分类，将简单查询路由到 Instant 快路径，复杂议题走完整六阶段管线。
- **容错恢复**：阶段级断点续传（checkpoint + 重试）、阶段回退上限保护、全局异常兜底标记 FAILED。

---

## 2. 架构总览

```
┌─────────────────────────────────────────────────────────────────────┐
│                              Runner                                 │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │  while not is_terminal(state):                               │  │
│  │    1. 处理用户介入消息 (_process_interventions)               │  │
│  │    2. manager.run_stage(state, current_stage)                │  │
│  │    3. 借调 Agent 发言 (_let_borrowed_agents_speak)            │  │
│  │    4. 持久化 checkpoint                                      │  │
│  │    5. 质量门禁评估 (_evaluate_quality) → 决定是否迭代         │  │
│  │    6. 动态路由 decide_next_stage（元认知 Agent）              │  │
│  │    7. publish stage.changed                                  │  │
│  └───────────────────────────────────────────────────────────────┘  │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                          MeetingManager                              │
│                                                                     │
│  run_stage(state, stage):                                           │
│    Planner ──► Scheduler(DAG) ──► Reducer ──► StageRunner           │
│       │              │               │              │               │
│       ▼              ▼               ▼              ▼               │
│  stage_planners   conclave_core   stage_reducers  stage_runners     │
│  (拆SubTask)     .Scheduler      (归约结果)      (写回State)        │
│                     │                                               │
│                     ▼                                               │
│              _execute_subtask(task, ctx):                           │
│                1. context_manager.prepare_async() → ContextSlice    │
│                2. build_agent_from_baseline() → Agent               │
│                3. agent.execute() → AgentResult                     │
│                4. (可选) ReactLoop / RefineLoop 工具调用/代码修复    │
└─────────────────────────────────────────────────────────────────────┘
                               │
          ┌────────────────────┼────────────────────┐
          ▼                    ▼                    ▼
┌──────────────┐    ┌──────────────────┐   ┌───────────────┐
│ContextManager│    │  nodes/* (legacy)│   │ Instant Path  │
│  分层上下文   │    │  兼容层节点函数   │   │  单Agent快路径 │
│  动态窗口     │    │  → 委托StageRunner│   │  classify→run │
│  摘要压缩     │    │                  │   │               │
└──────────────┘    └──────────────────┘   └───────────────┘
```

---

## 3. 六阶段管线

标准会议模式 (`flow_plan=standard`) 按以下顺序推进，动态路由允许在约束下回退：

```
clarify ──► intra_team ──► cross_team ──► evidence_check ──► arbitrate ──► produce
   │            │              │               │              │           │
   ▼            ▼              ▼               ▼              ▼           ▼
 议题澄清     队内观点      跨队辩论        证据核查        裁决决策     产出交付
 生成宪章     各角色独立    反驳/引用       对照证据        采纳/驳回     分阶段生成
 团队配置     发表 claims   claims          验证 claims     claims       代码/文档
```

### 3.1 clarify（议题澄清）

- **角色**：主持人（moderator）单 Agent
- **输入**：原始 topic + doc_summaries + reference_context
- **输出**：`clarified_topic`、`key_questions[]`、`team_config[]`、`charter`（会议宪章）
- **副作用**：锁定 clarify 结论到 `conclusion_chain`，根据复杂度设置 `flow_plan`（simple/standard/full）和 `debate_depth`（light/standard/deep）

### 3.2 intra_team（队内观点）

- **角色**：team_config 中每个角色**并行**独立发言（DAG 同层并行）
- **输入**：charter + 已锁定结论 + 角色立场
- **输出**：各角色的 `claims[]`（含论点、论据、置信度）
- **特殊**：门禁 supplement 模式下仅为 `target_roles` 创建补充任务，不全量重跑

### 3.3 cross_team（跨队辩论）

- **角色**：所有团队成员，针对他方 claims 进行反驳/补充/引用
- **输入**：intra_team 产出的全部 claims
- **输出**：`conflicts[]`（冲突点）、跨队引用关系、补充 claims
- **回退**：evidence_check 发现证据不足时可回退到此阶段重新辩论

### 3.4 evidence_check（证据核查）

- **角色**：按 conflict 拆分为**并行**子任务，核查冲突论点的证据支撑
- **输入**：conflicts + 检索到的证据/物料
- **输出**：每个 conflict 的证据验证结果（supported/contradicted/insufficient）
- **工具**：可调用 ReactLoop 执行网络搜索、文档检索等

### 3.5 arbitrate（裁决决策）

- **角色**：主持人/仲裁者
- **输入**：claims + conflicts + evidence 结果
- **输出**：`decision_record`（decisions + adopted_claims + action_brief）
- **特殊**：无冲突时自动采纳所有 claims；锁定裁决结论

### 3.6 produce（产出交付）

- **角色**：产出 Agent（不走 SubTask 调度，reducer 直接调用，避免重复 LLM 生成）
- **机制**：分阶段生成管线（PhasedGenerationPipeline），每次 LLM 调用仅输出 2-5 个聚焦文件，避免单次输出过长导致截断/幻觉
- **输出**：`artifact`（deployable_service + review + deployment + test_results）
- **后处理**：触发质量门禁评估，决定是否迭代重产出

---

## 4. 关键文件索引

| 文件 | 职责 |
|---|---|
| `runner.py` | **编排运行器**：主循环、状态机驱动、介入处理、断点续传、动态路由、质量门禁触发、内存 LRU 清理 |
| `manager.py` | **会议管理器**：Planner→Scheduler→Reducer 统一路径、子任务执行、Agent 构建、上下文注入、熔断治理 |
| `stage_runners.py` | **阶段业务逻辑**：六阶段结果写回 MeetingState 的纯逻辑层（与 LLM 节点解耦） |
| `stage_planners.py` | **阶段规划器**：将每个阶段展开为 SubTask DAG（intra_team 按角色拆并行，evidence_check 按 conflict 拆并行） |
| `stage_reducers.py` | **阶段归约器**：将 Scheduler 返回的多 SubTask 结果归约回 MeetingState，委托给 stage_runners |
| `stage_common.py` | **阶段共享辅助**：emit_agent_spoke、record_message、record_drift 等有副作用的辅助函数 |
| `context_manager.py` | **上下文治理**：ContextBudget 预算、ContextSlice 分层切片、动态窗口、LLM 摘要压缩 |
| `task_graph.py` | **DAG 任务图**：Task/TaskGraph 数据结构，拓扑排序分层，供低层任务编排使用 |
| `instant.py` | **Instant 快路径**：意图分类（LLM 语义分流）、normalize_mode、run_instant 单 Agent 即时回答 |
| `react_loop.py` | **ReAct 循环**：think→act→observe 自主工具调用循环，ToolRegistry 工具注册，卡死检测，O(1) 上下文 |
| `refine_loop.py` | **RefineLoop 代码自修复**：给定报错修正代码的受控重执行循环，重复检测，max_rounds 硬上限 |
| `phased_generation.py` | **分阶段生成管线**：ModuleDef/ArchitecturePlan 数据结构，将大产出拆分为多次 LLM 调用 |
| `nodes/__init__.py` | **节点注册表**：NODES 字典（Stage→node 函数），向后兼容 re-export |
| `nodes/clarify.py` | clarify 节点（legacy wrapper，委托 stage_runners.run_clarify） |
| `nodes/intra_team.py` | intra_team 节点（legacy wrapper） |
| `nodes/cross_team.py` | cross_team 节点（legacy wrapper） |
| `nodes/evidence_check.py` | evidence_check 节点（legacy wrapper） |
| `nodes/arbitrate.py` | arbitrate 节点（legacy wrapper） |
| `nodes/produce.py` | produce 节点 + 分阶段生成 + 进度事件 + 网络等级检测 |
| `nodes/routing.py` | 元认知路由：decide_next_stage、循环计数、阶段跳转白名单、强制阶段保护 |
| `nodes/_helpers.py` | 节点内部辅助：_resolve_model_for_call、_run_with_consistency |
| `nodes/borrow.py` | 借调 Agent 发言逻辑（跨角色借用专家） |
| `borrow_helpers.py` | 借调辅助：_let_borrowed_agents_speak、_moderator_assess_borrow |
| `evidence_helpers.py` | 证据辅助：_prefetch_evidence、_collect_evidence |
| `produce_helpers.py` | 产出辅助：_scan_artifacts、_emit_progress |
| `prompt_safety.py` | Prompt 安全防护（注入检测与隔离包装） |
| `system_prompt.py` | 系统提示词构建与分类结果解析 |

---

## 5. 质量门禁与自动回流

### 5.1 质量评估维度（_evaluate_quality）

produce 阶段完成后（且未标记终态时），Runner 调用多维度评分：

| 维度 | 权重 | 说明 |
|---|---|---|
| 部署成功 | 硬门槛 | 服务必须部署成功，失败直接不通过 |
| 测试通过 | 硬门槛 | 有测试必须全部通过，无测试扣分 |
| 架构完整性 | 25 分 | 分层是否完整（routers/schemas/services/dao/db/domain/config） |
| 代码规模匹配度 | 20 分 | 代码行数/文件数是否匹配复杂度等级（检测 demo/stub） |
| 功能真实性 | 15 分 | 检测是否为硬编码 mock/demo |
| 代码质量 | 15 分 | 语法检查、参数化查询、错误处理 |
| 前端完整性 | 10 分 | medium+ 复杂度必须有 React 前端 |
| 文档完整性 | 5 分 | README、环境变量、API 文档 |

### 5.2 自动迭代回流

```
produce 完成 → _evaluate_quality()
                │
                ├─ should_iterate=True && auto_iterate=True && iteration_count < max_iterations
                │   → 注入 quality-feedback 到 intervention_messages
                │   → state.stage = Stage.PRODUCE（重新执行 produce）
                │   → publish iteration.started
                │
                ├─ should_iterate=True && auto_iterate=False
                │   → publish quality.needs_review（等待人工确认）
                │
                └─ should_iterate=False
                    → 标记终态，会议结束
```

### 5.3 阶段级重试与断点续传

- **阶段内重试**：单阶段异常时按 `state.max_stage_retries`（默认）重试，重试前 `asyncio.sleep(2)`，发布 `stage.retry` 事件。
- **Checkpoint 机制**：每个阶段成功后记录 `{last_completed_stage, completed_at, elapsed_s, confidence}`，失败时记录 `{failed_stage, error, resumable=True}`，支持 resume 恢复。
- **全局异常兜底**：try/except 包裹主循环，未捕获异常标记 `status=FAILED` 并记录 `error_detail`，避免 RUNNING 僵死态。

---

## 6. 上下文管理

### 6.1 设计原则

1. **显式预算**：每次 LLM 调用前估算 token，不超限。
2. **优先级分层**：宪章 > 已锁定结论 > 证据 > 物料 > 旧消息摘要 > 近期发言。
3. **动态窗口**：根据 `budget.available_tokens` 计算窗口大小，替代硬编码 `[-8:]`。
4. **摘要压缩**：超预算时对旧消息调用 LLM 生成摘要保留关键信息，非直接丢弃。

### 6.2 ContextBudget

```python
@dataclass
class ContextBudget:
    max_tokens: int = 8000          # 模型上下文窗口
    reserved_tokens: int = 1500     # system/role/instruction 预留
    # available_tokens = max_tokens - reserved_tokens = 6500（供历史消息/物料）
```

### 6.3 ContextSlice 分层结构

| 字段 | 优先级 | 说明 |
|---|---|---|
| `charter` | 最高 | 会议宪章（议题、关键问题） |
| `locked_conclusions` | 高 | 已锁定结论（conclusion_chain） |
| `evidence` | 高 | 证据片段（quote + source） |
| `material_snippets` | 中 | 物料切片（每物料截断到 600 字） |
| `summarized_older_messages` | 中 | 旧消息 LLM 摘要（被压缩的消息关键信息） |
| `recent_messages` | 低 | 近期发言（每消息截断到 200 字） |

### 6.4 摘要压缩流程

```
_build_base_slice（宪章/结论/证据/物料）
    │
    ▼
_apply_dynamic_window（按预算计算可容纳的近期消息条数）
    │
    ├─ 预算充足 → 全部近期消息保留
    │
    └─ 预算不足 + llm_summarize 回调可用
        → _summarize_messages(older_messages, llm_summarize)
        → 生成 summarized_older_messages（≤500 tokens）
        → 摘要缓存（按消息 hash 命中不重复生成）
    │
    ▼
_trim_to_budget（最终裁剪兜底）
```

---

## 7. 任务图与 DAG 调度

### 7.1 核心抽象

```python
@dataclass
class Task:
    id: str                           # 唯一标识
    name: str                         # 人类可读名称
    dependencies: list[str] = []      # 依赖的任务 id（必须全部完成）
    execute: Callable | None = None   # 异步执行函数
    result: Any = None                # 执行结果
    status: str = "pending"           # pending/running/done/failed
```

### 7.2 DAG 执行模型

- **拓扑排序分层**：无依赖关系的任务自动同层并行。
- **同层并行**：`asyncio.gather` 并发执行同层所有任务。
- **依赖传递**：下游任务接收上游任务结果 dict 作为参数。

### 7.3 在阶段中的应用

`stage_planners.py` 将每个阶段展开为 `ExecutionPlan`（SubTask 列表 + 依赖关系），由 `conclave_core.Scheduler` 调度：

- **clarify/arbitrate/produce**：单 SubTask（与旧节点一次调用等价）。
- **intra_team**：按角色拆为多个并行 SubTask（`intra-{role}-{idx}`），角色间无依赖，自动并行。
- **evidence_check**：按 conflict 拆为并行 SubTask，每个冲突点独立核查。

---

## 8. 核心设计模式

### 8.1 ReactLoop（think-act-observe 自主循环）

```
┌──────────────────────────────────────────────┐
│  while iterations < max_iterations:          │
│    1. think:  LLM 基于当前状态决策工具调用    │
│    2. act:    执行工具（ToolRegistry 查找）   │
│    3. observe:记录工具结果到裁剪后的history   │
│    4. 卡死检测：连续相同工具+参数 → 终止      │
│    5. 目标锚定：每轮带原始任务+迭代序号       │
└──────────────────────────────────────────────┘
```

**关键特性**：
- `max_iterations` 是一等公民终态（非异常）。
- O(1) 上下文：每轮只带裁剪后的 tool_history，不带完整原始输出。
- 工具异常不终止循环，记为 error 后继续。
- 与 RefineLoop 的区别：ReactLoop 的 LLM **自主决策下一步**，RefineLoop 的 LLM 只**修正给定报错**。

### 8.2 RefineLoop（受控代码自修复）

```
初始代码 → run_fn 执行
    │
    ├─ 成功 → 返回结果
    │
    └─ 失败 → LLM 根据报错修正代码（只改出错部分，不重写）
              → run_fn 重执行
              → 重复检测：连续两轮相同代码 → 终止
              → max_rounds（默认5）硬上限兜底
```

**关键特性**：
- Prompt 约束："只修改导致报错的部分，不要重写整个文件"。
- 每轮上下文 O(1)：只带上一轮最终代码 + 报错，不带完整历史。
- 任务锚点：三句话摘要（任务是什么 + 已完成什么 + 当前问题）。

### 8.3 FastPath（Instant 快路径）

```
用户请求进入
    │
    ▼
classify_intent_async(query, override_mode)
    │  向 LLM 发送 Conclave 完整系统上下文（能力/模式/约束）
    │  LLM 基于语义理解自主决策（非关键词匹配）
    │
    ├─ instant/simple → run_instant()：单 Agent 即时回答，跳过六阶段
    ├─ plan           → flow_plan="plan"，进入六阶段配合 Planner（预留）
    └─ standard       → 完整六阶段多 Agent 辩论管线
```

**关键特性**：
- 模式标准化：`normalize_mode()` 兼容旧名称（fast/fast_path/quick → instant，deep_think/full → standard）。
- API 可通过 `override_mode` 显式指定，跳过 LLM 分类。
- Instant 模式在发布 stage.changed 事件之前分流，避免前端看到 clarify 阶段闪烁。

---

## 9. 动态路由与元认知控制

`nodes/routing.py` 中的 `decide_next_stage()` 实现元认知路由：

1. **阶段跳转白名单**：每个阶段只允许跳转到预定义的下一阶段集合（防止无效跳转）。
2. **循环上限**：intra_team≤3 次、cross_team≤2 次、evidence_check≤2 次、arbitrate≤2 次，超限强制推进。
3. **强制阶段保护**：根据 `debate_depth` 确保关键阶段至少执行一次：
   - `deep`：intra_team → cross_team → evidence_check → arbitrate 全部必须执行。
   - `standard`：intra_team 必须执行；有冲突时 evidence_check 必须执行；无冲突时 cross_team 后直接 arbitrate。
   - `light`：intra_team + arbitrate 必须执行。
4. **回退次数保护**：全局回退（从后阶段跳回前阶段）上限 5 次，超限强制推进到 produce。
5. **LLM 决策兜底**：元认知 Agent 调用失败时回退到固定顺序 `conclave_core.state.next_stage()`。

---

## 10. 扩展指南

### 10.1 新增一个阶段

1. **在 `conclave_core.state` 中注册阶段**：添加 Stage 枚举值、更新 STAGE_ORDER、更新 is_terminal/should_pause/next_stage 等函数。
2. **创建阶段 Runner**：在 `stage_runners.py` 中添加 `run_xxx(state, result, confidence) -> MeetingState`，负责将 LLM 结果写回 state、锁定结论、推进 stage。
3. **创建阶段 Planner**：在 `stage_planners.py` 中添加 `plan_xxx(state, baseline) -> ExecutionPlan`，定义 SubTask DAG。
4. **创建阶段 Reducer**：在 `stage_reducers.py` 中添加 `reduce_xxx(state, stage, results) -> MeetingState`，从 Scheduler 结果中提取 payload 并委托给 runner。
5. **（可选）创建节点兼容层**：在 `nodes/xxx.py` 中添加 `xxx_node(state) -> MeetingState` 作为 legacy wrapper（调用 build_xxx_prompt + execute_think + run_xxx），在 `nodes/__init__.py` 中注册到 NODES 字典。
6. **更新路由白名单**：在 `nodes/routing.py` 的 `_VALID_NEXT_STAGES` 中添加入边和出边。
7. **更新 Planner 映射**：在 `stage_planners.py` 的 `get_stage_planner()` 中注册 planner 函数。
8. **更新 Reducer 映射**：在 `stage_reducers.py` 的 `reduce_stage_results()` 中注册 reducer 函数。

### 10.2 新增一个节点（legacy 兼容方式）

```python
# nodes/my_stage.py
from app.orchestrator.stage_runners import run_my_stage

async def my_stage_node(state: MeetingState) -> MeetingState:
    """MyStage 节点：xxx"""
    set_current_trace(state.llm_trace)

    async def call_fn(anchor: str) -> dict:
        req = build_my_stage_prompt(...)
        req.model = _resolve_model_for_call(state, role, "my_stage")
        resp = await execute_think(req)
        return resp.result

    result, confidence = await _run_with_consistency(state, "my_stage", call_fn)
    return await run_my_stage(state, result, confidence)
```

然后在 `nodes/__init__.py` 中导入并加入 `NODES` 字典。

### 10.3 注册一个 ReactLoop 工具

```python
from app.orchestrator.react_loop import ToolRegistry

registry = ToolRegistry()
registry.register(
    name="web_search",
    description="搜索网络获取证据",
    fn=my_search_fn,          # async (params: dict) -> Any
    parameters={"query": "str", "top_k": "int"},
)
```

### 10.4 使用 RefineLoop 修复代码

```python
from app.orchestrator.refine_loop import refine_python_code

result = await refine_python_code(
    initial_code=code,
    task_summary="数据分析任务：xxx",
    run_fn=my_runner,          # async (code) -> {"exit_code", "stdout", "stderr"}
    max_rounds=5,
    meeting_id=state.meeting_id,
)
# result["code"] 为最终修复后的代码
# result["success"] 表示是否在 max_rounds 内修复成功
```

### 10.5 扩展 ContextManager 分层

在 `ContextSlice` 中添加新字段，在 `_build_base_slice()` 中填充，在 `to_prompt_text()` 中格式化输出。注意遵守优先级分层原则，新层的优先级应插入到现有层级之间的正确位置。

---

## 11. 内存管理

- **状态 TTL**：已完成会议状态在内存中保留 `CONCLAVE_STATE_TTL` 秒（默认 1800 秒 = 30 分钟），到期后 `_schedule_cleanup` 自动清理。
- **LRU 淘汰**：`_states` 字典超过 `CONCLAVE_MAX_CACHED_STATES`（默认 100）时，按最后访问时间淘汰最旧的非运行中会议。
- **PAUSED 状态不清理**：用户可能随时 resume，不参与 TTL/LRU 淘汰。

---

## 12. 可观测性

- **LogBus 旁路日志**：Runner session 开始/结束、阶段完成、动态路由决策、回退检测、质量门禁结果均通过 `log_bus` 发布结构化日志。
- **事件总线**：所有阶段切换、Agent 发言、证据挂载、产物生成、介入回复、质量评审、迭代开始等均通过 `bus.publish(make_event(...))` 发布 WebSocket 事件到前端。
- **Tracing**：`set_current_trace(state.llm_trace)` 将所有 LLM 调用关联到会议 trace。
- **Runner Session ID**：每次 `run()` 分配唯一 `runner_session_id`，关联该次运行期间的所有因果链日志。
