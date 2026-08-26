# 临近话题索引：会议议题向量化，支撑"创建时推荐相似历史会议"与"完成后聚类"。
#
# 独立 Qdrant collection `conclave_topics`，与 chunk 检索隔离，避免污染 RAG 召回。
# 无 Qdrant / 无 embedding key 时优雅降级为 no-op（不阻塞会议主流程）。
#
# 设计依据：docs/design/knowledge-rag-orchestration-review.md §3.2
from __future__ import annotations

import hashlib
import os
from typing import Any

from app.config import settings
from app.logging_config import get_logger
from app.rag.store import _build_embedding

logger = get_logger("rag.topic_index")

TOPIC_COLLECTION = os.environ.get("CONCLAVE_QDRANT_TOPIC_COLLECTION", "conclave_topics")


def _topic_point_id(meeting_id: str) -> int:
    """确定性点 ID（与 chunk 同策略：sha256 前 8 字节转 int63，重启可重建）。"""
    digest = hashlib.sha256(meeting_id.encode()).digest()
    return int.from_bytes(digest[:8], "big") & (2**63 - 1)


class TopicIndex:
    """会议议题向量索引（Qdrant 单 collection，按 tenant_id payload 过滤）。"""

    def __init__(self) -> None:
        self._embedding = _build_embedding()
        self._url = getattr(settings, "qdrant_url", "") or ""
        self._client = None
        self._initialized = False

    def _get_client(self):
        if self._client is None:
            from qdrant_client import QdrantClient

            self._client = QdrantClient(url=self._url)
        return self._client

    async def ensure_collection(self) -> bool:
        """确保 collection 存在。返回是否可用（无 Qdrant 返回 False）。"""
        if not self._url:
            return False
        if self._initialized:
            return True
        try:
            from qdrant_client.models import Distance, PayloadSchemaType, VectorParams

            client = self._get_client()
            names = [c.name for c in client.get_collections().collections]
            if TOPIC_COLLECTION not in names:
                dim = len(await self._embedding.embed("test"))
                client.create_collection(
                    collection_name=TOPIC_COLLECTION,
                    vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
                )
            with __import__("contextlib").suppress(Exception):
                client.create_payload_index(
                    collection_name=TOPIC_COLLECTION,
                    field_name="tenant_id",
                    field_schema=PayloadSchemaType.INTEGER,
                )
            with __import__("contextlib").suppress(Exception):
                client.create_payload_index(
                    collection_name=TOPIC_COLLECTION,
                    field_name="meeting_id",
                    field_schema=PayloadSchemaType.KEYWORD,
                )
            self._initialized = True
            return True
        except Exception as e:  # 降级：索引不可用不影响会议
            logger.warning("TopicIndex 初始化失败，降级为 no-op: %s", str(e)[:150])
            return False

    async def upsert(
        self,
        meeting_id: str,
        tenant_id: int | None,
        topic: str,
        *,
        status: str = "running",
        deliverable_type: str = "",
        summary: str = "",
        tags: list[str] | None = None,
    ) -> None:
        """写入/更新某会议的议题向量。"""
        if not self._url:
            return
        try:
            if not await self.ensure_collection():
                return
            text = (topic or "").strip()
            if not text and not summary:
                return
            embed_text = f"{topic}\n{summary}".strip()
            vec = await self._embedding.embed(embed_text)
            from qdrant_client.models import PointStruct

            payload: dict[str, Any] = {
                "meeting_id": meeting_id,
                "tenant_id": tenant_id if tenant_id is not None else -1,
                "topic": topic,
                "status": status,
                "deliverable_type": deliverable_type,
                "summary": (summary or "")[:2000],
                "tags": tags or [],
            }
            self._get_client().upsert(
                collection_name=TOPIC_COLLECTION,
                points=[PointStruct(id=_topic_point_id(meeting_id), vector=vec, payload=payload)],
            )
        except Exception as e:
            logger.warning("TopicIndex.upsert 失败（忽略）: %s", str(e)[:150])

    async def delete(self, meeting_id: str) -> None:
        if not self._url:
            return
        try:
            if not await self.ensure_collection():
                return
            from qdrant_client.models import FieldCondition, Filter, FilterSelector, MatchValue

            self._get_client().delete(
                collection_name=TOPIC_COLLECTION,
                points_selector=FilterSelector(
                    filter=Filter(
                        must=[
                            FieldCondition(
                                key="meeting_id",
                                match=MatchValue(value=meeting_id),
                            )
                        ]
                    )
                ),
            )
        except Exception:
            pass

    async def search(
        self,
        query: str,
        tenant_id: int | None,
        *,
        top_k: int = 5,
        exclude_meeting_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """检索最相似的议题，返回 [{meeting_id, topic, status, score, ...}]。

        - 仅检索当前租户（tenant_id=None 时匹配 -1 系统占位，避免跨租户泄露）。
        - exclude_meeting_id 用于"相关会议"场景，排除自身。
        """
        if not self._url or not query.strip():
            return []
        try:
            if not await self.ensure_collection():
                return []
            from qdrant_client.models import Condition, FieldCondition, Filter, MatchValue

            tid = tenant_id if tenant_id is not None else -1
            must_conditions: list[Condition] = [FieldCondition(key="tenant_id", match=MatchValue(value=tid))]
            query_filter = Filter(must=must_conditions)
            vec = await self._embedding.embed(query)
            results = self._get_client().search(
                collection_name=TOPIC_COLLECTION,
                query_vector=vec,
                query_filter=query_filter,
                limit=top_k + (1 if exclude_meeting_id else 0),
            )
            out: list[dict[str, Any]] = []
            for r in results:
                p = r.payload or {}
                mid = p.get("meeting_id", "")
                if exclude_meeting_id and mid == exclude_meeting_id:
                    continue
                # 排除自身尚未完成/非法的占位
                if not mid:
                    continue
                out.append(
                    {
                        "meeting_id": mid,
                        "topic": p.get("topic", ""),
                        "status": p.get("status", ""),
                        "deliverable_type": p.get("deliverable_type", ""),
                        "summary": p.get("summary", ""),
                        "tags": p.get("tags", []),
                        "score": round(float(r.score or 0.0), 4),
                    }
                )
                if len(out) >= top_k:
                    break
            return out
        except Exception as e:
            logger.warning("TopicIndex.search 失败（返回空）: %s", str(e)[:150])
            return []


# 进程级单例
_topic_index: TopicIndex | None = None


def get_topic_index() -> TopicIndex:
    global _topic_index
    if _topic_index is None:
        _topic_index = TopicIndex()
    return _topic_index
