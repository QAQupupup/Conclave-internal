# 内存向量存储：StubEmbedding（确定性 hash 向量，余弦相似度），预留 Qdrant 接口
from __future__ import annotations

import hashlib
import math
from typing import Protocol

from app.config import settings
from app.rag.chunker import Chunk


class Embedding(Protocol):
    """嵌入接口：真实可用 OpenAI text-embedding，这里只定义协议"""
    def embed(self, text: str) -> list[float]: ...


class StubEmbedding:
    """确定性伪向量：对文本 hash 后映射到固定维度向量，无需外部库

    保证相同文本得到相同向量，不同文本尽量分散。
    """

    def __init__(self, dim: int | None = None) -> None:
        self.dim = dim or settings.embed_dim

    def embed(self, text: str) -> list[float]:
        if not text:
            return [0.0] * self.dim
        out: list[float] = []
        # 对每个维度取不同盐切片段做 hash，映射到 [-1, 1]
        for i in range(self.dim):
            salt = f"{i}:{text}"
            digest = hashlib.md5(salt.encode("utf-8")).hexdigest()
            # 取前 8 个十六进制字符转 int，再归一化到 [-1, 1]
            val = int(digest[:8], 16) / 0xFFFFFFFF  # [0, 1]
            out.append(val * 2 - 1)
        return out


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """余弦相似度"""
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
        self._embedding = embedding or StubEmbedding()
        # chunk_id -> (chunk, vector)
        self._store: dict[str, tuple[Chunk, list[float]]] = {}

    def add_chunks(self, chunks: list[Chunk]) -> None:
        """切块入库并计算向量"""
        for chunk in chunks:
            vec = self._embedding.embed(chunk.text)
            self._store[chunk.chunk_id] = (chunk, vec)

    def search(self, query: str, top_k: int = 5) -> list[tuple[Chunk, float]]:
        """检索：按余弦相似度排序取 top_k"""
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
        """返回全部块，用于无检索条件时的兜底"""
        return [c for c, _ in self._store.values()]

    def clear(self) -> None:
        self._store.clear()


class QdrantVectorStore:
    """Qdrant 向量库接口占位（迭代一不启用，保持接口一致）"""

    def __init__(self, url: str, collection: str) -> None:
        self.url = url
        self.collection = collection
        raise NotImplementedError("Qdrant 适配在迭代一未启用，请使用 InMemoryVectorStore")

    def add_chunks(self, chunks: list[Chunk]) -> None:
        raise NotImplementedError

    def search(self, query: str, top_k: int = 5) -> list[tuple[Chunk, float]]:
        raise NotImplementedError


def build_store() -> InMemoryVectorStore:
    """按配置构建向量库（迭代一恒为内存版）"""
    return InMemoryVectorStore()


# 进程级单例向量库，按 meeting_id 隔离
_stores: dict[str, InMemoryVectorStore] = {}


def get_store(meeting_id: str) -> InMemoryVectorStore:
    """取某会议专属的向量库（按会议隔离文档）"""
    if meeting_id not in _stores:
        _stores[meeting_id] = InMemoryVectorStore()
    return _stores[meeting_id]
