"""向量存储抽象接口（槽接口）。

定义向量检索的标准契约，当前由 Qdrant 实现，未来可切换为 pgvector 或 seekdb。
业务代码仅依赖此接口，不感知具体实现。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class VectorStore(ABC):
    """向量存储抽象接口。

    设计原则：
    - 方法签名与 Qdrant 概念对齐（Collection、Point），但足够通用
    - 不暴露底层 Client 对象，调用方仅通过此接口操作
    """

    @abstractmethod
    async def ensure_collection(self, name: str, vector_size: int) -> None:
        """确保集合存在（不存在则创建）。"""
        ...

    @abstractmethod
    async def upsert(self, collection: str, points: list[dict[str, Any]]) -> None:
        """批量 upsert 向量点。
        points: [{"id": str, "vector": list[float], "payload": dict}, ...]
        """
        ...

    @abstractmethod
    async def search(
        self,
        collection: str,
        query_vector: list[float],
        limit: int = 5,
        score_threshold: float | None = None,
        filter_conditions: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """向量相似度搜索。
        返回: [{"id": str, "score": float, "payload": dict}, ...]
        """
        ...

    @abstractmethod
    async def delete(self, collection: str, point_ids: list[str]) -> None:
        """删除指定向量点。"""
        ...

    @abstractmethod
    async def collection_exists(self, name: str) -> bool:
        """检查集合是否存在。"""
        ...

    @abstractmethod
    async def count(self, collection: str) -> int:
        """返回集合中向量点数量。"""
        ...
