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


class InMemoryVectorStore:
    """内存向量库：存 chunk + 向量，余弦相似度检索"""

    def __init__(self, embedding: Embedding | None = None) -> None:
        self._embedding = embedding or _build_embedding()
        self._store: dict[str, tuple[Chunk, list[float]]] = {}

    def add_chunks(self, chunks: list[Chunk]) -> None:
        """切块入库并计算向量（批量嵌入提升效率）"""
        if not chunks:
            return
        texts = [c.text for c in chunks]
        vecs = self._embedding.embed_batch(texts)
        for chunk, vec in zip(chunks, vecs):
            self._store[chunk.chunk_id] = (chunk, vec)

    def search(self, query: str, top_k: int = 5) -> list[tuple[Chunk, float]]:
        if not self._store:
            return []
        qvec = self._embedding.embed(query)
        scored = [
            (chunk, cosine_similarity(qvec, vec))
            for chunk, vec in self._store.values()
        ]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    def all_chunks(self) -> list[Chunk]:
        return [c for c, _ in self._store.values()]

    def clear(self) -> None:
        self._store.clear()


def _build_embedding() -> Embedding:
    """按配置构建嵌入器：有 key 用真实 bge-m3，否则用 stub"""
    if settings.use_real_embed:
        return SiliconFlowEmbedding()
    return StubEmbedding()


# 进程级单例向量库，按 meeting_id 隔离
_stores: dict[str, InMemoryVectorStore] = {}


def get_store(meeting_id: str) -> InMemoryVectorStore:
    if meeting_id not in _stores:
        _stores[meeting_id] = InMemoryVectorStore()
    return _stores[meeting_id]
