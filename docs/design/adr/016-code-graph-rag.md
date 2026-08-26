# ADR-016: 代码知识图谱 RAG（Code Graph RAG）

## 状态

Accepted — 2026-08-24

## 背景

### 问题陈述

当前 RAG 只面向**纯文本**（Markdown / txt），无法理解**代码库**。用户的实际诉求是把一个代码仓库（上传文件夹，或粘贴 GitLab 链接）变成"可检索、可理解依赖与调用关系"的知识，而不是简单地做"文本切碎 + 向量 top-k"。具体存在五个断层：

1. **入口断层**：`routers/documents.py` 的上传白名单 `_ALLOWED_EXTENSIONS` 只有 `.md /.markdown /.txt`，注释明确"pdf/docx 等解析为后续里程碑"；既没有文件夹批量导入，也没有 Git 链接导入。
2. **解析断层**：`rag/chunker.py` 只有 `chunk_markdown` 一个入口，不懂任何编程语言的语法结构（函数/类/import）。
3. **关系断层**：检索只靠"查询与 chunk 的语义相似度（余弦）+ 关键词"——这无法回答"这个函数被谁调用""改这个模块会影响谁""文档里提到的组件 A 与代码符号 B 是什么关系"这类**结构/关系查询**。
4. **多跳断层**：用户举例的"张三汇报给李四 / 张三与王二平级 / 王二汇报给张三"这类**跨 chunk 的知识关联与矛盾检测**，纯向量检索天然够不到。
5. **设计原则欠账**：`design-principles.md` 原则 1 第 ② 条"图而非链"早已要求"chunk 间关系建模为图（chunk graph），而非线性 prev/next"，但"现阶段取舍速查"表把 `Chunk Graph` 标记为"暂缓"。本 ADR 正是把这条欠账正式立项。

### 代码核验（现有基础设施，全部 grep 核实）

```bash
# 1. 已有运行时代码浏览能力（不可与"知识入库"混为一谈）
ls backend/app/tools/workspace_tools.py   # fs.list / fs.read / fs.write / shell.exec / python.run
ls backend/app/routers/workspace.py       # /workspace/files 列表/读写/删除、/exec、/run

# 2. 已有 Docker 沙箱网络分级（git clone 需 L3 全联网）
grep -n "L1\|L2\|L3\|network" backend/app/sandbox.py          # L1 无网络 / L2 pypi 白名单 / L3 全联网
grep -n "L2 白名单" backend/app/tools/README.md

# 3. 已有文本 RAG 存储（embedding + reranker + 内存/Qdrant 双存储）
grep -n "class.*Embedding\|class.*Reranker\|RRF\|InMemoryVectorStore\|QdrantVectorStore" backend/app/rag/store.py

# 4. chunker 预留了图 RAG 字段但从未填充
grep -n "claims\|relations\|图 RAG\|预留" backend/app/rag/chunker.py

# 5. 无 tree-sitter / AST / 依赖解析 / 图数据库依赖
grep -rn "tree_sitter\|tree-sitter\|call_graph\|submodule" backend/app/         # 零实现（唯一命中的"gitlab"是 domain_registry.py 的信源文本别名）
grep -n "tree-sitter\|networkx\|neo4j\|rdflib" backend/requirements.txt         # 零结果
```

### 现有能力与缺口

| 能力 | 状态 | 位置 |
|------|------|------|
| 运行时代码浏览（list/read） | ✅ 已有 | `tools/workspace_tools.py`（`fs.list` / `fs.read`） |
| 命令执行（可 `git clone`） | ✅ 已有 | `workspace_tools.py`（`shell.exec` + sandbox） |
| 文本 chunk RAG | ✅ 已有 | `rag/chunker.py`（仅 `chunk_markdown`）+ `rag/store.py` |
| Git 链接导入端点（含 submodule） | ❌ 缺失 | 无专门端点，无 `--recurse-submodules`、无 SSH/HTTPS 认证管理 |
| 语言感知解析（AST） | ❌ 缺失 | 无 tree-sitter |
| 符号/调用/依赖关系图 | ❌ 缺失 | 无图构建、无图存储 |
| 图多跳检索 | ❌ 缺失 | 无沿关系边遍历 |

## 决策

### 总体架构：五阶段流水线，增量落在现有 RAG + workspace 之上，不另起炉灶

```
① 摄入 Ingest   ② 解析 Parse      ③ 构图 Graph        ④ 入库 Store            ⑤ 检索 Retrieve
git 链接(递归)    tree-sitter        File/Symbol/Doc      chunk 向量 → Qdrant      向量入口命中节点
submodule + zip  ──► AST 抽取符号 ──► + IMPORTS/CALLS  ──► nodes/edges → PG     ──► 沿关系边 N 跳扩展
(落 workspace)     (定义区间/docstr)  /INHERITS/DEFINES    (WITH RECURSIVE 多跳)   → 交 reranker 融合
```

各阶段职责与落地位置：

1. **摄入 Ingest**：两类入口——Git URL（`git clone --recurse-submodules`，强制递归 submodule）与 zip 文件夹上传，统一解包到 `workspace/{meeting_id}/` 目录。复用 `routers/workspace.py` 的 `_resolve_path` 防穿越、`meeting_id` 隔离。**git clone 在 backend 侧以受控子进程执行**（非 LLM shell，`asyncio.create_subprocess_exec` + 参数列表无 shell 注入），而非走 sandbox——因为沙箱镜像 `python:3.12-slim` 不含 git 且 `--read-only`，`--network none`。新增 `POST /meetings/{meeting_id}/code/ingest` 端点（见 `app/routers/code.py`）。
2. **解析 Parse**：用 **tree-sitter** 做多语言 AST 解析，抽取符号（函数/类/方法）+ 定义行区间 + docstring。首批语言 **Python + TypeScript/JavaScript**（对应项目自身技术栈，见 AGENTS.md 技术栈速查）。代码分块天然满足原则 1 第 ① 条"保真切块"——函数/类定义区间就是结构边界，`char_start/char_end` 就是来源偏移。
3. **构图 Graph**：三类节点 + 五类边，把"层级关系 = 依赖 + 调用"落成图：
   - 节点：`File`（文件）、`Symbol`（函数/类/方法）、`Doc`（README/设计文档/注释）
   - 边：`IMPORTS`（文件→模块）、`CALLS`（符号→符号）、`INHERITS`（类→类）、`DEFINES`（文件→符号）、`DEPENDS_ON`（package 依赖，来自 requirements/package.json/go.mod）、`REFERENCES`（Doc→File/Symbol，把"文档里提到的组件"连起来）
4. **入库 Store**：代码 chunk 的向量走 Qdrant（复用 `rag/store.py` 的 embedding/reranker/multi-tenant 隔离），图 `nodes/edges` 走 PostgreSQL（`WITH RECURSIVE` 递归 CTE 做多跳）。**不引入图数据库**。
5. **检索 Retrieve**：向量召回定位入口节点 → 沿关系边做 N 跳扩展（`IMPORTS/CALLS/INHERITS`）→ 合并后交 reranker。**向量管"语义入口"，图管"结构扩展"，两者级联非替代**。

### 关键决策点

| # | 决策 | 理由 | 备选（否决原因） |
|---|------|------|------|
| D1 | 解析用 **tree-sitter** | 多语言、容错（代码不完整也能解析）、可增量；是代码理解事实标准 | Python 内置 `ast`：只懂 Python 且要求可编译，无法覆盖 TS/JS |
| D2 | 图存储用 **PG nodes/edges + 递归 CTE + 内存邻接表缓存** | 复用现有 PG，规模内足够；符合"禁止未授权依赖"（AGENTS.md 5.3） | Neo4j/NebulaGraph：新增重型依赖 + 运维成本，规模未到 |
| D3 | 符号用**限定名** `file:class::method` | 跨语言/跨文件同名符号极常见，裸名会导致调用边错连（图最常见的坑） | 裸函数名：必错连 |
| D4 | 图检索是向量的**级联补充** | 余弦只负责"找到入口"，关系边才回答结构问题；两者结果 rerank 融合 | 纯图检索替代向量：丢失语义召回能力 |
| D5 | 打通 `chunker.py` 预留的 `claims`/`relations` 字段 | 关系抽取结果填 `relations`，声明按要求填 `claims`，兑现原则 1 第 ③ 条"多维提炼" | 新造字段：重复且破坏既有数据模型 |

### 与设计原则的对齐

- **原则 1 ② 图而非链**：本 ADR 把"暂缓的 Chunk Graph"落地为代码图——代码的依赖/调用关系正是最天然、最可静态确定的 chunk graph。
- **原则 7 反架构沉迷**：分阶段推进，Phase A 只做"导入 + 文件树浏览"的薄接口，图能力作为插件逐项引入，不做一次性大而全。
- **原则 8 演进式架构**：先跑通"git clone → 浏览 → 文本检索"最小闭环，再叠加 AST 解析与图检索。
- **原则 11 感知层工具端口**：Git 导入是"工具"，其产物作为证据注入 `evidence_check`，标注 `[code:file:class::method]`，与 RAG 证据一起走仲裁，不直接进结论链。

## 为什么不在现有 RAG 之外另起一个独立服务

1. 代码库本质仍是"文档"，只是需要语言感知分块 + 关系边——这是 RAG 的能力升级，不是新系统。
2. 复用 `rag/store.py` 已实现的 embedding、reranker、multi-tenant 隔离、内存/Qdrant 双存储，避免在"文本 RAG"与"代码 RAG"两套存储之间割裂数据。
3. 复用 `workspace` 的路径隔离、防穿越、会议间文件隔离，避免重造安全边界。
4. 复用 sandbox 的 L1/L2/L3 网络分级，git clone 的安全执行环境现成可用。

## 实施计划

### Phase A：代码摄入（1-2 天）

1. 新增 `POST /meetings/{id}/code/ingest`：接受 Git URL 或 zip 上传；Git 走 `git clone --recurse-submodules --depth 1`（backend 受控子进程，`GIT_TERMINAL_PROMPT=0` 防挂起），zip 解压到 workspace 会议目录。
2. 增加 git 安全护栏：仓库大小上限、clone 超时、SSH/HTTPS 认证（token 注入）、submodule 私有仓库 credential 处理、拒绝越界路径。
3. 复用 `fs.list`/`fs.read` 让 Agent 立即可浏览导入的代码库。
4. 产物：用户能导入一个 GitLab 仓库（含 submodule）并在会议中浏览代码。

### Phase B：解析与构图（3-5 天）

1. 引入 `tree-sitter` + Python/TypeScript/JavaScript grammar（本项目唯一新增依赖，需经本 ADR 批准）。
2. 实现 `rag/code_chunker.py`：语言感知分块（符号定义区间 + docstring + 来源偏移）。
3. 实现 `rag/code_graph.py`：抽取 File/Symbol/Doc 节点与 IMPORTS/CALLS/INHERITS/DEFINES/DEPENDS_ON 边，落 PG `nodes`/`edges` 表；关系填 `chunker.Chunk.relations`，声明填 `claims`。
4. 产物：导入的代码库被结构化为可查询的图 + 向量。

### Phase C：图检索与评测（3-5 天）

1. `retriever` 增加"向量入口 + N 跳图扩展"路径，扩展结果交 reranker。
2. 支持结构查询：符号的反向调用方、模块影响面（依赖子图）、文档-符号引用。
3. 建评测基准：`recall@k` + 结构查询正确率（如"被 3 处调用，召回应包含这 3 处"）。
4. 产物：RAG 能回答"谁调用它 / 改它影响谁 / 文档提到哪个符号"。

## 约束与风险

### Git 安全风险

- `git clone` 在 **backend 受控子进程**执行（非 LLM 任意 shell），参数列表拼装无 shell 注入，协议仅 http/https，`GIT_TERMINAL_PROMPT=0` 禁止交互式凭据提示，日志留痕且 token 不落盘。
- 私有仓库与私有 submodule 需要 credential：支持 HTTPS token / SSH deploy key 注入，密钥不落盘明文。
- 大小与超时上限，防止巨型仓库拖垮工作区。

### tree-sitter 语言覆盖不足

- 首批 Python + TS/JS；Go/Rust/Java 等按需扩展 grammar。跨语言运行期绑定（如 Python 调 JS）不做静态解析，属"不做的事"。

### 大仓库解析性能

- 全量 AST 解析 + 构图耗时长；需支持**增量索引**（仅解析变更文件），Phase C 引入。

### 同名符号消歧

- 限定名 `file:class::method` 缓解大部分错连；跨文件重定向、别名 import 的消歧在 Phase C 用 LLM 二次校验。

### PG 递归 CTE 性能

- 极深调用链（>50 层）与超大依赖图时 `WITH RECURSIVE` 可能变慢；规模验证后再评估是否升迁图数据库（另开 ADR）。

## 不做的事

- 不引入 Neo4j/NebulaGraph 等图数据库（Phase C 验证规模后另议）。
- 不做跨语言运行期语义绑定（静态 imports/calls 之外的动态调用）。
- 不做代码自动修复/重构/生成，本 ADR 只管"理解与检索"。
- 不做仓库持续同步（git webhook 增量拉取），Phase C 之后另开 ADR。
- 不动现有 `chunk_markdown` 的文本分块逻辑，代码分块作为**新增并行入口**，避免破坏已稳定的文本 RAG。

## 实施记录（2026-08-24）

### Phase A 已落地

- `app/routers/code.py`：新增 `POST /{meeting_id}/code/ingest`（`@router.post` 于 `code.py:326`），支持 Git URL（`git clone --recurse-submodules`，`GIT_TERMINAL_PROMPT=0`，size/timeout 上限、token 注入与脱敏、超时清理半成品目录）与 zip 上传（`_safe_extract_zip` 做 zip-slip 防穿越）。
- 仓库名解析 `_parse_repo_name` 用 `urlsplit` 处理认证前缀 / 查询片段 / `.git` 后缀 / 退化 URL（`https://` → 回退 `repo`）；`_sanitize_dir` / `_resolve_dest` 做目录名规范化与越界拒绝。
- 测试：`tests/test_code_ingest.py`（仓库名/目录清洗/token 注入与脱敏/zip-slip/越界）。

### Phase B 已落地

- `app/rag/code_parser.py`：`parse_file`（`code_parser.py:436`）基于 tree-sitter 抽取 Python/TypeScript/JavaScript 的符号、imports、calls、继承（含 TS 泛型基类 `Base<T>` 的 `type_arguments` 过滤），grammar 缺失时 graceful 降级。
- `app/rag/code_graph.py`：`CodeGraph`（`code_graph.py:80`），File/Symbol/Doc 三类节点 + IMPORTS/CALLS/INHERITS/DEFINES/DEPENDS_ON 五类边；限定名 `file::symbol` 消歧，同名符号歧义时跳过而非错连。
- `app/rag/code_chunker.py`：`chunk_repo`（`code_chunker.py:102`）把符号定义区间切成复用 `rag/chunker.Chunk` 的 chunk（docstring 优先、按行排序做 prev/next 邻接、`relations`/`claims` 填充）。
- 依赖：`requirements.txt` 新增 `tree-sitter` + `tree-sitter-python/-javascript/-typescript`。
- 测试：`test_code_parser.py` / `test_code_graph.py` / `test_code_chunker.py`。

### Phase C 已落地

- `app/rag/code_index.py`：`index_repo`（`code_index.py:40`）编排「解析 → 构图 → 切块 → 注册图 → 向量入库」，AST 解析放到 `asyncio.to_thread` 避免阻塞事件循环，索引失败 graceful 降级（不阻断导入）。
- `app/rag/graph_expand.py`：`GraphIndex`（`graph_expand.py:28`）提供 `expand` / `callers` / `dependencies`（BFS N 跳、边类型过滤、环路 visited 去重、种子去重），`structure_query`（`graph_expand.py:162`）回答「谁调用它 / 它依赖谁」；`register_graph` / `get_graph` / `unregister_graph` 注册表按 `meeting_id` 隔离。
- `app/rag/retriever.py`：`retrieve_code`（`retriever.py:221`）实现「向量入口命中种子 → 沿 CALLS/INHERITS N 跳扩展 → 合并交 reranker」，图扩展命中 chunk 携带 `graph_hit`（hop/edge_type/via）供审计；无图索引降级为纯向量，reranker 异常回退初始分排序。
- 测试：`test_code_index.py` / `test_graph_expand.py` / `test_retriever_graph.py`。

### 验证结果

- 上述 7 个测试文件共 **103 个用例全通过**（含降级 / 无图回退 / 环路 / zip-slip / 退化 URL 边界维度）。
- `ruff check` 与 `ruff format --check` 对新增文件全部通过（0 errors / 0 files reformat）。

### 尚未落地（后续迭代）

- 图节点/边 **Persist 到 PostgreSQL**（`nodes`/`edges` 表 + `WITH RECURSIVE` 多跳）——当前图用内存邻接表注册表承载，进程重启即失。这是 D2 决策的下半程。
- 增量索引（仅解析变更文件）、更多语言 grammar（Go/Rust/Java）、跨文件 import 别名 / 重定向的 LLM 二次消歧。
- Phase C.3 评测基准（`recall@k` + 结构查询正确率）尚未搭建。