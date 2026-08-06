# 知识资产化 / RAG / 图谱 / 编排器：修复前深度梳理与改造方案（ADR）

> 状态：Proposed · 日期：2026-08-06
> 性质：修复前的完整底数梳理 + 目标设计 + 分期方案。本文档是后续所有知识层/RAG/编排器改造的唯一依据。
> 证据基础：编排器探查（runner/stage_runners/nodes/routing）、记忆系统探查（memory/）、文档与话题关系探查（document.py/topic_decomposer/graph.py）、RAG 探查（rag/chunker.py/store.py/retriever.py）。
> 关联文档：mock-data-redline.md（红线）、frontend-fusion-plan.md（前端）、CONCLAVE-REVIEW-AND-RAG-REQUIREMENTS-2026-08-06.md（总审查）。

---

## 第一部分：现状底数（实证梳理）

### 1.1 编排器：流程、并行与依赖

**阶段推进**（证据：`conclave_core/state.py:406-413`、`workflow_templates.py:149`）：

```
topic → [意图分流 instant/plan/standard]
  → clarify（写 clarified_topic/key_questions/team_config；complexity=full 时拆子议题 DAG）
  → intra_team（角色 asyncio.gather 全并行，无角色间依赖，ADR-010 消除锚定；写 claims/team_conclusions）
  → cross_team（⚠ 主持人单次 LLM 调用，串行；写 conflicts；末尾 await 预检索证据）
  → evidence_check（逐冲突并行：RAG retrieve_for_conflict + RAG<3 条时 web 降级 + ReactLoop；写 evidence_set）
  → arbitrate（读 evidence_set+claims；写 decision_record）
  → produce（按 deliverable_type 分发：单次 LLM / phased_generation 7 阶段子管线 / 沙箱执行）
  → DONE → /meetings/{id}/report-layout（build_report_layout 纯函数，无 LLM 二次生成）
```

**回流机制三套并存**：① 节点内部预设下一阶段；② `routing.py` 元认知 LLM 动态路由（dynamic_routing=True 时，受 `_VALID_NEXT_STAGES` 约束）；③ 代码层硬门禁（cross_team supplement/re_examine ≤2 轮、produce 质量门禁迭代、全局回退 ≤5 次）。

**评估结论——编排器主干是健康的**：六阶段与设计原则一致；有界回退三层上限真实有效；intra_team 全并行正确；证据预检索有流水线意识；温度分阶段落实。不合理点集中在 §2.1。

### 1.2 报告链路

produce 产物存 `meetings.payload`（PG/JSON）+ `workspace_root/<meeting_id>/` 文件 → 前端 `/reports` 调 `report-layout` → `report_layout.py` 纯函数生成渲染 spec。**关键发现：spec 已设计 `findings.sources/trace`、`conflicts.trace` 等证据链块，前端只渲染了 8 种基础块——证据链展示断头在前端，后端数据是齐的**（低成本高价值修复点）。

### 1.3 记忆系统（比预期完整）

Raw→Feature→Profile 三层真实落地（PG 三表 + 进程内单例 + 读路径 fail-closed），per-(tenant, agent_role) 键控；会议结束触发 `record_raw→extract_features→update_profile`（confidence≥0.4 才合并）；画像以"【决策偏置…】"锚文本在 7 个角色 think 前注入 prompt。**缺口：特征提炼是纯关键词规则（无 LLM 语义提炼）；画像只携带行为偏置，不携带话题/文档知识。**

### 1.4 话题与文档关系（知识层最大短板）

| 维度 | 现状 | 缺口 |
|---|---|---|
| 子议题 | `topic_decomposer.py` 产出 DAG（≤5 节点深≤3、无环校验、拓扑排序），但只序列化进 `meetings.payload`，无独立表 | 子议题不可查询、不可复用 |
| 会议间关联 | 唯一机制是 `reference_meeting_ids` **用户手动指定**；`MeetingModel` 无 parent/series/topic_embedding 字段 | 无自动"临近话题"推荐 |
| 文档 | `DocumentModel.meeting_id` 非空强绑定单会议；原文不落盘（内存字典）；每会议独立向量 store；`content_hash` 可做跨会议去重 | **文档是耗材不是资产** |
| 文档间关系 | 无任何关系表；`Chunk.claims/relations` 是空占位（"迭代三填充"） | 无相似/引用/实体关系 |
| 实体机制 | `domain_registry.py` 是 web 信源分级表（别名+子串匹配），不可直接复用，但模式可借鉴 | 无业务实体库 |
| 图谱 | `routers/graph.py` 每次请求 SQL 现算，只产 3 种弱边（proposed_by/derived_from/时间序 relates_to）；边类型白名单里 supports/contradicts/evidence **已声明但无数据源** | 无语义边、无持久化 |
| workspace | 纯文件系统视角（`workspace_root/<meeting_id>/`），与 documents 表/RAG chunk 完全不通 | 产物文件与知识资产割裂 |

### 1.5 RAG 检索管线（亮点与缺陷并存）

已有：bge-m3 embedding（租户可配）+ HyDE + 多路查询改写 + RRF 融合 + 云端 rerank + 注入防护 + 邻居扩展——**检索管线是项目里完成度最高的子系统**。
缺陷：① 切分器不感知代码围栏（装饰器可被 `# 注释` 行与函数切散）；② 无 chunk 大小控制/overlap/合并；③ 关键词路是伪 BM25（IDF=1）；④ Qdrant 模式关键词召回只走内存缓存；⑤ 检索过滤疑似缺 meeting_id（跨会议串扰，**待核实，优先级最高**）；⑥ 原文与索引无持久化重建。

---

## 第二部分：不合理点确认

### 2.1 编排器（5 点，按严重度）

1. **路由双轨制**（`runner.py:813-873` vs `stage_runners.py:343-374`）：节点预设 + 元认知路由 + 门禁硬回流三套决策并存，LLM 路由理论上可绕开门禁 MAX_GATE_ROUNDS=2 上限（仅有全局 5 次兜底）。runner 还要临时回写 `state.stage` 才能让路由判断当前位置，脆弱。
2. **cross_team 单点串行 + 假流水线**：全队 claims 压进一次主持人调用；`_prefetch_evidence()` 在 cross_team 内部 await（`stage_runners.py:338-339`），所谓预检索并未与后续计算真正重叠。
3. **上下文预算覆盖不全**：`ContextBudget`（8000/1500）只作用于新 Scheduler 路径；legacy 的 evidence_check/produce（最重的两个阶段）无 token 预算；子议题切换时 claims/conflicts/evidence 硬清空（`runner.py:638-650`），仅靠 `reference_context` 摘要传递，**早期细节真实丢失**。
4. **证据链断点**：`prefetched_evidence` 曾用下划线字段导致 pydantic 不序列化、崩溃即丢（`evidence_check.py:47-50` 自认）；evidence_check 无冲突时整阶段可被路由跳过（`routing.py:177-178`），arbitrate 基于空 evidence_set 裁决。
5. **报告证据链前端断头**（见 §1.2，最低成本修复点）。

### 2.2 知识层（1 个根因 + 5 个表现）

**根因：知识被建模为会议的私有耗材，而非租户级资产。** 所有表现（文档强绑会议、向量 per-meeting、无文档关系、无临近话题、workspace 与 documents 割裂）都是这一个数据模型决策的推论。这与产品愿景直接冲突——三层记忆的设计意图就是"跨会议积累"，而知识层恰恰是零积累。

---

## 第三部分：目标设计

### 3.1 知识资产化（根改造）

**新实体 `knowledge_spaces`**：`id / name / tenant_id / scope(personal|team|default) / kind(persistent|ephemeral) / created_at`。
> 已定稿（§6 决策 1）：**首期只做单一租户默认空间**——每租户自动创建一个 default persistent space，UI 不暴露空间管理；`scope` 字段保留为后续 personal/team 分级预留，首期固定 `default`。

**DocumentModel 改造**：
- `space_id` 非空（替代 `meeting_id` 非空约束）；`meeting_id` 改可空，表示"首次上传来源"。
- 新增关联表 `meeting_document_refs(meeting_id, document_id, added_at, added_by)`——会议通过引用使用文档，一份文档可被多会议引用。
- **临时附件双轨**：会议内直接上传的附件自动进入该会议的 ephemeral space；用户可一键"转存"到 persistent space。统一模型、不同生命周期，检索路由统一。
- **临时附件生命周期（已定稿，§6 决策 2）**：会议删除/结束后**不立即清理**，进入 N 天缓冲期（默认 7 天，`CONCLAVE_EPHEMERAL_TTL_DAYS` 可配）；到期由后台任务将文档 `status` 置 `recycled`（回收箱，原文与向量保留、检索不再命中）；回收箱再保留 M 天（默认 30 天，`CONCLAVE_RECYCLE_TTL_DAYS`）后物理删除。**会议回看保障**：`meeting_document_refs` 永不随 TTL 删除，历史会议详情页文档列表照常展示（recycled 标注"已归档"），单文档原文始终可读、可一键恢复。
- **原文落盘**：`workspace_root/kb/<space_id>/<doc_id>__<filename>`，DB 存 `storage_path`；新增 `POST /documents/{id}/reindex`（从原文重建切分+向量）。
- **向量检索过滤**：Qdrant 检索 filter 改为 `{tenant_id, space_id ∈ 当前会议引用的 spaces}`——顺带修复跨会议串扰嫌疑（核实后若属实则此项升级为事故级先行修复）。

**数据迁移**：存量 documents 每会议的文档迁入自动创建的 ephemeral space，挂 `meeting_document_refs`。Alembic 迁移（借此次改造推动 DDL 单轨化）。

### 3.2 临近话题（语义相近历史会议）

- 新 Qdrant collection `conclave_topics`：会议创建时和 DONE 时写入议题向量（payload: meeting_id/tenant_id/status/deliverable_type/summary/tags）。
- **创建时推荐**：用户在 board 输入议题时（防抖 500ms）检索 top-5 相似历史会议，弹窗中展示"相关历史会议"供勾选 → 自动填充 `reference_meeting_ids`（复用现有 `_build_reference_context` 全链路，零后端管道改造，只换数据源）。
- **完成后聚类**：DONE 会议按向量相似度在 board/reports 页展示"相关会议"侧栏。
- 复用积木：`meeting_tags` 表作为显式聚类钩子；Qdrant + bge-m3 已就位。

### 3.3 文档间关系与 GraphRAG-lite

**`document_relations` 表**：`src_doc_id / dst_doc_id / relation_type(duplicate|similar|derived|cites) / score / created_by(pipeline|user) / tenant_id`。

自动边分三级（成本递增，分阶段启用）：
1. **零成本级（Phase 2）**：`content_hash` 相同 → duplicate；chunk 向量质心余弦 > 阈值 → similar。纯计算无 LLM。
2. **轻量 LLM 级（Phase 3）**：填充 `Chunk.claims/relations` 占位——上传后后台惰性任务，每 chunk 抽取 ≤5 条 claims + ≤8 个实体（LLM 温度 0.0，符合原则 9）；实体落 `entities` + `chunk_entities` 表；跨文档共享实体 → 生成 cites/related 边。
3. **图谱检索级（Phase 3）**：检索时向量召回 + 沿实体边一跳扩展（LightRAG 式 dual-level：low-level 具体实体 + high-level 主题），**不上 Neo4j，三元组存 PG**（控制依赖，符合运维极简原则）。
4. **明确不做**：Microsoft GraphRAG 的社区检测/全局摘要（索引成本与会议场景不匹配）。

### 3.4 图谱物化（低垂果实）

- `routers/graph.py` 从"每次现算 3 种弱边"升级为物化边表 `graph_edges`（或复用 document_relations + claim 边统一模型）。
- **现成的语义边数据源**：`state.conflicts`（结构化冲突，含双方 claim 引用）→ `contradicts` 边；`evidence_set`（证据→claim 支撑关系）→ `supports` 边 + evidence 节点。会议 DONE 时物化——白名单里的边类型终于有数据源。
- 前端 `/graph` 并入会议视图（见前端融合方案），复用现有力导向渲染器，扩边类型着色即可。

### 3.5 报告证据链（Phase 2  quick win）

前端 `ReportBlockRenderer` 补渲染 spec 已有的 `findings.sources/trace`、`conflicts.trace` 块：结论可展开查看证据引用（doc:section / web:url 可点击溯源到 chunk 原文预览）。后端零改动。

### 3.6 MCP 知识源接入

- 后端实现 MCP client（stdio + SSE 双传输），知识源注册为 space 的一种（`source_type: mcp`）。
- 第一个连接器：Obsidian vault（复用现有 `docker-compose.obsidian-mcp.yml` 服务，把"开发者个人记忆"升级为产品能力）。
- MCP 资源 → 统一解析 → 统一切分 → 统一索引管线，与上传文档同权检索；权限按 space 隔离。

### 3.7 切分器重写（RAG 一切工作的前置）

1. **围栏感知状态机**：逐行扫描，进出 ```` ``` ```` 围栏切换状态，围栏内行不参与标题匹配——修复装饰器/注释行被误切问题（用户关切的根因）。
2. 全层级标题（`#`–`####`），metadata 携带完整标题路径。
3. 大小控制：max ≈1200 字符，超长段落边界二次切 + 10% overlap；<200 字符与后继合并（借鉴 `tools/playwright/chunk_js.py` MIN_CHARS）。
4. **代码文件走 tree-sitter AST 切分**：按 `decorated_definition/function_definition/class_definition` 节点切——装饰器与函数天然同块（回应用户对 AST 切分的顾虑：问题从来不在 AST，在于土法切分）。
5. 表格/列表保持原子块不切断。

### 3.8 编排器改进（与知识改造解耦，可并行）

| 项 | 改动 | 风险 |
|---|---|---|
| 路由收敛 | 门禁硬回流保留代码层唯一决策权；routing.py 元认知仅在门禁无异议时生效，且与门禁共享回流计数器（不可绕过 MAX_GATE_ROUNDS） | 中，需契约测试 |
| 预检索真并行 | `_prefetch_evidence` 改 fire-and-forget task，evidence_check 消费 future（未就绪则自检索兜底） | 低 |
| 预算全覆盖 | legacy 路径（evidence_check/produce）接入 ContextBudget | 中 |
| prefetched 序列化 | 修复下划线字段不序列化问题，纳入 state.snapshot | 低 |
| 子议题断层 | 切换时 `reference_context` 从"摘要"升级为"摘要 + 锁定结论链 + 证据指针" | 中 |
| cross_team 并行化 | **暂缓**。主持人综合需要全局视野，拆并行收益不明确，先在 eval 上验证必要性 | — |

---

## 第四部分：测试策略（针对复杂能力专项设计）

> 用户特别要求：测试要仔细设计。原则——**不再裸信大模型生成的测试**，所有测试过 AGENTS.md §5.7 审查关；复杂能力用"黄金对照集"而非例行人肉断言。

1. **切分器黄金集**：`tests/rag/fixtures/` 存放对照文档 + 期望 chunk 边界 JSON。必须包含：带装饰器+注释行的 Python 代码块、C 代码 `#include`、5 万字单章节、嵌套表格、四级标题。断言 chunk 边界与 metadata 标题路径。
2. **检索黄金 QA 集**：20-50 条 `query → 应命中 chunk_id` 标注，Stub embedding 确定性下断言召回率；真 embedding 走 eval 管线（不阻塞 CI）。
3. **知识资产 DAO 测试**：双租户/双 space 隔离用例（互不可见）；ephemeral space TTL 清理；reindex 幂等。
4. **编排器契约测试**：每阶段 `state in → state out` 快照契约；门禁回流次数上限测试（验证路由不可绕过）；预检索 future 未就绪降级测试；子议题切换后 reference_context 完整性测试。
5. **测试质量门禁（元测试）**：AST 扫描脚本——检测无断言测试函数、条件断言（`if x: assert`）、`except: pass`，纳入 CI。现有 8 个无断言测试与 `test_stats.py` 条件断言先行修复。
6. **eval 指标扩展**：eval_v2 增加 RAG 维度（检索召回率、引用正确率、证据链完整率），与会议质量分并列。

---

## 第五部分：分期与验收

| Phase | 内容 | 验收 | 依赖 |
|---|---|---|---|
| **P0 清场**（先行） | mock 清除（MR-8）+ 前端主闭环（创建弹窗/真实上传/消息兜底）+ **Qdrant meeting_id 过滤核实** | 生产零 mock；真实会议全流程可走通一次；串扰核实有结论 | 无 |
| **P1 知识资产化** | §3.1 数据模型改造 + 落盘 + reindex + §3.7 切分器重写 | 重启后文档可检索；双 space 隔离测试通过；切分黄金集全绿 | P0 |
| **P2 关系与图谱 quick win** | §3.2 临近话题推荐 + §3.4 图谱物化（conflicts/evidence 边）+ §3.5 报告证据链渲染 + 零成本文档关系边 | 创建会议可见相似历史会议推荐；图谱出现 supports/contradicts 边；报告结论可溯源 | P1 |
| **P3 GraphRAG-lite** | §3.3 实体/claims 抽取管线 + document_relations 全量 + 一跳图扩展检索 + 记忆 LLM 语义提炼升级 | "X 与 Y 什么关系"类查询可命中；跨文档实体边可见 | P2 |
| **P4 编排器与 MCP** | §3.6 MCP/Obsidian 接入 + §3.8 编排器五项改进 + §4.6 eval 指标 | Obsidian vault 笔记可被会议引用；编排器契约测试全绿 | P1 起可并行 |

**顺序约束**：切分器重写（P1）必须先于实体抽取（P3）——垃圾切分喂不出好实体；知识资产化（P1）必须先于临近话题（P2）——没有持久层就没有可复用的向量。

## 第六部分：决策点（5/5 已定稿）

1. ✅ **space 粒度（已定稿 2026-08-06）**：**先做单一租户默认空间**——每租户自动创建一个 default persistent space，UI 不暴露空间管理，`scope` 字段预留后续 personal/team 分级。理由：先跑通资产化主链路，权限分级后续跟进。
2. ✅ **临时附件 TTL（已定稿 2026-08-06）**：**N 天缓冲 + 回收箱**，不随会议删除即清。缓冲 7 天（可配）→ 回收箱（status=recycled，原文保留、检索不命中）→ 30 天后物理删除。理由：用户明确指出"会议后期再点进来回看时，需要能看到、看明白"——`meeting_document_refs` 永不随 TTL 删除，历史会议文档列表与原文始终可读。
3. ✅ **实体抽取的触发时机（默认采纳建议，2026-08-06）**：**惰性抽取 + 后台闲时补抽**（首次检索命中后抽，符合原则 1⑤分层惰性）。
4. ✅ **编排器路由收敛（已定稿 2026-08-06，按建议）**：**先出独立 ADR 再动手**（改动决策逻辑，影响面大）。
5. ✅ **MCP 连接器范围（已定稿 2026-08-06，按建议）**：**首期只做 Obsidian 跑通，接口按通用 MCP server 设计**。
