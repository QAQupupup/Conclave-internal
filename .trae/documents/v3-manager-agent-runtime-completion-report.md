# Conclave V3 Manager-Agent-Runtime 重构完成报告

## 1. 本次完成内容

### 1.1 架构层

- `Runner` 已统一通过 `MeetingManager` 执行阶段，不再保留 `compatibility_mode` 分支。
- `MeetingManager.run_stage` 走通 `Planner -> Scheduler -> AgentRuntime -> Reducer -> StageRunner` 链路。
- `Scheduler`  DAG 调度与 `AgentRuntime` 统一执行接口已接入真实阶段运行。

### 1.2 阶段业务逻辑下沉

| 阶段 | 状态写入位置 | 说明 |
|---|---|---|
| clarify | `stage_runners.run_clarify` | 议题澄清、charter 生成、flow_plan 设置 |
| intra_team | `stage_runners.run_intra_team` | 聚合多角色 claims、生成 messages |
| cross_team | `stage_runners.run_cross_team` | 冲突识别/共识汇总、证据预取 |
| evidence_check | `stage_runners.run_evidence_check` | 聚合多冲突 evidence_assessments |
| arbitrate | `stage_runners.run_arbitrate` | 决策记录、action_brief、结论锁定 |
| produce | `stage_runners.run_produce` | 收尾：附件扫描、结论锁定、事件发布、漂移检查、终态设置 |

`nodes/*.py` 当前作为薄包装或保留复杂产物构建逻辑：

- `clarify.py` / `arbitrate.py` / `cross_team.py` / `intra_team.py` / `evidence_check.py` 已瘦身为 `compute` + `stage_runners` 调用。
- `produce.py` 仍保留 artifact 构建、代码审查、沙箱执行、Docker 部署等复杂逻辑；仅将收尾段替换为 `run_produce(state, confidence)`。

### 1.3 关键文件变更

- `backend/app/orchestrator/stage_runners.py`：新增/完善六阶段 runner；修复缺失的 `get_logger` / `MeetingStatus` 导入。
- `backend/app/orchestrator/nodes/produce.py`：删除 80 行收尾逻辑，改为调用 `run_produce`；清理不再使用的 `json`、`MeetingStatus`、`_record_drift` 导入。
- `backend/app/orchestrator/manager.py`：移除 `compatibility_mode`，统一走调度路径。
- `backend/app/orchestrator/runner.py`：移除 `compatibility_mode` 相关代码，始终注入 `MeetingManager`。
- `backend/tests/test_regression_historical.py`：新增历史 Wiki 议题回归与冲突触发 evidence_check 回归。
- `backend/tests/test_produce_stage.py`：新增 produce 内容完整性降级、附件扫描、fallback 事件测试。

## 2. 测试验证

执行命令：

```bash
cd backend
python -m pytest tests -q
```

结果：

```
189 passed, 2 skipped, 171 warnings
```

新增测试 3 个（`test_produce_stage.py`），回归测试 3 个（`test_regression_historical.py`），全部通过。

## 3. 已知未完结项

- `produce.py` 中 artifact 构建、代码审查、沙箱执行、Docker 部署等复杂逻辑尚未完全接入 `AgentRuntime` 产物回写，当前仍由 `produce_node` 直接调用 compute 与 sandbox。
- `ContextManager` 的分层裁剪能力已接入 `AgentContext.working_memory`，但尚未对长会议做系统性压测。
- `TaskBaseline` 已支持 software_dev / stock_analysis，但领域扩展与质量门仍需后续迭代。

## 4. 提交建议

本次变更涉及文件：

- `backend/app/orchestrator/stage_runners.py`
- `backend/app/orchestrator/nodes/produce.py`
- `backend/app/orchestrator/manager.py`
- `backend/app/orchestrator/runner.py`
- `backend/tests/test_regression_historical.py`
- `backend/tests/test_produce_stage.py`
- `README.md`
- `.trae/documents/v3-manager-agent-runtime-completion-report.md`

建议提交信息：

```text
feat(orchestrator): complete Phase 3 produce finalization migration

- Move produce finalization (lock, event, drift, DONE) to stage_runners.run_produce
- Wire produce.py tail to run_produce
- Add produce stage unit/regression tests
- Update README and archive completion report
```
