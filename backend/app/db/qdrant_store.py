"""Qdrant VectorStore 实现。

实现 VectorStore ABC，对接 Qdrant 向量数据库。
"""

from __future__ import annotations

from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)

from app.config import settings
from app.db.vector_store import VectorStore


class QdrantVectorStore(VectorStore):
    """Qdrant 向量存储实现。"""

    def __init__(self) -> None:
        self._client = QdrantClient(url=settings.qdrant_url)

    async def ensure_collection(self, name: str, vector_size: int) -> None:
        exists = await self.collection_exists(name)
        if not exists:
            self._client.create_collection(
                collection_name=name,
                vectors_config=VectorParams(
                    size=vector_size,
                    distance=Distance.COSINE,
                ),
            )

    async def upsert(self, collection: str, points: list[dict[str, Any]]) -> None:
        point_structs = [
            PointStruct(
                id=p["id"],
                vector=p["vector"],
                payload=p.get("payload", {}),
            )
            for p in points
        ]
        self._client.upsert(collection_name=collection, points=point_structs)

    async def search(
        self,
        collection: str,
        query_vector: list[float],
        limit: int = 5,
        score_threshold: float | None = None,
        filter_conditions: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        qdrant_filter = None
        if filter_conditions:
            qdrant_filter = Filter(
                must=[FieldCondition(key=k, match=MatchValue(value=v)) for k, v in filter_conditions.items()]
            )

        results = self._client.search(
            collection_name=collection,
            query_vector=query_vector,
            limit=limit,
            score_threshold=score_threshold,
            query_filter=qdrant_filter,
        )

        return [
            {
                "id": r.id,
                "score": r.score,
                "payload": r.payload,
            }
            for r in results
        ]

    async def delete(self, collection: str, point_ids: list[str]) -> None:
        self._client.delete(
            collection_name=collection,
            points_selector=point_ids,
        )

    async def collection_exists(self, name: str) -> bool:
        try:
            self._client.get_collection(name)
            return True
        except Exception:
            return False

    async def count(self, collection: str) -> int:
        info = self._client.get_collection(collection)
        return info.points_count if info else 0
