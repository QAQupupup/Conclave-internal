# Conclave 架构评审记录

> 本文档记录对三份架构输入的交叉评审：定位、价值、风险与分级判断。
> 它是“该不该现在做”的裁判依据，配合 [`design-principles.md`](./design-principles.md) 使用。
> 评审对象为早期架构探讨中三方给出的方案，本文以代号指代：**终态版**（架构终局设想）、**MVP 版**（可执行落地版）、**约束版**（可行性审计）。

---

## 1. 三份输入的定位

| 输入 | 作用 | 一句话定性 |
|---|---|---|
| 终态版 | 长期架构上限（天花板） | 已完成系统之后的架构复盘视角，非从 0 到 1 的实现路径 |
| MVP 版 | 可执行 MVP 蓝图（中间层） | 高质量 MVP 架构收敛方案，可开工级 |
| 约束版 | 落地约束与风险裁判（地基） | 把“架构幻想”压回 MVP，拒绝架构沉迷 |

三者叠加构成完整视角：愿景足够高，落地足够狠。`ideal-design.md` 承接终态版，`mvp-plan.md` 承接 MVP 版，本文承接约束版。

---

## 2. 终态版的价值与风险

### 2.1 真正有价值的部分

- **RAG 从检索系统升级为结构化知识系统**：chunk 为结构单元、term/entity/claim 抽取、图+语义混合检索，契合 Graph-enhanced RAG 真实趋势。
- **Event Runner 事件总线抽象**：WebSocket ≠ 核心，核心是 event bus + domain event，标准工程拆分。
- **Python 先做正确性再拆性能**：典型“先单体后服务化”路线。
- **Agent 记忆分三层**（raw / feature / profile）：整段最具产品价值的设计，可直接落地。

### 2.2 主要风险

- **把“未来系统”当“当前系统设计”**：chunk graph、术语系统、event runner、惰性管道、人格系统，每一个都是独立系统级项目，一起做会变成“还没做出产品就已设计平台”。
- **缺少最小可运行闭环（MVP loop）**：未回答第一版怎么跑起来。
- **大量“正确但无约束”的词**：chunk graph、lazy activation、evidence graph、conceptual normalization 等，无边界条件、无失败模式、无成本约束。
- **易引导架构沉迷**：写法是“你的系统已接近工业级 → 再升一层抽象”，导致设计越来越漂亮、落地越来越慢、MVP 永不完成。

### 2.3 评分

| 维度 | 评分 |
|---|---|
| 架构洞察 | 8.5 / 10 |
| 思维高度 | 9 / 10 |
| 工程落地性 | 5 / 10 |
| MVP 约束 | 3 / 10 |
| 过度设计风险控制 | 2 / 10 |

---

## 3. MVP 版的价值与隐藏问题

### 3.1 做对的关键点

- 成功把架构幻想压回 MVP：event runner / chunk graph / persona evolution / MQ / 多租户全部降级。
- 给出真实可跑闭环（议题→多 agent→辩论→证据→PRD→可选验证）。
- 状态机工程化（六阶段），强约束角色数量（5 或收敛到 3），RAG 降级为“能用版”，2 周计划可执行。

### 3.2 隐藏问题

- **仍低估工程复杂度**：所谓“6 模块简单系统”实为 mini AI workflow platform（编排 + RAG + rerank + WS + 状态机 + schema 生成）。
- **忽略 LLM 稳定性**：未认真处理 agent 一致性、prompt drift、hallucination propagation、arbitration bias。“仲裁者→结构化 PRD”若无强 schema 约束与 verification loop，会“看似结构化、内容质量不稳定”。
- **Docker 执行器偏重**：sandbox 安全、容器调度、超时、失败回传、依赖污染均为高风险，非 MVP 必需，属工程加分项。

### 3.3 评分

| 维度 | 评分 |
|---|---|
| 可落地性 | 8.5 / 10 |
| 产品真实感 | 8.5 / 10 |
| 克制程度 | 8 / 10 |
| 架构合理性 | 7.5 / 10 |
| 长期扩展性 | 7 / 10 |

---

## 4. 分级判断：现在做 / 暂缓 / 不做

### 现在就能用（v1 采纳）

- Event Bus 思想（内存版薄接口）
- Agent 三层记忆（结构先行，v1 只实现 raw 留底）
- Python 做 orchestration
- RAG 结构化趋势（轻量版：切块 + embedding + rerank）

### 暂时只记录，不实现

- chunk graph（先不用图数据库）
- terminology system（先不用完整本体）
- lazy embedding pipeline（先简化）
- multi-edge semantic graph（后期再说）

### 当前阶段不做

- 完整 event runner 架构（多 sink / MQ）
- full graph RAG system
- persona evolution system
- multi-sink observability pipeline

---

## 5. 过滤标准（长期可用）

判断一个设计是否“现在该做”，问三个问题：

1. **没这个能不能跑 MVP？** 能 → 推迟。
2. **是否影响主闭环？** 主闭环 = 输入 → 多 agent 协作 → 输出。不影响 → 不做复杂版。
3. **有没有可验证收益？** 不能在 1–2 周内验证 → 不做复杂版本。

---

## 6. 当前阶段结论

- 终态版是“完成态系统复盘视角”，非实现路径，已沉淀为 [`ideal-design.md`](./ideal-design.md) 长期参照。
- MVP 版可用但偏重工程，已降维为 [`mvp-plan.md`](./mvp-plan.md)，并按本评审进一步压缩复杂度（角色可收敛到 3、Docker 验证条件性引入）。
- 下一步唯一动作：**先跑通“3-agent + RAG + arbiter”的一次完整会议**，所有高级特性作为后续插件。
