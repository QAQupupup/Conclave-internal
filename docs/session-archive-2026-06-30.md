# 会话归档 2026-06-30

## 概述

完成三大改进：WebSocket 断线重连、RAG chunk 邻居链、议题路由。这三项分别解决了事件回放的"最后一公里"、证据检索的上下文缺失、以及简单任务浪费 token 的问题。

## 完成的工作

### 1. 前端 WebSocket 断线重连（commit `02603ff`）

**问题**：`lastSeq` 记录了但没用于重连，断线后全量 snapshot 覆盖已有状态。

**修复**：
- `lastSeqRef` 用 ref 追踪最新值，避免闭包陈旧
- `buildWsUrl` 支持 `from_seq` 参数，重连时携带 `?from_seq=<lastSeq>`
- 后端已有 `from_seq` 参数支持，只推增量事件
- 指数退避自动重连（1s → 2s → 4s → ... → 30s 上限）
- 配合之前的事件 SQLite 持久化 + seq 自增，端到端回放闭环完成

### 2. RAG chunk 邻居链（commit `02603ff`）

**问题**：`expand_context` 只能按字符范围展开，无法完整保留相邻标题段落。

**修复**：
- `Chunk` 新增 `prev_id`/`next_id` 字段
- `chunk_markdown` 切块时自动串联邻居链
- `InMemoryVectorStore.get_neighbor_context()` 按链展开上下文
- `retrieve_for_conflict` 默认启用 1 级邻居展开
- 证据检索时 LLM 能看到证据所在段落的完整上下文

### 3. 议题路由（commit `02603ff`）

**问题**：所有议题都跑完整六阶段，简单任务浪费 token 和时间。

**修复**：
- `ClarifyResult` 新增 `complexity` 字段（simple/standard/full）
- `MeetingState` 新增 `flow_plan` 字段
- `state.py` 的 `next_stage()` 按 flow_plan 跳过阶段
- 各 node 用 `_next_stage()` 替代硬编码阶段跳转
- `simple` 模式：跳过 cross_team + evidence_check + arbitrate
- `standard` 模式：无冲突时跳过 evidence_check
- `full` 模式：完整六阶段（默认）
- clarify 后发 `flow_plan.set` 事件通知前端
- `MODERATOR_CLARIFY` prompt 新增复杂度评估指令

## Commit 历史

| Commit | 内容 |
|---|---|
| `02603ff` | feat: 三大改进——WS断线重连+RAG邻居链+议题路由 |
| `3ca3615` | docs: 归档 2026-06-29 第四次 |
| `f9720f1` | fix(reliability): 可靠性闭环 |
| `2b89176` | fix(security): 安全闭环 |

## 测试验证

56 个回归测试全部通过。
