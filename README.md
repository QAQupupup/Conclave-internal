# Conclave

> 会议型多智能体系统：议题 → 多 Agent 结构化辩论 → 证据支撑裁决 → 产出可验证的 PRD / 接口规范。
>
> 名称取自“Conclave（闭门会议 / 枢机主教团集会）”，对应系统的核心隐喻——一场有流程、有证据、有裁决的结构化会议。早期架构讨论曾使用代号 *Zore*，统一归并为 **Conclave**。

---

## 这是什么

Conclave 是一个**可演化的会议型智能体系统**。它把一次议题拆解为多智能体结构化辩论、证据支撑裁决、产物输出的完整闭环，并在迭代中沉淀智能体行为特征。

终态系统有三个判定特征：

1. **结构化知识系统**——检索不靠全文 embedding top-k，而靠保真原文、概念抽取、按需激活的知识图。
2. **事件驱动协作**——实时性不绑死 WebSocket，由事件广播 runner 统一负责。
3. **可迭代的个体**——发言全量留底，选择性提炼为长期行为特征与稳定画像，反哺下次会议。

---

## 为什么有这四份文档

本仓库的设计经历过三股力量的交叉校验：

| 来源 | 作用 | 沉淀到 |
|---|---|---|
| 原始蓝图 | 产品灵魂与所有核心想法 | 各文档 |
| 终态架构设想（终态版） | 长期架构上限：事件总线、三层记忆、结构化 RAG、Runner 抽象 | [`docs/ideal-design.md`](./docs/ideal-design.md) |
| MVP 落地版 | 可执行蓝图：闭环、状态机、角色约束、两周计划 | [`docs/mvp-plan.md`](./docs/mvp-plan.md) |
| 可行性审计（约束版） | 拒绝架构沉迷，分级判断“现在做 / 暂缓 / 不做” | [`docs/architecture-review.md`](./docs/architecture-review.md) |

这三者叠加构成完整视角：**愿景足够高，落地足够狠**。三者共同萃取的固化条款见 [`docs/design-principles.md`](./docs/design-principles.md)。

---

## 文档索引

| 文档 | 内容 | 何时读 |
|---|---|---|
| [`docs/ideal-design.md`](./docs/ideal-design.md) | 终态架构愿景（理想设计稿） | 想看系统最终长什么样 |
| [`docs/design-principles.md`](./docs/design-principles.md) | 设计原则与固化条款 | 做取舍决策、评审方案时 |
| [`docs/mvp-plan.md`](./docs/mvp-plan.md) | v1 可执行计划与两周开发表 | 准备动手开工时 |
| [`docs/architecture-review.md`](./docs/architecture-review.md) | 架构评审与风险裁判 | 判断“该不该现在做”时 |

文档间关系：`ideal-design` 是上限，`mvp-plan` 是地基，`design-principles` 与 `architecture-review` 是两者间的裁判与约束。

---

## 技术栈（按演进阶段）

| 层 | v1 | 终态 |
|---|---|---|
| 后端编排 | Python + FastAPI | Python（异构热点可换 Go/Rust） |
| 状态机 | 纯 Python 六阶段 | 七阶段 + 控场信号 |
| 检索 | 向量库 + embedding + rerank | Chunk Graph + 术语归一 + 惰性管道 |
| 记忆 | 工作记忆 + SQLite 留底 | 三层记忆 + 稳定画像 |
| 实时 | 内存 WebSocket 广播 | Event Runner + 多 sink / MQ |
| 执行 | 可选容器 lint/test | L1/L2/L3 风险分级 |
| 前端 | React 四块布局 | + 力导向图拓扑 |
| 存储 | SQLite | PostgreSQL + 向量库 |

---

## 演进路线

- **v1**：极简会议闭环——议题 → 多 Agent 辩论 → 证据 → PRD（可选代码骨架验证）。2 周可演示。
- **v2**：三层记忆、动态角色库、力导向图、事件总线抽象。
- **v3**：Chunk Graph、术语归一、自动借调、多租户、完整执行风险分级。

原则：不妥协愿景，但不被愿景绑架。先跑通主闭环，再以插件方式逐项引入终态特性。

---

## 当前阶段

下一步唯一动作：**先跑通“3-agent + RAG + arbiter”的一次完整会议**。所有高级特性作为后续插件装配，接口边界先画好。
