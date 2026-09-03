# ADR-018: 代码库理解层（LightRAG 范式 + Qdrant workspace 隔离）

## 状态

Accepted — 2026-09-04（"索引按项目共享"经严格风险评估确认无正确性缺陷；补 D11 内容所有权边界 / D12 按项目串行锁两项护栏后定稿。用户裁决 2026-09-04：隔离键由 `project_slug` 改为稳定的 `project_id`，slug 改名不再影响索引；新增 D13 索引-main 同步生命周期，闭合"议题合入 main → 索引增量"缺口）

## 背景

### 问题陈述

ADR-016 解决了代码库的**结构理解**（tree-sitter AST → 符号/调用图 + 向量切块检索），但用户诉求"把一个仓库变成可理解、可跨会话复用的知识"仍有三个断层：

1. **语义理解断层**：ADR-016 的图是静态 AST 边（IMPORTS/CALLS/INHERITS），回答不了"文档里的组件 A 与代码模块 B 是什么关系""这两个设计文档的结论是否矛盾""这个仓库整体是干什么的"这类**概念/语义查询**。
2. **理解成本断层**：当前摄入与索引按 `meeting_id` 隔离（`rag/code_index.py`），多个会议/窗口对同一仓库**重复理解**——每次全量解析 + 全量检索，浪费 token（用户核心关切）。交互模型需升级为"**仓库级一次性摄入 → 后台建索引 → 多会议/会话廉价复用**"（预构建一次、查询多次）。这也是文件夹上传议题的最终形态：放弃前端 JSZip 压缩与逐文件上传（几百文件场景体验与开销都不可接受）。
3. **演进断层**：代码库持续演进，但 ADR-016 的图在内存注册表（进程重启即失），无增量更新与失效清理机制；ADR-016 实施记录已把"增量索引"列为后续迭代。

### 选型结论（20260904-0018 检查点，源码级核实）

**LightRAG 优于 GraphRAG**（对 Conclave 场景）：

- 决定性因素：**增量更新**（代码库持续演进）+ **低 token 成本**（用户核心关切）。
- LightRAG 双层检索（低层实体 / 高层主题）恰好覆盖 Agent 局部问答 + 跨文件推理。
- GraphRAG 仅"全局架构综述"占优，但索引成本高、社区结构（community）难增量。
- 不引入 DeepWiki-Open / OpenDeepWiki 作永久组件：输入模型（仓库 URL clone vs 本地文件夹）、向量孤岛（本地文件系统 vs Qdrant）、产物形态（答案式 vs 图谱节点）三点不契合；可作验证 sidecar。DeepWiki-Open 的 RAG 是传统向量 RAG，非图 RAG。

**三项源码级核实**（一手证据，详见检查点 `sessions/2026-09/20260904-0018-lightrag-codebase-rag-selection.md`）：

| 核实项 | 结论 | 证据 |
|--------|------|------|
| Qdrant 适配 | ✅ 官方一等公民后端 | `lightrag/kg/qdrant_impl.py`（1475 行）`QdrantVectorDBStorage` |
| Qdrant 多租户 | ✅ 原生 workspace 隔离：`workspace_id` payload 索引 + `is_tenant=True` + 查询过滤 + 防跨工作区泄露 + `QDRANT_WORKSPACE` 环境变量 | 同上，直接命中 P8 多租户红线 |
| 嵌入维度安全 | ✅ 换嵌入模型检测维度不匹配抛 `DataMigrationError` | 同上 |
| 增量更新 | ✅ 内容哈希去重（`compute_mdhash_id`）+ `DocStatus` 状态机 + 增量合并（`collect_kg_merge_candidates` / `merge_nodes_and_edges`）+ 并行摄入 | `lightrag/lightrag.py` |
| 图谱清理 | ✅ 日志式 4 阶段 purge（`prepared → derived_committed → anchors_pending → completed`）+ `_PurgeRecoveryProof` 防孤儿 + `subtract_source_ids` 共享实体减法 + 崩溃可续跑 | 同上（上游 issue #3400） |
| 改名/重构 | ✅ 改名（内容不变）→ 内容哈希识别为同文档；重构 → 删旧 doc_id + 插新文档 | 同上 |
| **代码感知抽取** | ⚠️ 唯一未闭环：实体抽取是 LLM prompt 驱动、面向自然语言；4 种切块策略（Fix/Recursive/Vector/Paragraph）均为文本切块，非 AST 感知 | 本 ADR 的 D5 决策解决 |

### 代码核验（本次 grep 核实，2026-09-04）

```bash
grep -n "qdrant" docker-compose.yml
#   → qdrant 服务已存在（conclave-dev-qdrant，CONCLAVE_QDRANT_URL=http://qdrant:6333，持久卷）
grep -n "class QdrantVectorStore\|class.*Embedding\|class.*Reranker" backend/app/rag/store.py
#   → SiliconFlowEmbedding(:49) / SiliconFlowReranker(:217) / QdrantVectorStore(:554)
#   → Embedding/Reranker 支持 contextvars tenant_id 级配置覆盖（store.py:53,110-114）
grep -rni "lightrag" backend/          # 零结果：依赖不存在，需本 ADR 批准（AGENTS.md §5.3）
grep -n "_EXT_TO_LANG" backend/app/rag/code_parser.py
#   → 只认 .py/.js/.mjs/.cjs/.jsx/.ts/.tsx 七种扩展名；bash/YAML/SQL 返回 supported=False
grep -n "pf.supported" backend/app/rag/code_graph.py
#   → build_graph 对 supported=False 文件直接 continue：bash/yaml/sql 完全不进图/chunks
grep -n "_py_docstring" backend/app/rag/code_parser.py
#   → docstring 提取仅 Python，JS/TS 不提取 JSDoc（code_parser.py:86 明示）
```

> 上述后三条核验（2026-09-04 补充）直接支撑 D5 的"按文件类别三路分派"：符号序列化只覆盖
> 符号语言，bash/YAML/SQL 是部署/数据模型/CI 的语义高地却无符号可抽，必须走摘要+原文直入。

## 决策

### 总体架构：语义层叠加在 ADR-016 结构层之上，两层分工、级联检索

```
摄入层（复用 ADR-016）   结构层（ADR-016 已有）          语义层（本 ADR 新增）
routers/code.py          tree-sitter AST                 LightRAG 实体-关系抽取
git/zip 仓库级摄入  ──►  符号/调用/依赖图           ──►  双层检索（实体/主题）
                         回答"谁调用它/改它影响谁"        回答"它是什么/与谁相关/矛盾吗"
                                   └────── 检索级联：双入口召回 → reranker 融合 ──────┘
```

- **结构查询走 ADR-016 图**（精确、静态可确定）；**语义/概念查询走 LightRAG**（LLM 抽取、跨文件推理）。两层非替代关系，沿用 ADR-016 D4"向量管语义入口、图管结构扩展"的级联哲学。
- **索引按项目共享，不按会议**：同一仓库一个索引，多会议复用——这是"省 token"的直接来源。

### 关键决策点

| # | 决策 | 理由 | 备选（否决原因） |
|---|------|------|------|
| D1 | 采用 **LightRAG 范式**作语义理解层 | 增量更新 + 低 token 成本决定性；双层检索覆盖 Agent 两类查询（见选型结论） | GraphRAG：索引成本高、社区结构难增量；纯向量：够不到关系/矛盾查询 |
| D2 | **方案 A**：LightRAG 用自己的 collection 命名 + workspace 隔离，**独立于**现有 `QdrantVectorStore` 的 collection | 轻耦合，不破坏现有 RAG 的迁移/租户逻辑；两套存储各司其职（会议文档 RAG vs 仓库理解索引） | 方案 B（共享/改造现有 collection）：耦合重、破坏既有迁移逻辑 |
| D3 | 隔离键 `workspace_id = {tenant_id}:proj-{project_id}`（`projects.id` UUID，用户裁决 2026-09-04）；无项目的会议级摄入退化 `{tenant_id}:mtg-{meeting_id}`；`proj-`/`mtg-` 前缀区分两类键防止 UUID 撞键 | 用稳定 UUID 作键：slug 改名是纯元数据操作，索引零影响（原 slug 键方案的"改名孤儿索引"问题彻底消除）；租户前缀命中 P8 红线；LightRAG 原生 `is_tenant=True` 查询过滤直接复用 | 仅按 meeting 隔离：回到重复理解、浪费 token 的老路；按 `project_slug`：改名即孤儿索引，需重建兜底 |
| D4 | **复用现有 SiliconFlow Embedding/Reranker**：适配层把 `SiliconFlowEmbedding`（含租户级覆盖）包装为 LightRAG 的 embedding_func | 不引入第二套嵌入服务；租户配置覆盖链路（`store.py:110-114`）原样继承；维度不匹配有 `DataMigrationError` 兜底 | LightRAG 默认嵌入：绕开租户配置与 BYOK 体系（ADR-008） |
| D5 | **代码感知抽取走预处理、按文件类别三路分派，不改 LightRAG 切块器**：① 符号语言（`.py/.js/.ts/.tsx`）复用 ADR-016 `code_parser` 序列化为"符号签名 + docstring/JSDoc + 调用摘要"（补 JSDoc 提取）；② 配置/数据语言（`.yaml/.toml/.json/.sql/.ini`）不做 AST 符号化，走"轻量结构摘要 + 原文直入"（YAML 提顶级键结构、SQL 提 DDL 语句头）；③ 脚本/文档（`.sh/.md/.txt`）原文直入 | 闭合选型唯一未闭环项，并覆盖 bash/YAML/SQL 语义盲区（这些文件是部署/数据模型/CI 的语义高地，符号序列化对它们无符号可抽）；LightRAG 切块器文本向、改它维护成本极高；预处理让 LightRAG 保持上游可升级 | 一切走符号序列化：bash/YAML/SQL 无符号概念、掉进盲区；直接切块喂代码：纯代码文本抽取质量差；fork LightRAG 切块器：锁死升级 |
| D6 | 增量更新**直接复用** LightRAG 内建机制：哈希去重 + `DocStatus` 状态机 + 增量合并 | 源码级核实可用；改名=同文档、重构=删旧插新的策略天然匹配代码库演进 | 自研增量：重复造轮子 |
| D7 | 图谱清理**直接复用** LightRAG 4 阶段 purge；触发时机：文档删除、仓库重新摄入、项目删除 | 防孤儿 + 共享实体减法已源码级核实；崩溃可续跑降低长任务风险 | 自研清理：4 阶段状态机复杂度高，不值得 |
| D8 | **LLM 消耗治理**：实体抽取温度 0.0（对齐设计原则温度纪律）；首次全量索引分批 + 受配额约束（ADR-007）；后续仅增量 | 全量索引是一次性成本，增量成本随变更量线性；配额防止巨型仓库拖垮租户额度 | 不限速：巨型仓库 token 爆炸 |
| D9 | 新增依赖 `lightrag`（本 ADR 即批准依据，AGENTS.md §5.3），`requirements.lock` 锁死版本；适配层 `app/rag/lightrag_adapter.py` 隔离上游 API | 上游演进快，适配层防 API 漂移（教训：tree-sitter 未锁版本曾致 CI 静默降级） | 不锁版本：已踩过坑 |
| D10 | 索引生命周期：项目级索引常驻（随 `projects` 表，ADR-017 Phase 2）；会议级临时索引随会议删除清理；图/KV 存储用 LightRAG 内建文件存储，落 `workspace/projects/{project_id}/lightrag/`（与 D3 同键，改名零迁移），**不引入图数据库** | 与 ADR-016 D2 哲学一致（规模未到不引图数据库）；文件存储可随项目目录整体备份/清理 | Neo4j 等：重型依赖，规模未到 |
| D11 | **内容所有权边界**：仅仓库内容（代码/配置/文档）进项目共享索引；会议私有上传（设计文件/敏感资料）走会议级索引（D3 退化键 `{tenant_id}:mtg-{meeting_id}`），**绝不进项目索引** | 项目索引对项目内全体会议可见；若会议私有内容混入，会造成租户内跨会议信息泄露。这是项目级共享唯一现实泄露通道，必须显式成规则 + 集成测试 | 混合摄入：租户内跨会议泄露 |
| D12 | **按项目建索引串行化**：同一 `project_id` 的建索引请求用分布式锁串行（复用现有 Redis，或 PG advisory lock） | LightRAG 哈希去重 + `DocStatus` 仅保证单批内幂等；跨请求并发在同一 workspace 的 `merge_nodes_and_edges` 与文件图存储上可能竞态（重复实体/不一致边/写坏）。议题池并行会议场景下此情况大概率发生 | 并发建索引：图合并竞态、实体重复 |
| D13 | **索引-main 同步生命周期**：索引源 = 项目共享克隆（跟踪 `default_branch`，ADR-017 Phase 4 仓库缓存）；**议题合入 main 成功是唯一增量触发点**（走 ADR-017 D11 合入流程），范围 = `git diff` 出的变更文件（删除文件同步 purge 对应文档）；进行中的议题分支不进共享索引；增量重摄走 D12 串行锁 | 闭合"议题合入 main 后索引不同步"缺口；索引只跟 main，共享索引恒等于项目当前基线（与 D11 内容所有权边界一致）；与 ADR-017 D8 git 护栏哲学一致（合入 = 共享空间操作，显式触发） | 合入不触发、定期全量重摄：索引持续陈旧且成本不可控；webhook 实时同步：与"不做仓库 webhook 实时同步"决策冲突；索引跟踪议题分支：基线语义丢失，进行中代码跨会议可见 |

### 与其他 ADR 的关系

- **ADR-016（代码知识图谱）**：本 ADR 是其语义层补全，结构层原样保留；ADR-016 遗留的"图持久化到 PG"与"增量索引"两项，增量部分由本 ADR 的 LightRAG 机制承接（语义索引），结构图持久化仍是 ADR-016 自身欠账，不在本 ADR 范围。
- **ADR-017（产物链/项目/议题池）**：`projects.id`（project_id）是本 ADR 的隔离键（D3）；ADR-017 D11 的议题合入 main 流程是 D13 索引同步的触发点；ADR-017 Phase 4 的"项目级代码库理解索引"由本 ADR 实施；摄入入口复用 `routers/code.py`。
- **ADR-007/008（配额/BYOK）**：索引构建消耗受配额约束；嵌入走租户 BYOK 配置链路。

## 实施计划

### Phase A：LightRAG 集成骨架（1-2 天）

1. `requirements.txt` / `requirements.lock` 引入 `lightrag`（锁版本）。
2. `app/rag/lightrag_adapter.py`：包装 SiliconFlow Embedding/LLM 为 LightRAG 注入函数；初始化 `QdrantVectorDBStorage`（指向现有 `CONCLAVE_QDRANT_URL`），workspace 隔离键按 D3。
3. 冒烟：单文档插入 → 查询 → 换租户查询验证隔离。

### Phase B：仓库级摄入 + 代码感知预处理（3-5 天）

1. 摄入入口复用 `POST /{meeting_id}/code/ingest`，新增"建索引"开关；项目场景落 `workspace/projects/{project_id}/`（依赖 ADR-017 Phase 2 的 `projects` 表，此前退化会议级）。
2. `app/rag/code_to_text.py` 按文件类别三路分派（对应 D5）：① 符号语言（`.py/.js/.ts/.tsx`）tree-sitter 预处理（复用 `code_parser`，补 JSDoc 提取）→ 符号描述文本；② 配置/数据语言（`.yaml/.toml/.json/.sql/.ini`）轻量结构摘要（YAML 顶级键 / SQL DDL 语句头）+ 原文直入；③ 脚本/文档（`.sh/.md/.txt`）原文直入。
3. 分批摄入 + 配额检查 + `DocStatus` 进度可查（前端可见索引状态）。

### Phase C：检索级联 + 增量/清理接入（3-5 天）

1. `retriever` 增加语义入口：LightRAG 双层检索（实体/主题）与 ADR-016 结构扩展结果 rerank 融合。
2. 增量：仓库重新摄入时走哈希去重 + 增量合并；重构文件删旧插新。
3. 合入触发（D13）：议题合入 main 成功后，按 `git diff` 变更文件增量重摄（依赖 ADR-017 D11 合入流程与 Phase 4 共享克隆）。
4. 清理：文档/项目删除触发 4 阶段 purge；会议删除清理会议级临时索引。

### 测试策略（用户约定）

- **测试后置、整体跑**：各 Phase 开发期间只写测试不逐次跑容器；全部 Phase 完成后在 Docker 容器内一次性跑 `ruff check` + `ruff format --check` + `mypy` + `pytest` 全套，避免多次容器启停浪费 token/时间。

## 约束与风险

### 首次全量索引的 token 成本

- 巨型仓库首次索引是最大开销：分批 + 配额 + 仅索引文档与代码摘要（D5 的预处理天然压缩体积）；后续增量成本随变更量线性下降。这是"预构建一次、廉价查询多次"的代价前置。

### 上游版本漂移

- LightRAG 演进快：`requirements.lock` 锁版本 + 适配层隔离 API（D9）；升级走适配层回归测试。

### 嵌入模型切换

- 换模型触发 `DataMigrationError` 是预期行为：此时重建该项目索引（删旧 workspace → 重新摄入），不做向量迁移。

### Stub 模式降级

- 无 LLM/Embedding key 时 LightRAG 索引不可用：graceful 降级到 ADR-016 纯结构层检索，功能可用但无语义理解（对齐现有 Stub 降级哲学）。

### 多租户与内容所有权

- `workspace_id` 恒带 `tenant_id` 前缀；集成测试必须包含跨租户查询零命中用例（P8 红线）。
- 内容所有权边界（D11）：集成测试必须包含"会议私有上传不进项目索引、其他会议查询不到"用例。
- 并发建索引（D12）：必须走按项目串行锁；测试需验证同项目并发请求不产生重复实体/不一致边。

### slug 改名与索引独立性

- `workspace_id` 以稳定的 `project_id`（UUID）为键（D3，用户裁决 2026-09-04）：slug 改名是纯元数据操作，**对索引零影响、无需重建**，原 slug 键方案的"改名孤儿索引"问题彻底消除。slug 仅作人类可读展示与 URL 标识，tenant 内唯一约束不变。

### 索引同步时窗（D13）

- 合入成功到增量重摄完成之间存在时间窗，索引短暂滞后于 main：可接受（检索结果仅供参考，仓库本身才是事实源），窗口时长随变更量线性、受配额约束（D8）。重摄失败作为独立任务重试，不回滚已完成的合入（合入是既成事实，索引是派生缓存）。

## 不做的事

- 不改 LightRAG 内部切块器（代码感知走预处理，D5）。
- 不与现有 `QdrantVectorStore` 共享 collection（方案 B 已否决）。
- 不引入 DeepWiki-Open / OpenDeepWiki 作永久组件（可作 sidecar 验证实验，搁置项）。
- 不做仓库 webhook 实时同步（批量增量足够，与 ADR-016 一致）。
- 不替代 ADR-016 结构层（两层分工共存）。
- 不引入图数据库（LightRAG 内建文件存储起步，规模验证后另议）。
- 不承接 ADR-016 的结构图 PG 持久化欠账（属 ADR-016 自身范围）。
