# 检索 + 重排：真实 bge-reranker-v2-m3 或关键词加成兜底
from __future__ import annotations

import re
from typing import Any

import httpx

from app.config import settings
from app.rag.store import get_store


def retrieve(
    meeting_id: str,
    query: str,
    top_k: int = 5,
    summary_max: int = 200,
) -> list[dict[str, Any]]:
    """检索：返回 top_k 个 chunk 的字典视图（含摘要，可按需展开）

    惰性读取策略：默认只返回 summary（前 summary_max 字符 + 省略号），
    完整文本通过 expand_context 按需获取，减少 prompt token 消耗。
    """
    store = get_store(meeting_id)
    if not store.all_chunks():
        return []
    # 召回阶段取更多候选，给 reranker 留空间
    candidates = store.search(query, top_k=max(top_k * 2, 10))
    out: list[dict[str, Any]] = []
    for chunk, score in candidates:
        d = chunk.to_dict()
        d["score"] = round(score, 4)
        # 惰性读取：返回摘要 + 完整长度，调用方按需 expand
        d["summary"] = chunk.summary(max_len=summary_max)
        d["full_length"] = len(chunk.text)
        d["expandable"] = len(chunk.text) > summary_max
        out.append(d)
    return out


def retrieve_for_conflict(
    meeting_id: str,
    conflict_summary: str,
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """针对单个冲突检索证据：召回 → 重排"""
    base = retrieve(meeting_id, conflict_summary, top_k=top_k)
    if not base:
        return base
    # 有 reranker 配置则用真实重排，否则关键词加成
    if settings.use_real_rerank:
        return _rerank_with_siliconflow(conflict_summary, base, top_k)
    return _rerank_with_keywords(conflict_summary, base, top_k)


def _rerank_with_siliconflow(
    query: str, candidates: list[dict[str, Any]], top_k: int
) -> list[dict[str, Any]]:
    """硅基流动 bge-reranker-v2-m3 真实重排"""
    try:
        resp = httpx.post(
            f"{settings.rerank_base_url.rstrip('/')}/rerank",
            headers={"Authorization": f"Bearer {settings.rerank_api_key}"},
            json={
                "model": settings.rerank_model,
                "query": query,
                "documents": [c["text"] for c in candidates],
                "top_n": top_k,
                "return_documents": False,
            },
            timeout=30.0,
        )
        resp.raise_for_status()
        results = resp.json()["results"]
        # 按 relevance_score 重排
        reranked: list[dict[str, Any]] = []
        for r in results:
            idx = r["index"]
            item = candidates[idx].copy()
            item["score"] = round(r["relevance_score"], 4)
            reranked.append(item)
        return reranked[:top_k]
    except Exception:
        # reranker 失败则降级关键词重排
        return _rerank_with_keywords(query, candidates, top_k)


def _rerank_with_keywords(
    query: str, candidates: list[dict[str, Any]], top_k: int
) -> list[dict[str, Any]]:
    """关键词加成重排（stub 兜底）"""
    keywords = set(_tokenize(query))
    for item in candidates:
        hits = sum(1 for kw in keywords if kw in item["text"].lower())
        item["score"] = round(item["score"] + hits * 0.05, 4)
    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates[:top_k]


def _tokenize(text: str) -> list[str]:
    return [w for w in re.split(r"[^a-z0-9\u4e00-\u9fa5]+", text.lower()) if len(w) > 1]
