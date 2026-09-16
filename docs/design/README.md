# Conclave 设计文档

本目录包含 Conclave 项目的架构设计、决策记录和实施计划。

## 核心文档

| 文档 | 说明 |
|------|------|
| [Conclave 设计原则（固化条款）](design-principles.md) | 11 条固化设计原则（RAG 五原则、借调三问法、MVP 三问等） |
| [团队管理与多租户设计](team-management-design.md) | 插件化架构、多租户、团队管理、配额系统（v0.4） |

## 决策记录 (ADR)

ADR（Architecture Decision Record）记录了每个重要架构决策的背景、选项、选择理由和后果。

| 编号 | 标题 | 状态 |
|------|------|------|
| [ADR-001](adr/001-plugin-architecture.md) | 插件化架构作为核心扩展机制 | Accepted |
| [ADR-002](adr/002-jsonb-metadata.md) | 元数据扩展槽（JSONB）而非核心表加业务字段 | Accepted |
| [ADR-003](adr/003-plugin-tiers.md) | 插件三层分级（CORE / CROSSCUTTING / OPTIONAL） | Accepted |
| [ADR-004](adr/004-hook-classification.md) | 钩子二分法（拦截型 / 观察型） | Accepted |
| [ADR-005](adr/005-real-priority-midpoint.md) | 优先级 REAL 中点算法（LexoRank） | Accepted |
| [ADR-006](adr/006-jwt-httponly-cookie.md) | JWT 存储于 HttpOnly Cookie | Accepted |
| [ADR-007](adr/007-quota-parent-pool.md) | 配额父池切分模型 | Accepted |
| [ADR-008](adr/008-quota-byok-fallback.md) | 配额耗尽自动降级（BYOK Fallback） | Accepted |
| [ADR-009](adr/009-meeting-state-sections-migration.md) | MeetingState Sections 迁移策略 | Accepted |
| [ADR-010](adr/010-claim-refinement-and-evidence-honesty.md) | 论点提纯架构与证据诚实性 | Accepted |
| [ADR-011](adr/011-incremental-session-checkpoint.md) | 会话检查点增量与结构化改造 | Superseded（→ ADR-012） |
| [ADR-012](adr/012-index-raw-two-layer-checkpoint.md) | 会话检查点 Index+Raw 2 层架构 | Accepted |
| [ADR-013](adr/013-orchestrator-state-machine-contract.md) | 编排器状态机契约 | Accepted |
| [ADR-014](adr/014-dynamic-workflow-assembly.md) | 动态工作流编排与议题拆分 | Accepted |
| [ADR-015](adr/015-prompt-regression-and-multi-agent-scoring.md) | Prompt 回归测试与多 Agent 并行讨论质量评估 | Accepted（Phase 1 已落地，Phase 2-4 待开始） |
| [ADR-016](adr/016-code-graph-rag.md) | 代码知识图谱 RAG（Code Graph RAG） | Accepted |
| [ADR-017](adr/017-artifact-chain-project-issue-pool.md) | 产物链、项目命名空间与议题池 | Accepted（Phase 3 进行中） |
| [ADR-018](adr/018-codebase-understanding-lightrag.md) | 代码库理解层（LightRAG 范式 + Qdrant workspace 隔离） | Accepted |
| [ADR-019](adr/019-schema-single-source-of-truth.md) | Schema 单一真相收敛（Alembic 全托管） | Accepted（2026-09 落地） |
| [ADR-020](adr/020-contract-first-and-borrow-overlap.md) | 契约优先工程固化与借调重叠检测 | Accepted（Phase 0-4 规划，2026-09） |

> ADR-015、ADR-017 各附带一份 `*-implementation-tasks.md` 实施任务清单，记录分阶段落地状态，不属于独立编号 ADR。

## 实施计划

| 计划 | 工期 | 说明 |
|------|------|------|
| [Phase 0+1: 插件框架地基](plans/phase0-plugin-foundation.md) | 3周 | 插件框架 + Auth 重构 + 核心钩子植入 |

其他历史设计与一次性评审文档见目录根（`iteration-*-design.md`、`*-review.md` 等），已完成使命的一次性分析文档归档在 `../archive/`。

## 文档规范

- **设计文档**（`*.md` 在根目录）是活文档，随代码迭代更新
- **ADR** 一旦 Accepted 不修改，决策变更通过新 ADR 取代（如 ADR-011 → ADR-012）
- **实施计划**完成后归档到 `archive/`

## 归档

| 文件 | 说明 |
|------|------|
| [v0.3 设计文档](archive/team-management-design-v0.3.md) | 被 v0.4 取代，归档保留 |
