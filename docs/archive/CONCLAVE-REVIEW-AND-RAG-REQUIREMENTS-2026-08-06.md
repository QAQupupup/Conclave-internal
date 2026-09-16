# Conclave 项目综合审查与 RAG/知识库能力建设需求分析

> 日期：2026-08-06
> 性质：深度实证审查 + 需求分析 + 可执行建设方案
> 方法：四条并行审查线（架构 / 前端 / 测试 / RAG），所有结论均附文件路径证据，禁止"凭感觉"声明（遵循 `docs/pitfalls.md` P21/P22）

---

## 0. 摘要：当前最大的五个问题

| # | 问题 | 严重度 | 一句话 |
|---|------|--------|--------|
| 1 | **RAG/知识库能力名存实亡** | P0 | 只支持纯文本 md/txt 上传、前端根本没接上传 API、文件不落盘重启即丢、无 PDF/DOCX 解析、无 GraphRAG、MCP 零集成 |
| 2 | **前端核心流程断裂** | P0 | 创建会议不能选 Agent/团队；历史消息无 REST 兜底，WS 断线即白屏；消息发送失败静默；两个"会议列表"入口互相打架 |
| 3 | **编排器巨型化 + 全局状态** | P1 | `runner.py` 1988 行、`produce_node` 单函数 660 行、12 个超 800 行文件；进程内字典当状态存储，无法横向扩容 |
| 4 | **测试覆盖结构性失衡** | P1 | DAO 层 8 个模块**全部零测试**；orchestrator 19 个模块中 12 个零测试；`test_stats.py` 存在"崩溃也通过"的条件断言 |
| 5 | **切分器结构性缺陷** | P1 | 唯一切分器是一条不感知代码围栏的正则，md 内嵌代码的 `# 注释` 会被当成标题切开——装饰器与函数确实可能被分离（机制与 AST 无关，详见 §4.3） |

---

## 1. 整体架构审查

### 1.1 健康面（值得保留）

- 分层清晰：routers / schemas / domain / dao / db/models / orchestrator / agents / tools / plugins / tenants / rbac，职责分明；`models.py` 已退化为 50 行兼容 shim。
- 编排器有界回退设计扎实：全局回退上限 5 次（`runner.py:822`）、阶段循环上限 `_MAX_LOOP_COUNT`（`nodes/routing.py:38-43`）、单阶段重试 2 次（`domain/meeting.py:131`），无无限回退。
- 防御机制真实落地：prompt 注入检测、模型快照、沙箱命令黑名单、插件体系。
- 配置环境变量化（`CONCLAVE_*` 前缀），无硬编码密钥。

### 1.2 架构问题（按严重度）

1. **巨型文件/上帝类（P1）**：12 个 .py 超 800 行。最严重的五个：
   - `backend/app/sandbox.py` — 2001 行
   - `backend/app/orchestrator/runner.py` — 1988 行，`Runner` 类约 1530 行，混入状态机、LRU 缓存、六个质量评估方法
   - `backend/app/orchestrator/nodes/produce.py` — 1721 行，`produce_node` 单函数约 660 行
   - `backend/app/agents/llm.py` — 1637 行
   - `backend/app/routers/meetings.py` — 1589 行
2. **编排器进程内全局可变状态（P1）**：`runner.py:38-44` 的 `_states`/`_cleanup_tasks`/`_intervention_locks` 是模块级字典 + 手写 TTL/LRU 淘汰，崩溃恢复靠从 PG 重建——自研有状态调度器，横向扩容即失效。
3. **DDL 双轨制（P1）**：启动时走 `dao/db_init.py`（147 行内联 DDL + 14 条补丁式 `ALTER TABLE`），同时 `alembic/versions/` 存在 0001–0005 五个迁移但启动流程从不调用。两套 schema 来源必然漂移。
4. **多租户为应用层手工过滤（P2）**：`tenant_id` 可空列 + 每个 DAO 自觉拼 `tenant_filter_clause`，漏一个 DAO 就是跨租户泄露；无数据库级 RLS。
5. **自相矛盾的配置**：`config.py:81` 默认连接串内嵌口令；`main.py:590` uvicorn 绑 `127.0.0.1`，与自家 `code_conventions.yaml:92`（必须绑 0.0.0.0）矛盾。

### 1.3 系统工程/仓库卫生

- 根目录 7 个 docker-compose 文件职责重叠（主文件 15 个服务，含 gitea、docker-socket-proxy 等可疑成员），无 profiles 归并。
- 根目录散落 20+ 审计产物目录（`arch-debt-audit/`、`cross-audit-analysis/`、`dual-audit-meta-review/`、`meta-meta-review/`、`Qwen3.7-Plus-*/` 等）+ `debug.log`、`ms.md`。
- `docs/` 324 个文件中 `docs/audits/` 占 219 个，日期戳报告无限累积，无归档/索引——典型文档腐烂。
- `archive/` 有 97 个文件被 git 跟踪（含整个旧前端 `frontend-react-original`）。
- 一个值得注意的信号：`CONCLAVE-CROSS-VERIFY-REPORT-2026-08-04.md` 显示外部审计 10 条声明中 6 条有偏差——代码可读性差到深度审查者都会误判，可读性本身就是架构问题。

---

## 2. 前端体验审查（"不好用"的实证定位）

前端体量：src/ 约 100 个源文件、2 万行。整体设计 token 化做得不错（硬编码 hex 仅 19 处、`!important` 仅 3 处且正当），**观感的底子不差，问题集中在流程断裂和交互残缺**。

### 2.1 信息架构问题

- **双会议列表入口**：`/board`（`features/board/page.tsx:47`）与 `/explore`（`features/explore/list-page.tsx:37`）都调 `useMeetings({pageSize:50})` 渲染会议列表，用户面对两个功能重叠的入口。
- `/landing` 是孤儿路由，无入口指向，疑似死代码。
- 会议产物查看路径割裂：`/explore/:id`（WS 实时流）与 `/reports`（REST，740 行）数据源不同。

### 2.2 核心流程体验缺陷（按严重度）

| 严重度 | 问题 | 证据 |
|--------|------|------|
| 高 | **创建会议无法选择 Agent/团队**——只提交 `{topic}`，尽管 mutation 已支持 `agents`/`deliverable_type` 参数 | `features/board/page.tsx:92`、`hooks/use-meetings.ts:189` |
| 高 | **历史消息无 REST 兜底**——`useMeetingMessages` 全工程零调用（死代码）；WS 建连失败则历史消息永久不可见，只有"等待 Agent 开始讨论..."空态 | `hooks/use-meetings.ts:164`、`components/meeting/message-stream.tsx:148` |
| 中 | **消息发送失败静默**——WS 未连接时无 toast、无重发，用户以为已发送 | `message-stream.tsx:94` |
| 中 | **假交互入口**——"分支探索"按钮只 toast"功能开发中" | `message-stream.tsx:117` |
| 中 | **看板无实时刷新**——运行中会议状态需手动刷新（operations 页有 30s 轮询，board 没有） | `features/board/page.tsx` 对比 `features/operations/page.tsx:745` |
| 低 | 接管面板硬编码深色 `bg-[#1a1a2e]`，浅色主题下突兀 | `takeover-panel.tsx:115` |

WS 层本身做得扎实（心跳 25s、指数退避、seq 断点续传、连接状态指示），不是短板。

### 2.3 代码质量与响应式

- 9 个页面级巨型组件（>400 行）：`agents/page.tsx` 1142 行、`operations/page.tsx` 1091 行、`reports` 740、`workspace` 702、`models` 699、`graph` 645、`admin` 644、`teams` 553、`settings` 479。
- `lib/mock-data.ts` 1612 行 mock 数据被生产路径引用，`isDemoMode()` 分支散落各处——观感"演示味"的来源之一。
- `components/ui/svg-icons.tsx` 1161 行手写图标库，应换 lucide-react。
- **响应式基本缺失**：全 src 仅 49 处断点，`/graph`、`/reports`、`/teams`、`/settings`、`/models`、`/explore/:id` 零断点，移动端不可用。
- `ErrorBoundary` 全站仅 1 处，单页崩溃白屏整站。
- 类型双重维护：`meeting.messageCount ?? meeting.message_count` 兜底散落各处，API 契约不稳定。

### 2.4 前端测试

仅 10 个测试文件（97 用例），会议核心链路（message-stream、stage-timeline、takeover-panel、ws.ts 重连、537 行 ag-ui 事件适配器）零测试；9 个巨型页面 7 个无测试；无 E2E。

---

## 3. 测试质量审查

### 3.1 规模

- 后端：68 个测试文件、1028 个用例、测试/源码行数比 ≈ 0.30 —— 规模尚可。
- 前端：10 个文件、97 个用例 —— 与源码体量严重不匹配。

### 3.2 反模式实证（对照 AGENTS.md §5.7）

- 恒真断言、自 mock、`.not.toThrow()` 滥用：**均为零**，达标。
- **无断言测试 8 个**（违反 §5.7.2）：`test_event_bus.py:71/76`、`test_password_hash.py:44`（安全心脏，仅两次 `base64.b64decode` 无断言调用，而 `b64decode` 默认不 validate 几乎恒通过）等。
- **最恶劣案例 `test_stats.py:100-135`**：`Runner().run()` 异常被捕获后不 fail，`if runner_exception is None: assert state.status == DONE` —— **流程崩溃与正常完成测试都通过**。
- 快乐路径：全局仅 9/68 个文件使用 `pytest.raises`；抽样中 `test_meeting_sections.py`、`test_workflow_templates.py`、`test_topic_decomposer.py`（共 83 用例）几乎纯快乐路径，违反 §5.7.9。
- 灰色地带：多个名为 e2e 的测试 monkeypatch 掉核心计算（`test_e2e_refactor.py:86`），属"伪 e2e"。

### 3.3 覆盖缺口（结构性）

- **DAO 层 8 个模块全部零测试**（tests 目录无一处 `from app.dao` import）——多租户过滤逻辑零保护，与 §1.2 的 P2 风险叠加。
- orchestrator 19 个模块中 **12 个零测试**：`runner.py`、`react_loop.py`、`result_aggregator.py`、`stage_runners.py`、`stage_planners.py`、`stage_reducers.py`、`nodes/arbitrate.py`、`nodes/clarify.py` 等——恰好是最巨型的模块最没测试。
- auth 覆盖良好（100+ 用例），是正面样板。

---

## 4. RAG / 知识库 / 文档理解：行业方案综述 + 项目现状

### 4.1 文件上传链路的常见做法（行业基准）

成熟产品的上传链路通常分四层：

1. **接入层**：multipart 上传（支持拖拽/文件夹/批量），前端校验类型+大小，分片/断点续传（大文件），病毒扫描（可选）。
2. **存储层**：原文落对象存储（S3/OSS/MinIO）或至少落盘，DB 只存元数据+指针；**原文必须可重建索引**。
3. **解析层**：按格式路由解析器——PDF（pypdf/pdfplumber/PyMuPDF，扫描件走 OCR）、DOCX（python-docx）、表格（保留结构为 markdown 表）、图片（OCR/多模态描述）、代码（按语言走 tree-sitter）、网页（readability 抽取正文）。`unstructured` / `markitdown` 是常见的统一入口。
4. **索引层**：解析 → 切分 → embedding → 向量库 + BM25 索引双写；异步任务队列（解析慢，不能阻塞上传响应）。

临时对话附件与持久知识库的区别主要在**生命周期与作用域**：临时附件挂在会话/会议作用域、会后过期清理；持久 KB 有独立管理界面、可复用、有权限边界。检索路由上通常临时附件优先（时效性强）再融合 KB 结果。

### 4.2 常见切分方案对比

| 方案 | 原理 | 优点 | 缺点 | 适用 |
|------|------|------|------|------|
| 固定长度 + overlap | 按字符/token 滑窗 | 简单稳定 | 切断语义单元 | 兜底/无结构文本 |
| 递归切分（RecursiveCharacterTextSplitter） | 按分隔符优先级递归降级（段落→句→词） | 通用、保语义边界 | 不懂文档结构 | 通用文本 |
| 结构感知（Markdown/HTML） | 按标题层级/标签切块，携带层级路径 | 块语义完整、元数据丰富 | 需防围栏内误匹配 | 文档/笔记 |
| **代码 AST 切分（tree-sitter）** | 按语法节点（函数/类/模块）切，`decorated_definition` 节点**天然把装饰器和函数绑在一起** | 代码语义完整 | 需逐语言配 grammar | 代码库 RAG |
| 语义切分（semantic chunking） | 按 embedding 相似度拐点切 | 主题内聚 | 慢、阈值难调 | 长叙述文 |
| 命题/句子级 + 上下文扩展 | 切小块检索、命中后向邻居扩展（类似项目的 neighbor_context） | 精度高 | 需扩展机制配合 | QA 场景 |
| Late Chunking | 先对全文过 long-context embedding 再切，块向量携带全文上下文 | 消歧强 | 依赖长上下文模型 | 高价值文档 |

**装饰器问题的标准答案**：AST 切分本身**不会**把装饰器和函数切开——tree-sitter 中装饰器是 `decorated_definition` 节点的子节点，取节点区间时天然包含。会切开的是两类情况：(1) 用"按行/按固定格式"的土法切分；(2) 像本项目这样**用不感知代码围栏的正则切 Markdown**，导致 md 内嵌代码块里的 `# 注释` 行被当成标题，把装饰器和函数拆散。

### 4.3 项目切分实现评估（含装饰器问题的明确答复）

项目唯一切分器 `backend/app/rag/chunker.py`（143 行）：

```python
_HEADING_RE = re.compile(r"^(#{1,2})\s+(.*)$", re.MULTILINE)
```

**明确结论：项目中不存在任何 AST 切分器**（全仓库 `import ast` 仅用于 `produce.py:1423` 校验 LLM 生成代码语法）。用户记忆中的"早期用 AST/固定格式切分导致装饰器与函数分离"在当前代码库里**已不存在对应实现**——但存在一个**机制不同、效果等价的真实缺陷**：

- **代码围栏不感知（实证 P1 缺陷）**：`_HEADING_RE` 全文 MULTILINE 匹配，不排除 ```` ``` ```` 围栏内的行。md 文档内嵌 Python 代码中的 `# 初始化配置`、C 代码 `#include <stdio.h>` 都会匹配 `^#{1,2}\s+` 被当成标题切开。**若装饰器与 `def` 之间隔一行 `# 注释`，装饰器就和函数体进了两个 chunk**——用户担心的问题真实存在，根因是围栏不感知而非 AST。
- 只认 `#`/`##`，`###` 以下不切；层级仅记 metadata，不形成层级路径。
- **无大小控制**：一个 `##` 章节 10 字或 10 万字都是一个 chunk，无 max_size、无 overlap、无小块合并；超长 chunk 在 embedding 时被模型静默截断。
- 缓解：chunk 带 prev/next 邻居链，检索时向前拼 1 块（截断 600 字符，`retriever.py:65-71`），部分弥补但不充分。

### 4.4 图谱关系类 RAG 综述（行业）

| 方案 | 核心机制 | 检索方式 | 成本 | 适用 |
|------|----------|----------|------|------|
| **Microsoft GraphRAG** | LLM 抽取实体+关系建图 → Leiden 社区检测 → 社区分层摘要 | local search（实体邻域）/ global search（社区摘要 map-reduce） | 建索引极贵（全文多轮 LLM） | 跨文档综合问答、"全局主题是什么"类查询 |
| **LightRAG** | 实体关系图 + 关键词双层检索（low-level 具体实体 / high-level 抽象主题），向量+图混合 |  dual-level 检索 | 比 GraphRAG 轻一个量级 | 大多数场景的高性价比选择 |
| **HippoRAG** | 模拟海马体：OpenIE 三元组建图 + Personalized PageRank 检索 | 图游走关联 | 中 | 多跳推理 |
| **三元组 + 向量混合（DIY）** | 实体关系抽三元组存图库（Neo4j/Memgraph/甚至 PG 表），检索时向量召回 + 图扩展 | 混合 | 可控 | 团队自研起步 |
| 结构化 RAG（不进图库） | 抽取实体只做元数据过滤/别名归一 | 过滤 | 低 | 领域词表明确的场景 |

对 Conclave 的定位建议：**不要直接上 Microsoft GraphRAG**（索引成本与会议场景不匹配），优先 LightRAG 式的"向量+实体关键词双层"或直接 DIY 三元组+图扩展，实体抽取复用现有 LLM 通道（温度 0.0，符合 ADR 规范）。

### 4.5 项目 RAG 现状全景（实证）

**上传链路**（`backend/app/routers/documents.py`）：
- 仅支持 `.md/.markdown/.txt`，10MB 上限，UTF-8 失败回退 GBK；文件名防路径穿越。
- **原文不落盘**：只存内存字典 `store._raw_texts`；chunk 向量进 Qdrant 或内存；元数据（filename/hash/chunk_count）进 PG。**进程重启后原文与内存索引全丢，且无重建机制**。
- **前端完全未接上传 API**：`frontend/src` 全局搜不到 `/documents`、`FormData`；workspace 页的上传是 `file.text()` 读文本 POST JSON 的假上传（二进制会损坏、无 accept 限制、无大小校验、无进度）；`mock-data.ts:1574` 宣称支持 pdf/docx 纯属 mock。**真实上传只被评测脚本使用**——这是"文档理解是大问题"的最直接根因：用户根本传不上来。

**解析能力**：`requirements.txt` 无 pypdf/pdfplumber/python-docx/unstructured/markitdown。**零解析，直接 decode 文本**。

**检索**（`backend/app/rag/store.py`、`retriever.py`）——这部分是亮点：
- SiliconFlow bge-m3 embedding（1024 维，租户级可配），无 key 降级 Stub。
- 混合检索：向量 + jieba 关键词，RRF(k=60) 融合——但**关键词是简化 TF（IDF 硬编码 1.0，非真 BM25）**；Qdrant 模式下关键词召回只遍历内存缓存，重启即失效。
- `retrieve_for_conflict` 有 LLM 查询改写 2 路 + HyDE + 多路并发召回 + `SiliconFlowReranker`（失败回退 KeywordReranker）——检索管线相当完整。
- **缺陷**：Qdrant collection 全局共享（`conclave_chunks`），检索过滤只见 `tenant_id`，**未见 meeting_id 过滤**——同租户跨会议串扰风险（待确认，建议优先核实）。

**GraphRAG**：不存在。`Chunk.claims/relations` 是空占位（chunker.py:19-20，注释"预留，迭代三填充"）。

**MCP**：后端零集成（全仓库 Python 代码搜 `mcp` 无命中）。`docker-compose.obsidian-mcp.yml` 是开发者个人 Obsidian 记忆服务，与 Conclave 运行时无调用关系。

**上下文注入**（`evidence_helpers.py:100-122`）：top_k=5 → 注入防护 → 每条 quote 截断 400 字符 + 邻居扩展 → 注入 EVIDENCE_CHECK prompt；全局 32K token 截断兜底（头 40% + 尾 20%）。**无 rerank 分数阈值过滤、无按 token 的证据预算分配**。

### 4.6 缺口清单（现状 vs 行业基准）

1. 无 PDF/DOCX/图片/代码解析；前端上传 UI 未接真实 API；mock 宣称的格式全部不支持。
2. 切分器围栏不感知（装饰器可被注释行拆散）、无大小上限、无 overlap、无小块合并、`###` 以下不切。
3. 原文不落盘、无索引重建机制；临时附件与持久 KB 无区分（全是 per-meeting 内存）。
4. 关键词路非真 BM25；Qdrant 模式关键词召回重启失效。
5. Qdrant 共享 collection 缺 meeting_id 过滤（跨会议串扰待核实）。
6. 无 GraphRAG/实体关系抽取（仅占位）；MCP 完全未接入产品。
7. 注入无相关性阈值、无 token 预算分配。

---

## 5. 需求分析与可执行建设方案

按 P0（止血）→ P1（固本）→ P2（增强）排布。每项含改动点与验收标准。

### 5.1 P0：让"上传文档并被理解"这条链路真正可用

**R1 文档解析与上传链路重建**
- 引入解析层：PDF（PyMuPDF，比 pypdf 快且稳）+ DOCX（python-docx）+ 图片 OCR（可选，二期），统一产出 markdown 中间表示。可选 `markitdown` 做统一入口，但注意依赖体积（§5.3 依赖纪律：先确认 requirements 无替代、license 兼容）。
- 原文落盘（`docker/` 挂载卷或 OSS），PG 存 `storage_path`；上传接口改异步：接收 → 存原文 → 入解析任务队列 → 完成回调更新状态。
- 前端：`/board` 或会议页加真实上传组件（multipart + accept 白名单 + 大小校验 + 进度条 + 解析状态轮询），删除 `file.text()` 假上传和 mock 格式宣称。
- 验收：上传一份含代码块和表格的 30 页 PDF，能在会议质证阶段被引用且引用内容语义完整。

**R2 切分器重写（修复装饰器/代码围栏问题）**
- 改为**围栏感知的状态机切分**：逐行扫描，进入/退出 ```` ``` ```` 围栏时切换状态，围栏内任何行不参与标题匹配——这是修复装饰器分离问题的最小改动。
- 层级扩展：支持 `#`–`####` 全层级，chunk metadata 携带完整标题路径（`["章", "节", "小节"]`）。
- 大小控制：max_chunk_size ≈ 1200 字符（bge-m3 友好区间），超长在段落边界二次切分 + 10% overlap；< 200 字符小块与后继合并（复用 `tools/playwright/chunk_js.py` 的 MIN_CHARS 思路）。
- 代码文件直传（.py/.ts 等）：走 tree-sitter AST 切分，按 `decorated_definition`/`function_definition`/`class_definition` 节点切——**装饰器与函数天然同块**，同时回应了用户对 AST 切分的顾虑（问题不在 AST，在于土法切分）。
- 验收（对照测试）：构造"装饰器 + 注释行 + 函数"的 md 内嵌代码块和裸 .py 文件各一份，断言装饰器与函数体同 chunk；构造 5 万字单章节文档，断言无 chunk 超上限。

**R3 持久化与隔离修复**
- 核实并修复 Qdrant 检索过滤缺 meeting_id 的问题（若确认串扰则按 P8 多租户 checklist 同等级处理）。
- 向量与原文持久化后提供重建入口（`POST /documents/{id}/reindex`）。
- 验收：重启后端后历史会议文档仍可检索；跨会议检索不串。

### 5.2 P0/P1：前端核心流程止血

**R4 会议创建流程补全**：创建面板接入团队/Agent/deliverable_type 选择（mutation 参数已存在，纯前端工作）。
**R5 消息可靠性**：启用 `useMeetingMessages` 做 WS 断线时的 REST 兜底；发送失败 toast + 本地重发队列。
**R6 信息架构收敛**：合并 `/board` 与 `/explore` 为一个入口（保留 board 的创建输入框 + explore 的列表）；删除或落地 `/landing` 与"分支探索"按钮——**要么实现要么下线，不留假交互**。
**R7 观感修复**：board 加运行中轮询；页面级 ErrorBoundary；`takeover-panel` 去硬编码深色；mock-data 从生产路径剥离（demo 模式集中到单一切换点）。
- 验收：WS 断开后历史消息可见；发送失败有提示；全站无"功能开发中"按钮；浅色主题无突兀深色块。

### 5.3 P1：架构与测试固本

**R8 编排器拆分**：`Runner` 拆为状态机 / 质量评估 / 缓存三个协作类；`produce_node` 按阶段拆函数（目标单函数 < 100 行）；全局状态评估迁移 Redis（为横向扩容铺路，可先出 ADR）。
**R9 DDL 统一**：收敛到 Alembic 单轨，`db_init.py` 补丁迁移转写为 0006+ 迁移文件，启动只跑 `alembic upgrade head`（先开 ADR，符合 §5.1 大改纪律）。
**R10 测试补缺**：DAO 层每个模块补测试（重点：tenant_filter 隔离用例——构造两租户同资源断言互不可见）；orchestrator 零测试模块按 `runner > stage_runners > arbitrate` 优先级补；修复 `test_stats.py` 条件断言（异常必须 fail）；8 个无断言测试补断言或删除；三个纯快乐路径文件各补至少 1 个负向用例。
**R11 前端测试**：message-stream、ws.ts 重连、ag-ui 适配器补 Vitest；Playwright 加一条"创建会议→讨论→看报告"冒烟 E2E。
- 验收：DAO/orchestrator 零测试模块清零；`docker compose -f docker-compose.test.yml up --exit-code-from backend-test` 全绿；前端测试文件 ≥ 20。

### 5.4 P1/P2：检索质量与知识库能力

**R12 真 BM25**：关键词路换 rank_bm25 或自建带全局 IDF 的 BM25（jieba 保留），Qdrant 模式的关键词索引持久化（随原文落盘重建）。
**R13 注入预算**：rerank 分数阈值过滤（< 阈值丢弃）+ 按 token 分配证据预算（替代 400 字符硬截断），保留注入防护。
**R14 持久知识库 + 临时附件双轨**：新增全局 KB 作用域（跨会议复用、独立管理页），临时附件 per-meeting 保留会后清理；检索路由：临时附件优先 → KB 融合 → RRF。
**R15 MCP 知识库接入**：后端实现 MCP client，支持挂载外部知识库（首个目标：用户的 Obsidian vault，复用现有 `docker-compose.obsidian-mcp.yml` 服务，把"开发者个人记忆"升级为"产品能力"）；MCP 资源统一走 RAG 索引管线。
**R16 轻量 GraphRAG**：填充 `Chunk.claims/relations` 占位——实体+关系抽取（LLM 温度 0.0，符合 ADR）→ 三元组存 PG（不上 Neo4j，控制依赖）→ 检索时向量召回 + 一跳图扩展（LightRAG 式 dual-level）。先出 ADR 再动手。
- 验收 R14-16：同一文档二次会议可复用；挂载 Obsidian vault 后会议能引用其中笔记；问"X 与 Y 有什么关系"类问题时图扩展路径可命中。

### 5.5 P2：卫生与体验增强

- **R17 仓库大扫除**：根目录 20+ 审计产物目录归档进 `docs/audits/`（或移出仓库）；`archive/` 停止 git 跟踪；compose 文件用 profiles 归并；`docs/audits/` 219 个文件建索引页。
- **R18 前端拆分与响应式**：9 个巨型页面按 feature 内子组件拆分；核心页（会议详情、reports）补 `md:` 断点；svg-icons 换 lucide-react。
- **R19 类型契约收敛**：消灭 `messageCount ?? message_count` 双重字段，后端响应统一 camelCase（或前端 normalize 单点处理）。

### 5.6 优先级路线图

```
第 1-2 周（止血）   R1 解析上传链路 → R2 切分器重写 → R4/R5/R6 前端止血
第 3-4 周（固本）   R3 持久化隔离 → R10 测试补缺（DAO/orchestrator）→ R7 观感
第 5-8 周（增强）   R8 编排器拆分(ADR) → R9 Alembic 单轨(ADR) → R12/R13 检索质量
第 9-12 周（能力）  R14 双轨 KB → R15 MCP 接入 → R16 轻量 GraphRAG(ADR)
持续               R11 前端测试、R17-R19 卫生与体验
```

---

## 6. 风险与开放问题

1. **Qdrant 跨会议串扰（R3 前置）**：尚未 100% 确认过滤缺失，建议作为第一项核实任务——若属实等同 P8 级隔离事故。
2. **引入解析/tree-sitter 依赖**需过 §5.3 依赖审查（维护活跃度、license、镜像源可用性）。
3. **GraphRAG 索引成本**：实体抽取是全文档 LLM 调用，需评估 token 成本与会议场景的性价比，故排 P2 并要求先 ADR。
4. **编排器状态迁 Redis** 影响面大，建议在 R8 拆分完成、测试补齐（R10）之后再动，顺序不可颠倒。
5. 本报告每条结论均附代码证据；执行阶段对任何"外部评审式"新结论仍须先 grep 核验再认领（P22 纪律）。
