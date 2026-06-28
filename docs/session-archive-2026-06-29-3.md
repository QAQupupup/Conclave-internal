# 会话归档 2026-06-29（第三次）

## 概述

用户指示"现阶段不用太关注前端排版，可以做几个不同阶段的改动"。本次完成 3 个后端重构改动，全部有回归测试保护，56 个测试通过。

## 完成的工作

### 1. P1-9：produce 产出类型 schema 强类型校验（commit `358e1d8`）

**问题**：`ProduceResult` 的 `code_analysis`/`tested_system`/`deployable_service` 字段是 `dict[str, Any]`，LLM 漏关键字段时校验不报错，静默丢失。

**修复**：
- 新增 `CodeAnalysisArtifact`（`code` 必填）
- 新增 `TestedSystemArtifact`（`main_code`/`test_code` 必填）
- 新增 `DeployableServiceArtifact`（`app_code` 必填）
- `ProduceResult` 字段从 `dict` 改为 `Optional[具体模型]`
- `nodes.py` + `refine_loop.py` 适配 `or {}` 防 None

**效果**：RealLLM 解析时关键字段缺失会触发 `ValidationError` → 重试 → 降级 StubLLM，不再静默丢失。

### 2. P0-6：角色画像统一到 ROLE_LIBRARY 单一数据源（commit `6c42be5`）

**问题**：`moderator`/`product_architect`/`engineer` 三个角色的视角+决策偏置文本在 `prompts.py` 和 `role_templates.py` 各维护一份，修改时需同步两处。

**重构**：
- `prompts.py` 的 `ARCHITECT_INTRA`/`ENGINEER_INTRA` 角色画像改为 `{role_persona}` 占位符
- `compute.py` 新增 `_get_role_persona()` 从 `ROLE_LIBRARY` 取 `prompt_template`
- `build_intra_prompt` / `build_intra_react_prompt` 渲染时注入 `role_persona`

**效果**：角色画像只在 `role_templates.py` 维护一处，`prompts.py` 只保留阶段骨架。

### 3. P1-13：EvidenceCollector 抽取消除检索逻辑重复（commit `f4b369c`）

**问题**：`_prefetch_evidence._retrieve_one` 和 `evidence_check_node._retrieve_evidence` 的 RAG + WebSearch + 降级逻辑完全重复（约 25 行）。

**重构**：
- 抽取 `_collect_evidence(meeting_id, conflict)` 统一函数
  - RAG 检索（`retrieve_for_conflict`）
  - 不足 3 条时 Web Search 补充
  - 无结果时 `_make_common_knowledge_evidence` 降级
- `cross_team` 预检索和 `evidence_check` 实时检索共用此函数

**效果**：消除约 25 行重复代码，检索逻辑修改只需改一处。净减 14 行代码。

## Commit 历史

| Commit | 内容 |
|---|---|
| `f4b369c` | refactor(orchestrator): P1-13 EvidenceCollector 抽取消除检索逻辑重复 |
| `6c42be5` | refactor(agents): P0-6 角色画像统一到 ROLE_LIBRARY 单一数据源 |
| `358e1d8` | fix(schema): P1-9 produce 产出类型 schema 强类型校验 |
| `09f820b` | docs: 归档 2026-06-29 会话记录（续） |
| `9b3ccb2` | test: 核心链路回归测试——38 个测试全部通过 |
| `fdf1d2b` | feat(ui): 消息内容语义化渲染 + 排版优化 |

## 测试验证

| 改动 | 测试数 | 结果 |
|---|---|---|
| P1-9 schema 强类型 | 38 | 全部通过 |
| P0-6 角色画像统一 | 56（含 role_matching + role_library） | 全部通过 |
| P1-13 EvidenceCollector | 38 | 全部通过 |

## Backlog 进展

已完成的 backlog 项：
- P1-9 schemas.py 未覆盖全部 produce 模板 ✅
- P0-6 角色画像描述统一到 ROLE_LIBRARY ✅
- P1-13 _prefetch_evidence 与 evidence_check 重复 ✅

下一步可做的 backlog 项：
- P0-12 BorrowAdjudicator（借调责任链，已有测试覆盖）
- P1-14 produce_node 改策略分派（中等风险）
- P1-9 已完成，但 StubLLM 的 deployable_service 分支仍缺失（不影响主流程）
