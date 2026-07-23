[返回上级文档](../../README.md)

# RAG 检索增强生成模块

## 1. 模块目的

本模块实现 Conclave 的**检索增强生成（Retrieval-Augmented Generation）**子系统，为会议仲裁流程提供文档知识检索能力。核心职责：

- **文档分块**：将上传的 Markdown 文档按标题层级切分为语义完整的 Chunk
- **多路召回**：结合向量语义检索、关键词检索、Multi-Query 扩展、HyDE 假设文档嵌入，最大化召回率
- **重排序**：通过 Reranker 对召回候选按相关性重新排序，提升精度
- **混合检索融合**：使用 RRF（Reciprocal Rank Fusion）融合向量与关键词两路结果
- **惰性上下文展开**：默认返回摘要，按需展开邻居 Chunk 或字符级上下文，节省 Prompt Token

---

## 2. 架构总览

```
                          ┌─────────────────────────────────────────┐
                          │            Orchestrator 层              │
                          │  evidence_helpers.py / manager.py       │
                          │  通过工具函数调用 retriever 入口          │
                          └──────────────┬──────────────────────────┘
                                         │ 调用
                                         ▼
┌────────────────────────────────────────────────────────────────────────────┐
│                          retriever.py (检索入口)                           │
│  ┌──────────────┐   ┌──────────────┐   ┌───────────────────────────────┐  │
│  │ retrieve()   │   │retrieve_for_ │   │ 多路并发召回 + 合并去重 + Rerank │  │
│  │  (基础检索)   │   │conflict()    │   │ _safe_search 异常隔离          │  │
│  └──────┬───────┘   │(冲突证据检索) │   └──────────────┬────────────────┘  │
│         │           └──────┬───────┘                  │                   │
│         │                  │ 并行                     │                   │
│         │           ┌──────┴───────┐                  │                   │
│         │           ▼              ▼                  │                   │
│         │  ┌────────────┐  ┌──────────────┐           │                   │
│         │  │query_      │  │  hyde.py     │           │                   │
│         │  │rewriter.py │  │ (假设文档)    │           │                   │
│         │  │ Multi-Query│  │ HyDE 检索    │           │                   │
│         │  └─────┬──────┘  └──────┬───────┘           │                   │
│         │        │                │                   │                   │
│         └────────┴────────┬───────┴───────────────────┘                   │
│                           │                                               │
│                           ▼                                               │
│                 ┌─────────────────────┐                                   │
│                 │    store.py         │                                   │
│                 │  VectorStore (接口)  │                                   │
│                 └──────┬──────────────┘                                   │
│                        │                                                  │
│              ┌─────────┴──────────┐                                       │
│              ▼                    ▼                                       │
│     ┌────────────────┐   ┌─────────────────┐                             │
│     │InMemoryVector  │   │QdrantVectorStore│                             │
│     │Store (内存)    │◄──│ (适配器,生产环境) │                             │
│     │ 向量+关键词     │   │ 委托 Qdrant 检索 │                             │
│     │ RRF 融合       │   │ 失败回退内存     │                             │
│     └───────┬────────┘   └────────┬────────┘                             │
│             │                     │                                      │
│             ▼                     ▼                                      │
│     ┌─────────────────────────────────────┐                             │
│     │         Embedding / Reranker        │                             │
│     │  SiliconFlow (bge-m3 / bge-reranker)│  ← 生产环境                  │
│     │  StubEmbedding / KeywordReranker    │  ← 开发/无 Key 时 fallback   │
│     └─────────────────────────────────────┘                             │
│                                                                          │
│  ┌──────────────┐  ┌──────────────┐                                     │
│  │ chunker.py   │  │ tokenize.py  │                                     │
│  │ Markdown分块 │  │ 中英混合分词  │                                     │
│  └──────────────┘  └──────────────┘                                     │
└────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. 数据处理流水线

```
文档上传
   │
   ▼
[chunker.py] Markdown 按 # / ## 标题切分 → Chunk 列表
   │         每个 Chunk 记录 doc_id / section / char_start / char_end
   │         建立 prev_id / next_id 邻居链
   ▼
[store.add_chunks] 批量 embed → 写入向量库（内存/Qdrant）
   │
   ▼
                              ┌─────────────────────────────────┐
查询请求 ──► [query_rewriter]  │ 查询改写 + HyDE 并行执行          │
   │         LLM 生成 2 个改写  │  query_rewriter: 原始+2改写=3路  │
   │         查询 + 原始查询    │  hyde: LLM 生成假设文档 → 搜索    │
   │                          └──────────────┬──────────────────┘
   │                                         │
   ▼                                         ▼
[多路并发召回 _safe_search]  ◄───────────────┘
   │  每路独立异常隔离，单路失败不影响整体
   │  每路取 top_k * 2 候选
   ▼
[合并去重] 按 chunk_id 去重，保留最高分
   │
   ▼
[Reranker 重排序] bge-reranker-v2-m3 精排，失败回退关键词排序
   │
   ▼
[邻居链上下文扩展] 附带前 N 个 Chunk 文本，提供完整证据上下文
   │
   ▼
返回 top_k 个证据 Chunk（含摘要 + 可展开标记）
```

---

## 4. 分块策略（chunker.py）

**分块方式**：Markdown 标题感知分块

- 以 `#`（一级标题）和 `##`（二级标题）作为切分边界
- 标题前的引导文本作为首个无标题块（section=`intro`）
- 无标题的文档整体作为一个块
- 每个块记录在原文中的字符区间 `[char_start, char_end)`，支持惰性展开

**邻居链机制**：

- 同一文档的 Chunk 通过 `prev_id` / `next_id` 双向链表串联
- 检索时可通过 `get_neighbor_context()` 获取相邻 Chunk 文本，构建完整上下文窗口
- 相比固定字符窗口，邻居链按标题段落粒度展开，语义更完整

**Chunk 数据结构**预留了图 RAG 扩展字段：

| 字段 | 用途 |
|------|------|
| `metadata` | 标题层级、文档来源、创建时间等 |
| `claims` | 从 Chunk 提取的声明（预留） |
| `relations` | 与其他 Chunk 的关系（预留） |

---

## 5. Embedding 模型（store.py）

### 向量嵌入

| 实现类 | 模型 | 维度 | 场景 |
|--------|------|------|------|
| `SiliconFlowEmbedding` | **bge-m3**（多语言） | 1024 | 生产环境，通过硅基流动 OpenAI 兼容 API 调用 |
| `StubEmbedding` | MD5 确定性伪向量 | 可配置（默认 1024） | 开发/测试环境，无需外部 API |

- 批量嵌入：每批最多 32 条，分批调用
- 租户级覆盖：支持通过 `resolve_embed_config()` 按租户切换 API Key / Base URL / 模型
- 循环感知：`httpx.AsyncClient` 懒加载，事件循环变化时自动重建，避免跨循环 Future 错误
- 无 API Key 时自动降级到 `StubEmbedding`

### 重排序（Reranker）

| 实现类 | 模型 | 场景 |
|--------|------|------|
| `SiliconFlowReranker` | **bge-reranker-v2-m3** | 生产环境，Jina/Cohere 兼容 `/rerank` API |
| `KeywordReranker` | TF-IDF 简化版关键词匹配 | 开发/无 Key/API 失败时 fallback |

- Reranker 对召回候选精排，返回 `(原始索引, 相关性分数)` 列表
- 任何异常自动回退到 `KeywordReranker`，保证不中断流程

---

## 6. 存储后端（store.py）

### InMemoryVectorStore（开发环境）

- 进程内 `dict` 存储 Chunk + 向量
- 支持混合检索：向量余弦相似度 + 关键词 TF-IDF → RRF 融合
- 原文缓存 `_raw_texts` 支持按字符区间惰性展开上下文
- 邻居链 `get_neighbor_context()` 支持按 Chunk 粒度展开

### QdrantVectorStore（生产环境，适配器模式）

- 继承 `InMemoryVectorStore`，保持接口一致
- 向量存储委托 Qdrant（COSINE 距离，Collection 名可通过 `CONCLAVE_QDRANT_COLLECTION` 环境变量配置，默认 `conclave_chunks`）
- 原文缓存和邻居链仍使用内存（Qdrant 存向量 + payload，不存完整原文）
- **Lazy 初始化**：首次 `add_chunks` / `search` 时异步创建 Collection，不阻塞事件循环
- **自动降级**：Qdrant 连接失败时回退到纯内存混合检索

### Store 单例管理

- 按 `meeting_id` 隔离，进程级单例字典 `_stores[meeting_id]`
- `get_store(meeting_id)` 获取指定会议的向量库
- `clear_store(meeting_id)` 清理会议缓存，释放内存
- `_build_store()` 自动选择后端：配置了 `qdrant_url` 则用 Qdrant，否则内存

---

## 7. 检索策略

### 7.1 混合检索（Hybrid Search）

每次 `store.search()` 内部执行两路检索 + RRF 融合：

1. **向量检索**：query embed → 余弦相似度排序 → 取 top_k*2
2. **关键词检索**：jieba 中文分词 + 英文分词 → 简化 TF-IDF 计分 → 取 top_k*2
3. **RRF 融合**：`score = Σ 1/(K + rank)`，K=60，两路排名倒数加权求和

### 7.2 Multi-Query 扩展（query_rewriter.py）

- LLM 将原始查询改写为 **2 个不同角度**的检索查询：
  - 查询 1：提取关键词，使用正式/技术化术语，去除口语化表达
  - 查询 2：同义词替换、换个问法，保持语义不变
- 最终形成 **原始查询 + 2 改写 = 3 路**并发检索
- LLM 调用失败时回退为仅用原始查询
- 输出严格 JSON 格式 `{"queries": ["改写1", "改写2"]}`

### 7.3 HyDE 假设文档嵌入（hyde.py）

**原理**（Gao et al. 2022）：原始 query 与文档在 embedding 空间中存在语义鸿沟，让 LLM 先写一段"假设性答案文档"，用该文档的 embedding 做检索，更接近真实文档的向量分布。

**流程**：
1. LLM 根据 query 生成 200-300 字的技术文档风格段落（temperature=0.1，保证稳定性）
2. 清理 Markdown 标记、前缀等噪音
3. 用假设文档作为 query 调用 `store.search()` 检索
4. 失败时返回空列表，不阻塞主流程

### 7.4 多路召回整合（retrieve_for_conflict）

`retrieve_for_conflict()` 是冲突证据检索的完整 Pipeline：

1. **并行执行**查询改写 + HyDE（`asyncio.gather` 减少延迟）
2. **多路并发召回**：3 路 Multi-Query + 1 路 HyDE = 4 路，每路独立 `_safe_search` 异常隔离
3. **合并去重**：按 `chunk_id` 去重，保留最高分
4. **Reranker 精排**：对合并后的候选池调 Reranker，取 top_k
5. **邻居链扩展**：附带前 1 个 Chunk 摘要，提供证据上下文

### 7.5 中英混合分词（tokenize.py）

针对中文无空格分界的问题，修复了旧版单字切分导致召回率低的缺陷：

- **中文**：优先使用 `jieba` 按词切分（精确模式），jieba 不可用时退化为单字切分
- **英文/数字**：按非字母数字字符切，过滤短词（查询时最小长度 2）
- 覆盖 CJK 统一汉字、日文假名、韩文谚文

---

## 8. 关键文件索引

| 文件 | 职责 | 关键类/函数 |
|------|------|-------------|
| `__init__.py` | 模块入口 | 模块声明 |
| `chunker.py` | Markdown 文档分块 | `Chunk` 数据类、`chunk_markdown()` |
| `store.py` | 向量存储、Embedding、Reranker | `InMemoryVectorStore`、`QdrantVectorStore`、`SiliconFlowEmbedding`、`SiliconFlowReranker`、`get_store()`、`get_reranker()` |
| `retriever.py` | 检索入口与多路召回编排 | `retrieve()`、`retrieve_for_conflict()`、`_safe_search()` |
| `query_rewriter.py` | Multi-Query 查询改写 | `rewrite_query()` |
| `hyde.py` | HyDE 假设文档生成与检索 | `generate_hypothetical_document()`、`hyde_retrieve()` |
| `tokenize.py` | 中英混合分词 | `tokenize()`、`tokenize_query()`、`has_jieba()` |

---

## 9. 与 Orchestrator 的集成

RAG 模块通过 **orchestrator 层的辅助函数** 被 Agent 调用，Agent 不直接访问 RAG 内部接口：

```
Agent (intra_team / cross_team / evidence_check / arbitrate)
  │
  ▼
orchestrator/evidence_helpers.py  ── retrieve_for_conflict()
  │                                   为冲突点检索文档证据，返回结构化证据列表
  │                                   （含 evidence_id / quote / source / strength）
  │
orchestrator/manager.py           ── retrieve()
  │                                   会议管理中的基础文档检索
  │
orchestrator/runner.py            ── clear_store()
                                      会议结束/重置时清理向量缓存
```

**文档入库入口**：`routers/documents.py`

- 文档上传 API 接收 Markdown 内容后，调用 `chunk_markdown()` 切分
- 通过 `get_store(meeting_id).add_chunks(chunks)` 写入向量库
- 每个会议的向量库按 `meeting_id` 隔离

**集成要点**：

- Agent 通过 Tool 调用链间接访问 RAG：Agent → Tool/Node → evidence_helpers → retriever
- RAG 对 Agent 透明，Agent 只看到结构化的证据结果（含摘要、来源、可展开标记）
- 惰性读取策略：Prompt 中默认只注入 Chunk 摘要（前 200 字符），完整文本按需通过 `expand_context` / `get_neighbor_context` 展开，控制 Token 消耗
- 所有外部依赖（Embedding API、Reranker API、Qdrant、LLM）均有 fallback，保证单组件故障不中断仲裁流程
