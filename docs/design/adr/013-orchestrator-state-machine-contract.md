# ADR-013: 编排器状态机契约

## 状态

Accepted — 2026-07-28

## 背景

### 问题历史

Conclave 编排器（`Runner.run()`）使用 `while not is_terminal(state)` 主循环驱动六阶段管线。在迭代开发中多次出现状态机时序 bug（§4.24），根因是**终态设置权责不清**：

1. **阶段 runner 越权设置终态**：`run_produce()` 在 produce 阶段结束时直接设置 `state.status = MeetingStatus.DONE`，导致 `is_terminal(state)` 返回 True，Runner 主循环在质量门禁评估前退出。质量门禁代码在 `is_terminal()` 检查之后，永远不会被执行。

2. **auto_iterate=False 死循环**：质量未达标且用户未开启自动迭代时，`should_iterate=True` 但不设置终态，导致 while 循环无限重跑 produce。

3. **测试断言与实现不一致**：直接调用 `produce_node()` 的测试断言 `status == DONE`，但修复后阶段 runner 不再设置 DONE，测试需要同步更新为 `status == RUNNING`。

### 代码核验

**状态枚举**（`app/domain/enums.py`）：

```
Stage: CLARIFY → INTRA_TEAM → CROSS_TEAM → EVIDENCE_CHECK → ARBITRATE → PRODUCE
MeetingStatus: RUNNING | PAUSED | ABORTED | DONE | FAILED
```

**终态判定**（`conclave_core/state.py:445-447`）：

```python
def is_terminal(state: MeetingState) -> bool:
    return state.status in (MeetingStatus.DONE, MeetingStatus.ABORTED, MeetingStatus.FAILED)
```

**阶段 runner 现状**（`stage_runners.py`）：6 个 `state.stage` 赋值，0 个 `state.status` 赋值 — 符合契约。

**Runner 主循环**（`runner.py:311-538`）：

```
while not is_terminal(state):
    1. 执行当前阶段节点
    2. 持久化状态
    3. 若 PRODUCE 完成 → 质量门禁评估 → 决定迭代/终态
    4. 终态检查 → break
    5. 动态路由 → 设置下一 stage
```

## 决策

### 1. 终态设置权责划分

| 组件 | 可设置 | 禁止设置 |
|---|---|---|
| `Runner.run()` | `DONE`, `FAILED` | — |
| 阶段 runner（`run_clarify` 等） | — | `DONE`, `FAILED`, `ABORTED` |
| 节点（`clarify_node` 等） | — | `DONE`, `FAILED`, `ABORTED` |
| 控场信号（`pause`/`abort`） | `PAUSED`, `ABORTED` | `DONE`, `FAILED` |

**规则**：阶段 runner 和节点只能修改 `state.stage`（标识下一目标阶段），不能修改 `state.status`。终态（`DONE`/`FAILED`）由 Runner 主循环统一设置。

### 2. 质量门禁终态转换规则

Runner 在 `current_stage == Stage.PRODUCE` 后执行质量门禁评估（`_evaluate_quality`），根据评估结果设置终态：

| 条件 | `state.status` | `state.stage` | 行为 |
|---|---|---|---|
| 质量达标 (`should_iterate=False`) | `DONE` | 保持 `PRODUCE` | 正常结束 |
| 迭代上限 (`iteration_count >= max_iterations`) | `DONE` | 保持 `PRODUCE` | 记录未达标原因 |
| 自动迭代 (`should_iterate=True` + `auto_iterate=True` + 未达上限) | 保持 `RUNNING` | 回退 `PRODUCE` | 注入反馈，重跑 |
| 需人工确认 (`should_iterate=True` + `auto_iterate=False`) | `DONE` | 保持 `PRODUCE` | 发 `quality.needs_review` 事件 |
| 节点异常 | `FAILED` | 当前 stage | 记录异常信息 |

**关键约束**：`auto_iterate=False` 时必须设置 `DONE` 退出循环，否则 `should_iterate=True` 会导致 while 无限重跑。

### 3. 动态路由契约

动态路由（元认知 Agent `decide_next_stage`）在**非 PRODUCE 阶段**执行：

- 临时将 `state.stage` 设回 `current_stage`（因为节点可能已预设下一阶段）
- 调用 `decide_next_stage(state)` 获取元认知决策
- 若元认知决策与节点预设不同，采纳元认知决策
- 若元认知异常，回退到固定管线推进（`next_stage(current_stage)`）

PRODUCE 阶段不执行动态路由 — 由质量门禁接管。

### 4. 阶段推进规则

阶段 runner 通过 `state.stage = nxt or Stage.PRODUCE` 设置下一阶段。`nxt` 来自 `next_stage(current_stage, skip)`，根据议题复杂度裁剪：

- **simple**：跳过 `cross_team` + `evidence_check`，保留 `clarify → intra_team → arbitrate → produce`
- **standard**：六阶段全走
- **complex**：六阶段全走 + 可借调额外角色

Runner 主循环读取 `state.stage` 执行对应节点，不自行决定阶段跳转。

### 5. 测试断言契约

直接调用节点/阶段 runner 的测试：
- 断言 `state.status == MeetingStatus.RUNNING`（非 DONE）
- 断言 `state.stage` 为预期的下一阶段

通过 `Runner.run()` 完整运行的测试：
- 断言 `state.status == MeetingStatus.DONE`
- 断言 `state.stage == Stage.PRODUCE`

## 迁移

已完成的迁移（本次 ADR 落地时）：
1. `stage_runners.py` 中所有 `state.status = MeetingStatus.DONE` 已移除
2. `runner.py` 新增质量门禁后的终态设置逻辑
3. `auto_iterate=False` 分支新增 `state.status = MeetingStatus.DONE`
4. 相关测试断言已更新

## 验证方式

```bash
# 1. 确认阶段 runner 不设置终态
grep -n "MeetingStatus\.\(DONE\|FAILED\|ABORTED\)" backend/app/orchestrator/stage_runners.py
# 预期：0 匹配

# 2. 确认 Runner 主循环设置终态
grep -n "state\.status = MeetingStatus\.\(DONE\|FAILED\)" backend/app/orchestrator/runner.py
# 预期：3+ 匹配（质量达标/迭代上限/需人工确认/异常）

# 3. 确认测试断言一致
grep -n "status.*DONE\|status.*RUNNING" backend/tests/test_smoke.py backend/tests/test_determinism.py
# 预期：通过 Runner.run 的测试断言 DONE，直接调节点的测试断言 RUNNING
```

## 参考

- AGENTS.md §4.24（质量门禁终态设置时序）
- AGENTS.md §4.21（cross_team 门禁 claim_refs 不信任 LLM）
- AGENTS.md §4.22（plan_intra_team 角色名规范化）
- `backend/app/orchestrator/runner.py:311-538`（主循环实现）
- `backend/app/orchestrator/stage_runners.py`（阶段 runner 实现）
- `backend/conclave_core/state.py:445-452`（is_terminal / should_pause）
- `backend/app/domain/enums.py:41-59`（Stage / MeetingStatus 枚举）
- ADR-010（论点提纯架构与证据诚实性）
