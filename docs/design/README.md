# Conclave 设计文档

本目录包含 Conclave 项目的架构设计、决策记录和实施计划。

## 核心文档

| 文档 | 版本 | 说明 |
|------|------|------|
| [团队管理与多租户设计](team-management-design.md) | v0.4 | 插件化架构、多租户、团队管理、配额系统的最终设计文档 |

## 决策记录 (ADR)

ADR（Architecture Decision Record）记录了每个重要架构决策的背景、选项、选择理由和后果。

| 编号 | 标题 | 状态 |
|------|------|------|
| [ADR-001](adr/001-plugin-architecture.md) | 插件化架构作为核心扩展机制 | Accepted |
| [ADR-002](adr/002-jsonb-metadata.md) | 元数据扩展槽(JSONB)而非核心表加业务字段 | Accepted |
| [ADR-003](adr/003-plugin-tiers.md) | 插件三层分级(CORE/CROSSCUTTING/OPTIONAL) | Accepted |
| [ADR-004](adr/004-hook-classification.md) | 钩子二分法(拦截型/观察型) | Accepted |
| [ADR-005](adr/005-real-priority-midpoint.md) | 优先级 REAL 中点算法(LexoRank) | Accepted |
| [ADR-006](adr/006-jwt-httponly-cookie.md) | JWT 存储于 HttpOnly Cookie | Accepted |
| [ADR-007](adr/007-quota-parent-pool.md) | 配额父池切分模型 | Accepted |
| [ADR-008](adr/008-quota-byok-fallback.md) | 配额耗尽自动降级(BYOK Fallback) | Accepted |

## 实施计划

| 计划 | 工期 | 说明 |
|------|------|------|
| [Phase 0+1: 插件框架地基](plans/phase0-plugin-foundation.md) | 3周 | 插件框架 + Auth 重构 + 核心钩子植入 |

## 文档规范

- **设计文档**（`*.md` 在根目录）是活文档，随代码迭代更新
- **ADR** 一旦 Accepted 不修改，决策变更通过新 ADR 取代
- **实施计划**完成后归档到 `archive/`

## 归档

| 文件 | 说明 |
|------|------|
| [v0.3 设计文档](archive/team-management-design-v0.3.md) | 被 v0.4 取代，归档保留 |
