# 检索 + 重排：查询改写多路召回 + HyDE + 混合检索 + Reranker 重排
from __future__ import annotations

import asyncio
from typing import Any

from app.logging_config import get_logger
from app.rag.graph_expand import get_graph
from app.rag.hyde import hyde_retrieve
from app.rag.query_rewriter import rewrite_query
from app.rag.store import get_reranker, get_store

logger = get_logger("rag.retriever")


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
        logger.debug("retrieve: store 无 chunk，返回空列表 (meeting_id=%s)", meeting_id)
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


async def _safe_search(
    store: Any,
    query: str,
    top_k: int,
    route_name: str,
) -> list[tuple[Any, float]]:
    """单路召回的异常隔离包装。

    任何异常都不会中断整体流程，但会打 warning 日志供审计。
    返回空列表表示该路召回失败。
    """
    try:
        results = await store.search(query, top_k=top_k)
        logger.debug(
            "多路召回 [%s] 成功: query=%s, 候选数=%d",
            route_name,
            query[:80],
            len(results),
        )
        return list(results)
    except Exception as e:
        logger.warning(
            "多路召回 [%s] 失败，该路返回空（不影响其他路）: query=%s, error=%s: %s",
            route_name,
            query[:80],
            type(e).__name__,
            e,
        )
        return []


async def retrieve_for_conflict(
    meeting_id: str,
    conflict_summary: str,
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """针对单个冲突检索证据：查询改写 + HyDE → 多路并发召回 → 合并去重 → 重排 → 邻居链扩展

    流程：
    1. 查询改写 + HyDE 并行：LLM 生成 2 个改写查询 + 原始查询 + 假设文档检索
       （HyDE 用假设文档的 embedding 检索，弥补 query-document 语义鸿沟）
    2. 多路并发召回：每路检索 top_k*2 个候选，用 asyncio.gather 并发执行
       每路独立异常隔离，单路失败不阻塞其他路
    3. 合并去重：按 chunk_id 去重，保留最高分
    4. Reranker 重排：使用 get_reranker()（真实 API 或关键词 fallback）
    5. 邻居链扩展：附带前后 N 个 chunk 上下文
    """
    store = get_store(meeting_id)
    if not store.all_chunks():
        logger.debug("retrieve_for_conflict: store 无 chunk，返回空列表 (meeting_id=%s)", meeting_id)
        return []

    search_k = max(top_k * 2, 10)

    # 1. 查询改写 + HyDE 并行（减少总延迟）
    logger.info(
        "retrieve_for_conflict 开始: meeting_id=%s, conflict=%s..., top_k=%d", meeting_id, conflict_summary[:80], top_k
    )
    queries_task = rewrite_query(conflict_summary)
    hyde_task = hyde_retrieve(store, conflict_summary, top_k=search_k)

    queries, hyde_candidates = await asyncio.gather(queries_task, hyde_task, return_exceptions=False)

    logger.info(
        "查询改写完成: %d 路查询 (原始+%d 改写), HyDE 候选=%d",
        len(queries),
        len(queries) - 1,
        len(hyde_candidates),
    )

    # 2. 多路并发召回（asyncio.gather + 异常隔离）
    # 每路独立 _safe_search 包装，单路失败返回空列表不阻塞其他路
    search_tasks = [_safe_search(store, q, search_k, f"multi_query_{i}") for i, q in enumerate(queries)]
    search_results = await asyncio.gather(*search_tasks)

    # 合并去重：按 chunk_id 去重，保留最高分
    seen: dict[str, dict[str, Any]] = {}

    # Multi-Query 召回结果合并
    for candidates in search_results:
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
        logger.warning(
            "retrieve_for_conflict: 所有路召回均为空，返回空列表 (meeting_id=%s, conflict=%s...)",
            meeting_id,
            conflict_summary[:80],
        )
        return []

    logger.info(
        "多路召回合并去重: 总候选=%d (来自 %d 路查询 + HyDE)",
        len(base),
        len(queries),
    )

    # 按初始分数排序（reranker 内部再重排）
    base.sort(key=lambda x: x["score"], reverse=True)

    # 3. 使用 Reranker Protocol 统一重排（SiliconFlow 失败自动回退关键词）
    reranker = get_reranker()
    documents = [c["text"] for c in base]
    try:
        reranked = await reranker.rerank(conflict_summary, documents, top_n=top_k)
        logger.info(
            "Reranker 重排完成: 输入=%d, 输出=%d, reranker=%s",
            len(documents),
            len(reranked),
            type(reranker).__name__,
        )
    except Exception as e:
        logger.error(
            "Reranker 重排异常（非预期，get_reranker 内部应已回退）: %s: %s",
            type(e).__name__,
            e,
        )
        # 最后防线：用初始分数排序的前 top_k
        return base[:top_k]

    results: list[dict[str, Any]] = []
    for idx, rel_score in reranked:
        if 0 <= idx < len(base):
            item = base[idx].copy()
            item["score"] = round(rel_score, 4)
            results.append(item)

    logger.info(
        "retrieve_for_conflict 完成: 返回 %d 条证据 (meeting_id=%s)",
        len(results),
        meeting_id,
    )
    return results


async def _semantic_code_candidates(meeting_id: str, query: str, top_k: int) -> list[dict[str, Any]]:
    """语义层召回（ADR-018 Phase C 检索级联入口）：LightRAG naive chunk 召回。

    与结构层（向量+图）级联而非替代：aquery_data(naive) 纯向量召回预处理文档
    的 chunk，零查询期 LLM 消耗（D8），结果并入候选池交 Conclave reranker 统一
    重排。任何失败（语义层不可用/存储故障）返回空列表，不影响结构层检索路径。

    返回项携带 ``semantic_hit``（file_path/reference_id）供审计；``expandable``
    恒为 False——语义 chunk 不在结构 store 中，无展开入口，摘要即全文片段。
    """
    from app.rag.lightrag_adapter import decode_ingest_path, get_semantic_index, resolve_semantic_tenant_id

    index = get_semantic_index(resolve_semantic_tenant_id(), meeting_id=meeting_id)
    if index is None:
        return []
    try:
        await index.initialize()
        try:
            chunks = await index.retrieve_chunks(query, top_k=top_k)
        finally:
            await index.close()
    except Exception as e:
        logger.warning(
            "语义层召回失败（降级为纯结构检索）: meeting_id=%s, %s: %s",
            meeting_id,
            type(e).__name__,
            e,
        )
        return []

    out: list[dict[str, Any]] = []
    for i, c in enumerate(chunks):
        text = c["text"]
        # file_path 是摄入时的编码 token（encode_ingest_path），解码还原仓库相对路径
        file_path = decode_ingest_path(c["file_path"]) if c["file_path"] else ""
        out.append(
            {
                "chunk_id": c["chunk_id"] or f"semantic-{i}",
                "doc_id": file_path,
                "section": "",
                "text": text,
                "char_start": 0,
                "char_end": len(text),
                "source": file_path,
                "score": 0.0,
                "summary": text[:200] + ("..." if len(text) > 200 else ""),
                "full_length": len(text),
                "expandable": False,
                "semantic_hit": {"file_path": file_path, "reference_id": c["reference_id"]},
            }
        )
    return out


async def retrieve_code(
    meeting_id: str,
    query: str,
    top_k: int = 5,
    max_hops: int = 1,
) -> list[dict[str, Any]]:
    """代码检索：向量入口 + N 跳图扩展 + 语义层召回，候选统一交 reranker。

    结构层（ADR-016 Phase C）：向量管「语义入口」（召回种子符号 chunk），
    图管「结构扩展」（沿 CALLS/INHERITS 做 N 跳遍历，回答"谁调用它 / 它依赖谁"），
    两者级联而非替代（ADR-016 D4）。
    语义层（ADR-018 Phase C）：LightRAG 预处理文档的 naive chunk 召回并入候选池，
    与结构候选统一重排——语义层不可用时静默降级为纯结构检索。

    降级策略：
    - 会议无图索引 → 结构层退化为纯向量检索（等价 `retrieve`）。
    - 种子 chunk 非图节点（如纯文本 chunk）→ 跳过图扩展，仍作为向量候选返回。
    - 语义索引不存在/召回失败 → 跳过语义候选，不影响结构层结果。

    与 `retrieve`/`retrieve_for_conflict` 的区别：返回项中图扩展命中的 chunk 携带
    `graph_hit` 字段（hop/edge_type/via），语义层命中项携带 `semantic_hit` 字段
    （file_path/reference_id），供审计与解释性展示。
    """
    store = get_store(meeting_id)
    graph = get_graph(meeting_id)

    # 1. 向量召回种子（取更多候选，给图扩展 + 语义层 + reranker 留空间）
    search_k = max(top_k * 2, 10)
    seeds = await store.search(query, top_k=search_k) if store.all_chunks() else []

    # 候选池：种子打底，图扩展与语义召回追加（按 chunk_id 去重，种子优先）
    pool: dict[str, dict[str, Any]] = {chunk.chunk_id: _build_chunk_dict(chunk, score, store) for chunk, score in seeds}

    # 2. 图扩展：仅对命中图节点的种子沿 CALLS/INHERITS 做双向 N 跳扩展
    if graph is not None:
        for chunk, _score in seeds:
            if not graph.has_node(chunk.chunk_id):
                continue
            for hit in graph.expand(
                [chunk.chunk_id],
                max_hops=max_hops,
                edge_types={"CALLS", "INHERITS"},
                incoming=True,
                outgoing=True,
                include_seeds=False,
            ):
                if hit.node_id in pool:
                    continue
                related = store.get_chunk(hit.node_id)
                if related is None:
                    # file/doc 节点无对应 chunk（只有 symbol 有 chunk），跳过
                    continue
                d = _build_chunk_dict(related, 0.0, store)
                d["graph_hit"] = {
                    "hop": hit.hop,
                    "edge_type": hit.edge_type,
                    "via": hit.via,
                }
                pool[hit.node_id] = d

    # 3. 语义层召回并入候选池（键加 semantic: 前缀，防与结构层 chunk_id 撞键）
    for d in await _semantic_code_candidates(meeting_id, query, top_k=search_k):
        pool.setdefault(f"semantic:{d['chunk_id']}", d)

    base = list(pool.values())
    if not base:
        logger.debug("retrieve_code: 结构层与语义层均无候选，返回空列表 (meeting_id=%s)", meeting_id)
        return []

    # 排序为 reranker 提供稳定输入（图扩展/语义项初始分 0，排在种子之后）
    base.sort(key=lambda x: x["score"], reverse=True)

    # 4. reranker 融合（与 retrieve_for_conflict 一致性：真实 Reranker 失败回退初始分）
    reranker = get_reranker()
    documents = [c["text"] for c in base]
    try:
        reranked = await reranker.rerank(query, documents, top_n=top_k)
    except Exception as e:
        logger.error(
            "retrieve_code: reranker 重排异常，回退初始分排序: %s: %s",
            type(e).__name__,
            e,
        )
        return base[:top_k]

    results: list[dict[str, Any]] = []
    for idx, rel_score in reranked:
        if 0 <= idx < len(base):
            item = base[idx].copy()
            item["score"] = round(rel_score, 4)
            results.append(item)

    logger.info(
        "retrieve_code 完成: meeting_id=%s, 候选=%d(图扩展 %d, 语义 %d), 返回=%d, max_hops=%d",
        meeting_id,
        len(base),
        sum(1 for c in base if "graph_hit" in c),
        sum(1 for c in base if "semantic_hit" in c),
        len(results),
        max_hops,
    )
    return results
