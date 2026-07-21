# Conclave V3 Manager-Agent-Runtime 重构实施计划

## 1. Summary

本计划目标是将 `Runner` 从“阶段循环 + 节点直接调用”的混合体，改造成**纯阶段状态机**；由新引入的 `MeetingManager` 接管每个阶段内的子任务拆分、Agent 调度、上下文治理与产物回写。最终解决三个核心问题：

- **上下文溢出**：所有 Agent 调用统一走 `ContextManager`，按预算分层切片，而不是把整段历史 prompt 塞给 LLM。
- **Agent 抽象不统一**：所有角色（主持人、业务 Agent、借调 Agent）统一使用 `AgentRuntime` 执行，差异通过 `TaskBaseline` 与 `AgentConfig` 表达。
- **组件交互混乱**：`Manager` 作为 Runner、Scheduler、AgentRuntime、ContextManager、EventBus、Storage 之间的统一协调层，定义显式契约。

实施原则：**API 不变、测试通过、小步迁移，终态不保留兼容层**。

- 当前 `nodes/` 已经是模块化包，保留 `__init__.py` 兼容符号作为过渡。
- 第一阶段：Runner 通过 Manager 调用旧节点逻辑，保证所有现有测试立即通过。
- 第二阶段：把节点内的业务逻辑逐步下沉到 `stage_planners.py` / `stage_reducers.py` / `stage_common.py`。
- 第三阶段：节点函数瘦身为对 `Manager.run_stage` 的薄包装，或直接移除；`nodes/__init__.py` 仅保留导出别名。
- 终态：`Runner -> Manager -> Scheduler -> AgentRuntime -> ContextManager`，旧节点实现全部下线。

---

## 2. Current State

### 2.1 关键文件现状

| 文件 | 状态 | 说明 |
|---|---|---|
| `backend/app/orchestrator/runner.py` | 已存在，需重构 | 仍按 `NODES[stage]` 直接调用节点，包含干预处理、借调发言、动态路由、持久化等大量职责。 |
| `backend/app/orchestrator/nodes/` | 已模块化 | `__init__.py` 导出 `NODES`、`clarify_node` 等兼容符号；各阶段实现分散在 `clarify.py`、`intra_team.py` 等文件中。 |
| `backend/app/orchestrator/manager.py` | 骨架已存在 | 仅有 `run_stage` 入口和简单 `stage_plan`，未接入真实阶段业务逻辑。 |
| `backend/app/orchestrator/scheduler.py` | 骨架已存在 | 已实现 `SubTask` DAG 分层与递归调度，但未与真实 Agent 执行打通。 |
| `backend/app/orchestrator/context_manager.py` | 骨架已存在 | 已实现 `ContextBudget` / `ContextSlice` / 裁剪逻辑，但尚未接入 Agent 调用路径。 |
| `backend/app/agents/agent_runtime.py` | 骨架已存在 | 已实现 `AgentRuntime.execute`，但尚未被 Manager 调用。 |
| `backend/app/agents/task_baseline.py` | 骨架已存在 | 已定义 `TaskBaseline` 与 software_dev / stock_analysis 两条基线。 |

### 2.2 Runner 当前职责过重

`Runner.run()` 当前职责：

1. 设置追踪上下文、模型快照。
2. Fast Path 分流。
3. `while not is_terminal(state)` 循环：
   - 检查 pause。
   - `node = NODES[current_stage]` 直接调用节点。
   - 节点返回后处理 intervention、借调 agent 发言。
   - 持久化。
   - 动态路由（`decide_next_stage`）或固定 `next_stage` 推进。
   - 发布 `stage.changed`。
4. 异常兜底、终态清理。

节点内部又硬编码了角色并行（`asyncio.gather`）、prompt 构造、事件发布、状态字段写入。这是导致“组件交互混乱”的根因。

### 2.3 MeetingState 结构

`MeetingState`（`backend/app/models.py`）是当前会议聚合根，包含：

- 基础：`meeting_id`, `topic`, `stage`, `status`, `created_at`
- 团队：`team_config`, `role_configs`
- 议题澄清：`clarified_topic`, `key_questions`, `charter`
- 讨论产物：`messages`, `claims`, `conflicts`, `evidence_set`, `decision_record`, `artifact`
- 流程控制：`flow_plan`, `debate_depth`, `dynamic_routing`, `confidence_flags`
- 治理：`conclusion_chain`, `drift_log`, `llm_trace`, `borrowed_agents`, `user_rejections`

重构期间**不修改** `MeetingState` 的字段定义，所有迁移通过读取/写入这些字段完成，保证快照与 API 兼容。

---

## 3. Proposed Changes

### 3.1 把 Runner 改造成纯阶段状态机

**文件**：`backend/app/orchestrator/runner.py`

**What**：删除 Runner 对节点实现的直接依赖，只保留：

- 会议生命周期上下文（trace id、runner_session_id）。
- Fast Path 分流。
- 阶段循环：`while not is_terminal`。
- pause / abort 检查。
- 调用 `Manager.run_stage(state, current_stage.value)` 执行阶段。
- 阶段后处理：intervention、借调发言。
- 阶段推进：`next_stage` 固定推进 或 `decide_next_stage` 动态路由。
- 事件发布：`stage.changed`、`run.started` 等。
- 持久化 `_persist`、状态注册表。

**Why**：单一职责。Runner 只关心“到哪个阶段了、是否继续、怎么推进”，不关心阶段内怎么调度 Agent。

**How**：

1. 在 `Runner.__init__` 中注入 `MeetingManager`（默认新建），保存为 `self.manager`。
2. 循环体中：
   ```python
   current_stage = state.stage
   state = await self.manager.run_stage(state, current_stage.value)
   state = await _process_interventions(state)
   await _let_borrowed_agents_speak(state, current_stage)
   self._persist(state)
   ```
3. 移除 `from app.orchestrator.nodes import NODES` 的直接调用；改为 `from app.orchestrator.manager import MeetingManager`。
4. 保留 `dynamic_routing` 分支：在 Manager 执行完阶段后，Runner 根据 `current_stage` 调用 `decide_next_stage`，再做回归检测与上限保护。

### 3.2 扩展 MeetingManager 为真正的调度中枢

**文件**：`backend/app/orchestrator/manager.py`

**What**：实现 `run_stage` 的完整调度逻辑，把每个阶段展开为 `SubTask` DAG，通过 `Scheduler` 执行，再把子任务结果归约回 `MeetingState`。

**How**：

1. 新增阶段规划器注册表：
   ```python
   _STAGE_PLANNERS: dict[str, Callable[[MeetingState, TaskBaseline], ExecutionPlan]]
   ```
2. `run_stage(state, stage)` 流程：
   - 选择 `baseline = self.select_baseline(state.topic, state.domain_hint)`。
   - 根据 `stage` 调用对应 planner 生成 `ExecutionPlan`。
   - `scheduler = Scheduler(self._execute_subtask, max_recursion_depth=...)`
   - `results = await scheduler.run_plan(plan, shared_state={"state": state, "baseline": baseline})`
   - 调用 `_reduce_stage_results(state, stage, results)` 把结果写回 `MeetingState`。
3. `_execute_subtask(task, context)` 流程：
   - 从 `context["shared_state"]` 取 `state` 与 `baseline`。
   - `ctx_slice = self.context_manager.prepare(state, task.stage, task.role)`
   - `agent = build_agent_from_baseline(...)`
   - `agent_ctx = AgentContext(..., working_memory={"context": ctx_slice.to_prompt_text()})`
   - `result = await agent.execute(...)`
   - 记录 trace / latency / token。

### 3.3 新增阶段规划器模块

**文件**：`backend/app/orchestrator/stage_planners.py`（新增）

**What**：为六阶段分别定义 `SubTask` DAG 构建函数。

| 阶段 | Plan 结构 |
|---|---|
| `clarify` | 单任务 `moderator`，负责议题澄清、生成 charter。 |
| `intra_team` | 每个 `team_config` 角色一个 `SubTask`，默认无依赖（可并行）。 |
| `cross_team` | 单任务 `moderator`，基于 claims 生成 conflicts。 |
| `evidence_check` | 每个 conflict 一个 `SubTask`（并行）。 |
| `arbitrate` | 单任务 `moderator`，基于 evidence_set 做裁决。 |
| `produce` | 单任务 `moderator` 生成 artifact；若需子模块，返回 `sub_tasks` 让 Scheduler 递归执行。 |

### 3.4 新增阶段结果归约器

**文件**：`backend/app/orchestrator/stage_reducers.py`（新增）

**What**：把 `Scheduler` 返回的 `{task_id: AgentResult}` 写回 `MeetingState`，并触发事件。

**How**：

- `_reduce_clarify`：设置 `clarified_topic`、`key_questions`、`team_config`、`charter`、`flow_plan`，发布 moderator 发言。
- `_reduce_intra_team`：收集每个角色的 `claims`，生成 `messages`。
- `_reduce_cross_team`：设置 `conflicts`。
- `_reduce_evidence_check`：设置 `evidence_set`。
- `_reduce_arbitrate`：设置 `decision_record`，生成 action_brief。
- `_reduce_produce`：设置 `artifact`，处理 deployable_service / code_analysis / tested_system。

### 3.5 迁移并复用旧节点业务函数

**文件**：`backend/app/orchestrator/stage_common.py`（新增）

**What**：从 `nodes/_helpers.py`、`nodes/borrow.py`、`nodes/routing.py` 提取与调度无关的辅助函数。

**How**：迁移以下函数（保持签名尽量不变）：

- `_match_role`, `_ROLE_KEYWORDS`
- `_record_drift`, `_record_message`, `_emit_agent_spoke`
- `_format_claims_as_text`, `_format_arbitrate_as_text`
- `_let_borrowed_agents_speak`
- `_moderator_assess_borrow`, `_BORROWABLE_ROLES`, `AUTO_BORROW_THRESHOLD`
- `_collect_evidence`, `_prefetch_evidence`
- `_compress_decisions_to_brief`, `_synthesize_evidence_for_produce`
- `decide_next_stage`, `_VALID_NEXT_STAGES`, `_MAX_LOOP_COUNT`

### 3.6 接入 ContextManager 到 AgentRuntime

**文件**：`backend/app/agents/agent_runtime.py` 与 `backend/app/orchestrator/context_manager.py`

**What**：让 AgentRuntime 的 prompt 构建显式消费 `ContextSlice`。

**How**：

1. `AgentContext.working_memory` 接收 `ContextSlice.to_prompt_text()` 结果。
2. `AgentRuntime._build_prompt` 把 `working_memory["context"]` 作为“相关上下文”段落。
3. `ContextManager.prepare` 逐步增强：charter、conclusion_chain、evidence、messages、doc_summaries、reference_context。

### 3.7 nodes/ 兼容层（过渡方案）

**文件**：`backend/app/orchestrator/nodes/__init__.py`

**What**：保留现有导出符号不变，但明确这是**临时过渡**。

**Why**：
- 现有测试与 runner.py 直接 import `clarify_node`、`NODES` 等符号。
- 一次性全部迁移风险过高，需要先保证测试通过再瘦身。

**终态**：
- 当 `stage_planners.py` / `stage_reducers.py` 完成并经过全量测试验证后，`nodes/*.py` 中的业务逻辑删除。
- `nodes/__init__.py` 继续导出同名符号，但内部直接委托给 `MeetingManager.run_stage`，或仅作为别名存在。
- 例如：
  ```python
  async def clarify_node(state: MeetingState) -> MeetingState:
      return await _manager_for_state(state).run_stage(state, "clarify")
  ```

**当前阶段**：先不动 `nodes/*.py` 内部实现，只改造 `runner.py` 让它通过 `Manager` 调用节点。

---

## 4. Assumptions

1. **API 兼容优先**：HTTP 端点、`MeetingState` 模型、测试 import 路径均保持不变。
2. **StubLLM 仍是默认测试路径**：真实 LLM 仅通过 `CONCLAVE_TEST_REAL_LLM=1` 触发。
3. **单进程事件循环**：当前代码依赖 asyncio 单线程事件循环；本次重构不引入多进程/分布式。
4. **SQLite 继续用于测试**：不强制迁移到 PostgreSQL，但 Manager 的 `persist_state` 接口预留 Repository 层接入点。
5. **Pydantic v2 模型不变**：`MeetingState` 字段与序列化行为保持现状。
6. **阶段顺序保持六阶段**：`clarify -> intra_team -> cross_team -> evidence_check -> arbitrate -> produce`。

---

## 5. Verification

### 5.1 测试分层策略

| 层级 | 目标 | 手段 |
|---|---|---|
| **单元测试** | Manager / Scheduler / ContextManager / AgentRuntime 独立正确 | 继续完善 `test_manager.py`、`test_scheduler.py`、`test_context_manager.py` |
| **集成测试** | Runner + Manager + 六阶段完整跑通 | 运行 `test_core_flow.py`、`test_smoke.py`、`test_e2e.py`、`test_event_replay.py`、`test_determinism.py` |
| **回归测试** | 基于历史会议数据验证输出结构 | 新增 `test_regression_historical.py` |

### 5.2 基于历史数据的端到端回归测试

**文件**：`backend/tests/test_regression_historical.py`（新增）

**How**：

1. **录制历史 fixture**：从 `conclave.db` 导出若干 `MeetingState` 快照，保存到 `backend/tests/fixtures/historical_states.json`。
2. **Stub Compute 回放**：按 `req.stage` 返回预定义结果。
3. **断言指标**：
   - 六阶段都产生 `confidence_flags`。
   - `conclusion_chain` 锁定 6 条。
   - `artifact` 包含 `prd` 与 `openapi`。
   - 事件历史包含 `stage.changed`、`agent.spoke`、`evidence.attached`、`artifact.generated`。
4. **避免真实 LLM**：monkeypatch `app.agents.compute._compute`。

### 5.3 验证清单

- [ ] `pytest backend/tests/test_manager.py` 通过。
- [ ] `pytest backend/tests/test_scheduler.py` 通过。
- [ ] `pytest backend/tests/test_context_manager.py` 通过。
- [ ] `pytest backend/tests/test_e2e_refactor.py` 通过。
- [ ] `pytest backend/tests/test_core_flow.py` 通过。
- [ ] `pytest backend/tests/test_smoke.py` 通过。
- [ ] `pytest backend/tests/test_e2e.py` 通过。
- [ ] `pytest backend/tests/test_event_replay.py` 通过。
- [ ] `pytest backend/tests/test_determinism.py` 通过。
- [ ] 新增 `test_regression_historical.py` 通过。

---

## 6. 推荐实施顺序

### 第一阶段：兼容过渡（保证测试不中断）
1. **重构 `runner.py`**，改为调用 `Manager.run_stage`。
2. **扩展 `manager.py`**，在 `run_stage` 中通过兼容模式直接调用旧节点函数（`clarify_node` 等）。
3. **全量运行测试套件**，确保现有测试全部通过。

### 第二阶段：逻辑下沉（逐步替换节点实现）
4. **提取 `stage_common.py`**，把 `nodes/_helpers.py`、`borrow.py`、`routing.py` 中的业务函数迁移到独立模块。
5. **实现 `stage_planners.py` 与 `stage_reducers.py`**，把六阶段逻辑从节点函数中解耦。
6. **扩展 `manager.py`**，接入 Planner/Reducer/Scheduler/AgentRuntime/ContextManager。

### 第三阶段：终态收敛（下线兼容层）
7. **将 `nodes/*.py` 瘦身为对 `Manager.run_stage` 的薄包装**。
8. **编写 `test_regression_historical.py`**，基于历史数据验证重构后行为一致。
9. **全量运行测试套件**，确认终态无回归后删除旧节点实现。
