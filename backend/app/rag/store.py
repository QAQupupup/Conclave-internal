# 向量存储：StubEmbedding / SiliconFlowEmbedding（bge-m3），余弦相似度检索
from __future__ import annotations

import hashlib
import math
from typing import Protocol

import httpx

from app.config import settings
from app.rag.chunker import Chunk


class Embedding(Protocol):
    """嵌入接口"""
    def embed(self, text: str) -> list[float]: ...
    def embed_batch(self, texts: list[str]) -> list[list[float]]: ...


class StubEmbedding:
    """确定性伪向量：对文本 hash 后映射到固定维度向量，无需外部库"""

    def __init__(self, dim: int | None = None) -> None:
        self.dim = dim or settings.embed_dim

    def embed(self, text: str) -> list[float]:
        if not text:
            return [0.0] * self.dim
        out: list[float] = []
        for i in range(self.dim):
            salt = f"{i}:{text}"
            digest = hashlib.md5(salt.encode("utf-8")).hexdigest()
            val = int(digest[:8], 16) / 0xFFFFFFFF
            out.append(val * 2 - 1)
        return out

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(t) for t in texts]


class SiliconFlowEmbedding:
    """硅基流动 bge-m3 真实嵌入：调 OpenAI 兼容 /embeddings 端点"""

    def __init__(self) -> None:
        self._api_key = settings.embed_api_key
        self._base_url = settings.embed_base_url.rstrip("/")
        self._model = settings.embed_model
        self._client = httpx.Client(timeout=30.0)
        # bge-m3 输出 1024 维
        self.dim = 1024

    def embed(self, text: str) -> list[float]:
        return self.embed_batch([text])[0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        # 分批处理，每批最多 32 条
        all_vecs: list[list[float]] = []
        for i in range(0, len(texts), 32):
            batch = texts[i : i + 32]
            resp = self._client.post(
                f"{self._base_url}/embeddings",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={"model": self._model, "input": batch},
            )
            resp.raise_for_status()
            data = resp.json()["data"]
            # 按 index 排序确保顺序正确
            data.sort(key=lambda x: x["index"])
            all_vecs.extend([item["embedding"] for item in data])
        return all_vecs


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        raise ValueError("向量维度不一致")
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _tokenize_query(text: str) -> list[str]:
    """中文/英文分词：提取长度>=2 的词条（jieba 中文分词）

    [CON-26 修复] 旧版用单字切分（re.split 按非中英字符），中文无空格分界时
    把"会议系统设计"切成 6 个单字，召回率低。改为：
    - 英文：按非字母数字字符切，长度 >= 2
    - 中文：jieba.cut 按词切（jieba 未安装时退回单字）
    """
    from app.rag.tokenize import tokenize_query

    return tokenize_query(text)


def _keyword_score(text: str, query_terms: list[str], doc_freq: int = 1) -> float:
    """简化 TF-IDF 关键词得分

    对每个查询词条计算在文本中的命中次数，加权求和。
    doc_freq 用于 IDF 惩罚（预留，当前固定为 1）。
    """
    if not query_terms or not text:
        return 0.0
    text_lower = text.lower()
    score = 0.0
    for term in query_terms:
        count = text_lower.count(term)
        if count > 0:
            # TF: 命中次数 / 文本长度（归一化避免长文本优势）
            tf = count / max(len(text_lower), 1)
            # IDF: 简化为 1（未实现全局文档频率统计）
            idf = 1.0 / max(doc_freq, 1)
            score += tf * idf
    return score


class InMemoryVectorStore:
    """内存向量库：存 chunk + 向量，余弦相似度检索

    支持原文缓存和惰性展开：存文档原文，按 char_range 按需展开上下文。
    """

    def __init__(self, embedding: Embedding | None = None) -> None:
        self._embedding = embedding or _build_embedding()
        self._store: dict[str, tuple[Chunk, list[float]]] = {}
        # 原文缓存：doc_id → 原始文本，用于惰性展开
        self._raw_texts: dict[str, str] = {}

    def add_chunks(self, chunks: list[Chunk]) -> None:
        """切块入库并计算向量（批量嵌入提升效率）"""
        if not chunks:
            return
        texts = [c.text for c in chunks]
        vecs = self._embedding.embed_batch(texts)
        for chunk, vec in zip(chunks, vecs):
            self._store[chunk.chunk_id] = (chunk, vec)
        # 原文缓存：仅在 store_raw_text 未调用时作为兜底
        # 优先用 store_raw_text 存入完整文档原文，此处只标记文档存在
        for chunk in chunks:
            if chunk.doc_id not in self._raw_texts:
                self._raw_texts[chunk.doc_id] = ""  # 占位，expand_context 会回退到 chunk.text

    def store_raw_text(self, doc_id: str, full_text: str) -> None:
        """缓存文档完整原文，用于跨 chunk 惰性展开"""
        self._raw_texts[doc_id] = full_text

    def expand_context(
        self,
        chunk: Chunk,
        before: int = 0,
        after: int = 0,
    ) -> str:
        """惰性展开：从原文缓存按 char_range 扩展上下文

        - before/after: 向前/向后扩展的字符数
        - 返回扩展后的文本；无原文缓存时回退到 chunk.text
        """
        raw = self._raw_texts.get(chunk.doc_id)
        if not raw:  # None 或空字符串都回退到 chunk.text
            return chunk.text
        start = max(0, chunk.char_start - before)
        end = min(len(raw), chunk.char_end + after)
        return raw[start:end]

    def get_neighbor_context(
        self,
        chunk: Chunk,
        prev_count: int = 1,
        next_count: int = 1,
    ) -> str:
        """按邻居链展开上下文：拼接 prev/next chunk 的文本

        相比 expand_context 的字符级展开，邻居链按 chunk 粒度展开，
        能完整保留相邻标题段落，提供更好的上下文窗口。

        - prev_count: 向前取几个 chunk
        - next_count: 向后取几个 chunk
        - 返回拼接后的上下文文本
        """
        parts: list[str] = []
        # 向前遍历
        prev_chunks: list[str] = []
        current = chunk
        for _ in range(prev_count):
            if not current.prev_id:
                break
            prev = self._store.get(current.prev_id)
            if prev is None:
                break
            current = prev[0]
            prev_chunks.insert(0, current.text)
        # 向后遍历
        next_chunks: list[str] = []
        current = chunk
        for _ in range(next_count):
            if not current.next_id:
                break
            nxt = self._store.get(current.next_id)
            if nxt is None:
                break
            current = nxt[0]
            next_chunks.append(current.text)
        parts = prev_chunks + [chunk.text] + next_chunks
        return "\n\n".join(parts)

    def get_chunk(self, chunk_id: str) -> Chunk | None:
        """按 ID 取单个 chunk"""
        entry = self._store.get(chunk_id)
        return entry[0] if entry else None

    def search(self, query: str, top_k: int = 5) -> list[tuple[Chunk, float]]:
        if not self._store:
            return []
        return self.hybrid_search(query, top_k)

    def hybrid_search(self, query: str, top_k: int = 5, rrf_k: int = 60) -> list[tuple[Chunk, float]]:
        """混合检索：向量检索 + 关键词检索 → RRF 融合

        RRF（Reciprocal Rank Fusion）：score = 1/(K + rank)
        两路各取 top_k*2 个候选，RRF 融合后截取 top_k。
        """
        if not self._store:
            return []

        # 1. 向量检索
        qvec = self._embedding.embed(query)
        vec_scored = [
            (chunk, cosine_similarity(qvec, vec))
            for chunk, vec in self._store.values()
        ]
        vec_scored.sort(key=lambda x: x[1], reverse=True)
        vec_candidates = vec_scored[: top_k * 2]

        # 2. 关键词检索（TF-IDF 简化版）
        query_terms = _tokenize_query(query)
        kw_scored = [
            (chunk, _keyword_score(chunk.text, query_terms))
            for chunk, _ in self._store.values()
        ]
        kw_scored.sort(key=lambda x: x[1], reverse=True)
        kw_candidates = kw_scored[: top_k * 2]

        # 3. RRF 融合
        chunk_ranks: dict[str, tuple[Chunk, float, float]] = {}
        for rank, (chunk, score) in enumerate(vec_candidates, start=1):
            rrf = 1.0 / (rrf_k + rank)
            chunk_ranks[chunk.chunk_id] = (chunk, rrf, score)
        for rank, (chunk, kw_score) in enumerate(kw_candidates, start=1):
            rrf = 1.0 / (rrf_k + rank)
            if chunk.chunk_id in chunk_ranks:
                existing = chunk_ranks[chunk.chunk_id]
                chunk_ranks[chunk.chunk_id] = (existing[0], existing[1] + rrf, existing[2])
            else:
                chunk_ranks[chunk.chunk_id] = (chunk, rrf, 0.0)

        # 按 RRF 分数排序
        merged = sorted(chunk_ranks.values(), key=lambda x: x[1], reverse=True)
        return [(chunk, round(rrf_score, 4)) for chunk, rrf_score, _ in merged[:top_k]]

    def all_chunks(self) -> list[Chunk]:
        return [c for c, _ in self._store.values()]

    def clear(self) -> None:
        self._store.clear()


class QdrantVectorStore(InMemoryVectorStore):
    """Qdrant 向量库适配器（适配器模式）

    继承 InMemoryVectorStore 保持接口一致，add_chunks/search/all_chunks/clear 委托 Qdrant。
    原文缓存和惰性展开仍用内存（Qdrant 存向量+payload，不存原文）。
    Qdrant 不可用时自动降级到内存（_build_store 已处理）。
    """

    def __init__(self, url: str, embedding: Embedding | None = None) -> None:
        super().__init__(embedding)
        self._url = url.rstrip("/")
        self._collection = "conclave_chunks"
        self._client = None

    def _get_client(self):
        if self._client is None:
            from qdrant_client import QdrantClient
            self._client = QdrantClient(url=self._url)
        return self._client

    def ensure_collection(self) -> None:
        """确保 collection 存在，不存在则创建"""
        from qdrant_client.models import Distance, VectorParams
        client = self._get_client()
        collections = client.get_collections().collections
        names = [c.name for c in collections]
        if self._collection not in names:
            # 维度从 embedding 获取
            dim = len(self._embedding.embed("test"))
            client.create_collection(
                collection_name=self._collection,
                vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
            )

    def add_chunks(self, chunks: list[Chunk]) -> None:
        """入库：计算向量 + 写 Qdrant"""
        if not chunks:
            return
        from qdrant_client.models import PointStruct
        texts = [c.text for c in chunks]
        vecs = self._embedding.embed_batch(texts)
        client = self._get_client()
        points = []
        for chunk, vec in zip(chunks, vecs):
            # 内存也存一份（惰性展开用）
            self._store[chunk.chunk_id] = (chunk, vec)
            if chunk.doc_id not in self._raw_texts:
                self._raw_texts[chunk.doc_id] = ""  # 占位，优先用 store_raw_text
            # Qdrant 存 payload
            points.append(PointStruct(
                id=hash(chunk.chunk_id) % (2**63),
                vector=vec,
                payload=chunk.to_dict(),
            ))
        client.upsert(collection_name=self._collection, points=points)

    def search(self, query: str, top_k: int = 5) -> list[tuple[Chunk, float]]:
        """混合检索：Qdrant 向量检索 + 内存关键词检索 → RRF 融合

        失败时回退到父类 hybrid_search（纯内存混合检索）。
        """
        try:
            client = self._get_client()
            qvec = self._embedding.embed(query)

            # 1. Qdrant 向量检索
            results = client.search(
                collection_name=self._collection,
                query_vector=qvec,
                limit=top_k * 2,
            )
            vec_candidates: list[tuple[Chunk, float]] = []
            for r in results:
                payload = r.payload or {}
                chunk = Chunk(
                    chunk_id=payload.get("chunk_id", ""),
                    doc_id=payload.get("doc_id", ""),
                    section=payload.get("section", ""),
                    text=payload.get("text", ""),
                    char_start=payload.get("char_start", 0),
                    char_end=payload.get("char_end", 0),
                    source=payload.get("source", ""),
                    prev_id=payload.get("prev_id", ""),
                    next_id=payload.get("next_id", ""),
                )
                vec_candidates.append((chunk, r.score or 0.0))

            # 2. 关键词检索（内存中计分）
            query_terms = _tokenize_query(query)
            kw_scored = [
                (chunk, _keyword_score(chunk.text, query_terms))
                for chunk, _ in self._store.values()
            ]
            kw_scored.sort(key=lambda x: x[1], reverse=True)
            kw_candidates = kw_scored[: top_k * 2]

            # 3. RRF 融合
            rrf_k = 60
            chunk_ranks: dict[str, tuple[Chunk, float, float]] = {}
            for rank, (chunk, score) in enumerate(vec_candidates, start=1):
                rrf = 1.0 / (rrf_k + rank)
                chunk_ranks[chunk.chunk_id] = (chunk, rrf, score)
            for rank, (chunk, kw_score) in enumerate(kw_candidates, start=1):
                rrf = 1.0 / (rrf_k + rank)
                if chunk.chunk_id in chunk_ranks:
                    existing = chunk_ranks[chunk.chunk_id]
                    chunk_ranks[chunk.chunk_id] = (existing[0], existing[1] + rrf, existing[2])
                else:
                    chunk_ranks[chunk.chunk_id] = (chunk, rrf, 0.0)

            merged = sorted(chunk_ranks.values(), key=lambda x: x[1], reverse=True)
            return [(chunk, round(rrf_score, 4)) for chunk, rrf_score, _ in merged[:top_k]]

        except Exception:
            import logging
            logging.getLogger("app.rag.store").warning(
                "Qdrant 混合检索失败，回退内存混合检索（内存缓存: %d 条）",
                len(self._store),
            )
            return super().search(query, top_k)

    def clear(self) -> None:
        """清空：删 Qdrant collection + 内存"""
        try:
            client = self._get_client()
            client.delete_collection(collection_name=self._collection)
        except Exception:
            pass
        self._store.clear()
        self._raw_texts.clear()


def _build_embedding() -> Embedding:
    """按配置构建嵌入器：有 key 用真实 bge-m3，否则用 stub"""
    if settings.use_real_embed:
        return SiliconFlowEmbedding()
    return StubEmbedding()


# 进程级单例向量库，按 meeting_id 隔离
_stores: dict[str, InMemoryVectorStore] = {}


def get_store(meeting_id: str) -> InMemoryVectorStore:
    if meeting_id not in _stores:
        _stores[meeting_id] = _build_store()
    return _stores[meeting_id]


def clear_store(meeting_id: str) -> bool:
    """清理某会议的向量库内存缓存，释放chunks和向量内存。

    Returns:
        bool: 是否真的有缓存被清理。
    """
    store = _stores.pop(meeting_id, None)
    if store is not None:
        try:
            # 清空store内部缓存
            if hasattr(store, "_store"):
                store._store.clear()
            if hasattr(store, "_raw_texts"):
                store._raw_texts.clear()
        except Exception:
            pass
        return True
    return False


def _build_store() -> InMemoryVectorStore:
    """按配置构建向量库：优先 Qdrant，回退内存"""
    qdrant_url = getattr(settings, "qdrant_url", "") or ""
    if qdrant_url:
        try:
            store = QdrantVectorStore(url=qdrant_url, embedding=_build_embedding())
            store.ensure_collection()
            return store
        except Exception:
            pass  # Qdrant 不可用时回退内存
    return InMemoryVectorStore(embedding=_build_embedding())
