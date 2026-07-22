# ADR-009: MeetingState Sections 迁移策略

## 状态

Accepted — 2026-07-22

## 背景

`MeetingState` 当前有约 56 个平铺字段，所有 orchestrator 节点直接通过 `state.xxx` 访问。
这导致：
1. 字段职责不清晰（看不出哪些字段属于同一逻辑分组）
2. 序列化输出是扁平的 50+ 键 JSON，前端难以增量订阅
3. 新增字段时不知道该放在哪个逻辑区域

`sections` property 已实现（5 个分组：core/debate/borrow/iteration/observability），
`snapshot_sections()` 方法已添加，但 orchestrator 节点零使用。

## 决策

### 迁移原则

1. **只迁移读取路径**：sections 返回视图拷贝（model_copy），不支持写回。
   写入仍走平铺字段（`state.xxx = value`），仅读取迁移到 `state.sections["xxx"].field`。

2. **向后兼容**：平铺字段不删除。sections 和平铺字段并存，直到所有读取路径迁移完成。

3. **分阶段迁移**：每个阶段独立可回退，不一次性全量迁移。

### 迁移顺序

1. **Phase 1 — 只读工具层**（context_manager）：纯读取场景，无写入，风险最低
2. **Phase 2 — 只读节点**（routing、clarify 的读取部分）：读取多写入少
3. **Phase 3 — 读写节点**（intra_team、cross_team 等）：仅迁移读取部分，写入保持平铺
4. **Phase 4 — 移除平铺冗余**（未来迭代）：需 sections 写回支持就绪后

### 不在此 ADR 范围

- sections 写回支持（需要 `@sections.setter` 或 `update_from_sections()` 方法）
- 移除平铺字段（需要确认所有读写路径都已迁移）
- 前端 WS 协议变更（snapshot_sections 已在审计导出中提供，WS 增量推送是独立特性）

## 影响

- orchestrator 节点代码从 `state.charter` 变为 `state.sections["observability"].charter`
- 读取路径变长，但类型更清晰（Pydantic Section model 有字段约束）
- 不影响运行时行为（sections 视图的字段值与平铺字段一致）
