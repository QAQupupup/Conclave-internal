# 检索 + 简单重排：按相似度排序取 top5
from __future__ import annotations

from typing import Any

from app.rag.chunker import Chunk
from app.rag.store import InMemoryVectorStore, get_store


def retrieve(
    meeting_id: str,
    query: str,
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """检索：返回 top_k 个 chunk 的字典视图

    若向量库为空（未上传文档），返回空列表，调用方需兜底。
    """
    store = get_store(meeting_id)
    if not store.all_chunks():
        return []
    results = store.search(query, top_k=top_k)
    out: list[dict[str, Any]] = []
    for chunk, score in results:
        d = chunk.to_dict()
        d["score"] = round(score, 4)
        out.append(d)
    return out


def retrieve_for_conflict(
    meeting_id: str,
    conflict_summary: str,
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """针对单个冲突检索证据：以冲突摘要作为 query

    简单重排：对返回结果再做一次关键词加成（命中摘要词的加分）。
    """
    base = retrieve(meeting_id, conflict_summary, top_k=top_k)
    if not base:
        return base
    # 简单关键词重排：query 分词命中 text 的加分
    keywords = set(_tokenize(conflict_summary))
    for item in base:
        hits = sum(1 for kw in keywords if kw in item["text"].lower())
        item["score"] = round(item["score"] + hits * 0.05, 4)
    base.sort(key=lambda x: x["score"], reverse=True)
    return base[:top_k]


def _tokenize(text: str) -> list[str]:
    """极简分词：小写 + 按非字母数字切分，过滤短词"""
    import re

    return [w for w in re.split(r"[^a-z0-9\u4e00-\u9fa5]+", text.lower()) if len(w) > 1]
