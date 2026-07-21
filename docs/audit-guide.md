# Conclave 审计与重跑指南

本文档说明如何在代码生成失败或需要换模型重跑前，完整记录并回溯一次会议的全链路数据。

## 核心思路

一次失败的重跑不应只依赖前端截图。Conclave 已在后端持久化以下数据：

- **LLM trace**：每次调用的 prompt、原始响应、解析结果、验证状态、token、延迟
- **事件总线**：会议运行期间的所有领域事件（stage 变化、agent 发言、降级事件）
- **成本记录**：每条成本写入 `cost_records` 表
- **状态快照**：`MeetingState` 中的 confidence_flags、结论链、证据集等

通过 `/meetings/{meeting_id}/audit` 端点可一次性导出以上内容，再通过脚本生成离线 HTML 报告。

## 快速使用

### 1. 获取会议 ID

方式 A：前端 URL 中截取，例如 `/meetings/abc-123` 则 ID 为 `abc-123`。

方式 B：调用后端列出会议：

```bash
curl http://localhost:8000/meetings
```

### 2. 生成审计报告

```bash
# 默认后端在 localhost:8000，输出到 docs/audits
python scripts/generate_audit_report.py <meeting_id>

# 自定义后端地址或输出目录
python scripts/generate_audit_report.py <meeting_id> \
  --api http://localhost:8000 \
  --out docs/audits
```

脚本会输出类似：

```text
[audit] 获取会议 <meeting_id> 的审计数据...
[audit] 报告已生成: C:\Users\Huawei\Documents\Conclave\docs\audits\conclave-audit-20260712-083000-<meeting_id>\report.html
[audit] 降级事件数: 1
[audit] LLM 调用数: 12
[audit] 总成本: $0.004320
```

打开 `report.html` 即可查看完整链路。

### 3. 直接调用审计端点

如果不想生成 HTML，可直接获取 JSON：

```bash
curl http://localhost:8000/meetings/<meeting_id>/audit | python -m json.tool
```

返回结构：

```json
{
  "meeting_id": "...",
  "generated_at": "...",
  "meeting": { /* 状态快照 */ },
  "trace": { "summary": {...}, "calls": [...] },
  "events": { "total": 42, "degradation_events": [...], "all": [...] },
  "cost_records": [...],
  "stats": { "total_tokens": ..., "total_calls": ..., "total_cost_usd": ... }
}
```

## 报告内容说明

### 降级事件（重点）

当 produce 节点检测到 `deployable_service.app_code` 等关键字段为空时，会发布 `produce.degradation` 事件，包含：

- `src_loc`：触发代码位置（文件路径 + 行号）
- `condition`：触发条件，例如 `deliverable_type=deployable_service 且 deployable_service.app_code 为空`
- `logic`：程序逻辑说明
- `state`：当前会议状态（stage、status、confidence_flags 等）
- `last_call`：最近一次 LLM 调用的模型、token、prompt/response 长度、验证状态

同时，日志也会输出相同信息，格式如：

```text
produce: LLM 返回内容不完整 — 空字段: ['deployable_service.app_code'] (触发位置: C:\...\produce.py:XXX)
```

### LLM 调用链

报告中每个调用卡片可展开，包含：

- **Prompt**：完整发送给模型的提示词
- **Raw Response**：模型原始返回文本
- **Parsed Result**：按 JSON Schema 解析后的结果
- **错误详情**：如果验证失败或网络异常

### 成本明细

按调用时间顺序列出每条 `cost_records` 记录，包含模型、token 数、美元成本、延迟、状态。

## 重跑前建议

1. **先生成当前失败的审计报告**，确认空字段类型和触发位置。
2. **检查 `trace.calls` 中 produce 阶段的 prompt 长度**：若 prompt 被截断，可能需要精简上下文。
3. **检查 `last_call.raw_response_length`**：若响应很短，说明模型确实没有生成代码；若响应较长但 parsed 后为空，说明 JSON 结构不符合 schema。
4. **查看前置阶段 evidence/claims 数量**：如果 evidence 极少，前置阶段信息不足，produce 可能无法生成有效代码。
5. **换模型重跑**：在确认问题后，可在前端或 API 中选择更强/更贵的模型，重跑 produce 阶段。
6. **重跑后立即再生成一份审计报告**，对比两次的 prompt、response、成本变化。

## 扩展：自定义日志持久化

当前日志默认输出到 stdout。若需要持久化日志文件以便按关键字检索，可设置环境变量：

```bash
set CONCLAVE_LOG_JSON_FILE=C:\Users\Huawei\Documents\Conclave\logs\conclave.jsonl
```

日志格式为每行一个 JSON，包含 `request_id`、`meeting_id`、`runner_session_id`、`agent_role`、`message`、`extra` 等字段，可与审计报告中的 `src_loc` 字段交叉定位。

## 相关文件

- `backend/app/routers/meetings.py`：审计端点实现
- `backend/app/orchestrator/nodes/produce.py`：produce 节点降级事件与日志
- `backend/app/agents/trace.py`：LLM trace 数据结构
- `backend/app/observability/cost_tracker.py`：成本记录逻辑
- `scripts/generate_audit_report.py`：HTML 报告生成脚本
