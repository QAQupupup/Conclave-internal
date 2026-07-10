# 检索 + 重排：查询改写多路召回 + 混合检索 + bge-reranker-v2-m3 重排
from __future__ import annotations

import re
from typing import Any

import httpx

from app.config import settings
from app.rag.query_rewriter import rewrite_query
from app.rag.store import get_store


def retrieve(
    meeting_id: str,
    query: str,
    top_k: int = 5,
    summary_max: int = 200,
    expand_neighbors: int = 0,
) -> list[dict[str, Any]]:
    """检索：返回 top_k 个 chunk 的字典视图（含摘要，可按需展开）

    惰性读取策略：默认只返回 summary（前 summary_max 字符 + 省略号），
    完整文本通过 expand_context 按需获取，减少 prompt token 消耗。

    邻居链扩展：expand_neighbors > 0 时，附带前 N 个 chunk 的摘要，
    提供更完整的上下文窗口（适用于证据检索场景）。
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
        # 邻居链上下文：附带前 N 个 chunk 的文本
        if expand_neighbors > 0:
            neighbor_ctx = store.get_neighbor_context(
                chunk, prev_count=expand_neighbors, next_count=0,
            )
            if len(neighbor_ctx) > len(chunk.text):
                d["neighbor_context"] = neighbor_ctx[:summary_max * 3]
        out.append(d)
    return out


async def retrieve_for_conflict(
    meeting_id: str,
    conflict_summary: str,
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """针对单个冲突检索证据：查询改写 → 多路召回 → 合并去重 → 重排 → 邻居链扩展

    流程：
    1. 查询改写：LLM 生成 2 个改写查询 + 原始查询（最多 3 路）
    2. 多路召回：每路检索 top_k*2 个候选
    3. 合并去重：按 chunk_id 去重，保留最高分
    4. Reranker 重排：bge-reranker-v2-m3 或关键词加成
    5. 邻居链扩展：附带前后 N 个 chunk 上下文
    """
    # 1. 查询改写
    queries = await rewrite_query(conflict_summary)

    # 2. 多路召回 + 合并去重
    store = get_store(meeting_id)
    if not store.all_chunks():
        return []

    seen: dict[str, dict[str, Any]] = {}
    for q in queries:
        candidates = store.search(q, top_k=max(top_k * 2, 10))
        for chunk, score in candidates:
            d = chunk.to_dict()
            d["score"] = round(score, 4)
            d["summary"] = chunk.summary(max_len=200)
            d["full_length"] = len(chunk.text)
            d["expandable"] = len(chunk.text) > 200
            # 邻居链上下文
            neighbor_ctx = store.get_neighbor_context(
                chunk, prev_count=1, next_count=0,
            )
            if len(neighbor_ctx) > len(chunk.text):
                d["neighbor_context"] = neighbor_ctx[:600]
            # 去重：同一 chunk_id 保留最高分
            if chunk.chunk_id not in seen or score > seen[chunk.chunk_id]["score"]:
                seen[chunk.chunk_id] = d

    base = list(seen.values())
    base.sort(key=lambda x: x["score"], reverse=True)

    if not base:
        return []

    # 3. 重排
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
    # [CON-26 修复] 用中英分词工具（jieba 中文按词切）替代单字切分
    from app.rag.tokenize import tokenize

    return tokenize(text)
