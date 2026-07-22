# 检索 + 重排：查询改写多路召回 + HyDE + 混合检索 + Reranker 重排
from __future__ import annotations

import asyncio
from typing import Any

from app.rag.hyde import hyde_retrieve
from app.rag.query_rewriter import rewrite_query
from app.rag.store import get_reranker, get_store


async def retrieve(
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
    candidates = await store.search(query, top_k=max(top_k * 2, 10))
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
                chunk,
                prev_count=expand_neighbors,
                next_count=0,
            )
            if len(neighbor_ctx) > len(chunk.text):
                d["neighbor_context"] = neighbor_ctx[: summary_max * 3]
        out.append(d)
    return out


def _build_chunk_dict(chunk: Any, score: float, store: Any) -> dict[str, Any]:
    """将 (chunk, score) 转换为带元数据的字典视图（含邻居链上下文）。"""
    d: dict[str, Any] = dict(chunk.to_dict())
    d["score"] = round(score, 4)
    d["summary"] = chunk.summary(max_len=200)
    d["full_length"] = len(chunk.text)
    d["expandable"] = len(chunk.text) > 200
    # 邻居链上下文
    neighbor_ctx = store.get_neighbor_context(
        chunk,
        prev_count=1,
        next_count=0,
    )
    if len(neighbor_ctx) > len(chunk.text):
        d["neighbor_context"] = neighbor_ctx[:600]
    return d


async def retrieve_for_conflict(
    meeting_id: str,
    conflict_summary: str,
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """针对单个冲突检索证据：查询改写 + HyDE → 多路召回 → 合并去重 → 重排 → 邻居链扩展

    流程：
    1. 查询改写 + HyDE 并行：LLM 生成 2 个改写查询 + 原始查询 + 假设文档检索
       （HyDE 用假设文档的 embedding 检索，弥补 query-document 语义鸿沟）
    2. 多路召回：每路检索 top_k*2 个候选
    3. 合并去重：按 chunk_id 去重，保留最高分
    4. Reranker 重排：使用 get_reranker()（真实 API 或关键词 fallback）
    5. 邻居链扩展：附带前后 N 个 chunk 上下文
    """
    store = get_store(meeting_id)
    if not store.all_chunks():
        return []

    # 1. 查询改写 + HyDE 并行（减少总延迟）
    search_k = max(top_k * 2, 10)
    queries_task = rewrite_query(conflict_summary)
    hyde_task = hyde_retrieve(store, conflict_summary, top_k=search_k)

    queries, hyde_candidates = await asyncio.gather(queries_task, hyde_task)

    # 2. 多路召回 + HyDE 召回 → 合并去重
    seen: dict[str, dict[str, Any]] = {}

    # Multi-Query 召回
    for q in queries:
        candidates = await store.search(q, top_k=search_k)
        for chunk, score in candidates:
            d = _build_chunk_dict(chunk, score, store)
            # 去重：同一 chunk_id 保留最高分
            if chunk.chunk_id not in seen or score > seen[chunk.chunk_id]["score"]:
                seen[chunk.chunk_id] = d

    # HyDE 召回（假设文档检索到的 chunk 合并入候选池）
    for chunk, score in hyde_candidates:
        d = _build_chunk_dict(chunk, score, store)
        if chunk.chunk_id not in seen or score > seen[chunk.chunk_id]["score"]:
            seen[chunk.chunk_id] = d

    base = list(seen.values())
    if not base:
        return []

    # 按初始分数排序（reranker 内部再重排）
    base.sort(key=lambda x: x["score"], reverse=True)

    # 3. 使用 Reranker Protocol 统一重排（SiliconFlow 失败自动回退关键词）
    reranker = get_reranker()
    documents = [c["text"] for c in base]
    reranked = await reranker.rerank(conflict_summary, documents, top_n=top_k)
    results: list[dict[str, Any]] = []
    for idx, rel_score in reranked:
        if 0 <= idx < len(base):
            item = base[idx].copy()
            item["score"] = round(rel_score, 4)
            results.append(item)
    return results
