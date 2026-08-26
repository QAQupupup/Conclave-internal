# 代码索引编排（ADR-016 Phase C）：摄入 → 构图 → 切块 → 注册图索引 + 向量入库
#
# 把 Phase A 的「导入」与 Phase B 的「解析/构图/切块」接到一起，让已摄入的
# 代码仓库真正进入 RAG：符号 chunk 走向量（复用 store.py），关系边走内存图索引
# （graph_expand.py 注册表），检索时向量管语义入口、图管结构扩展（ADR-016 D4）。
#
# 设计要点：
# - tree-sitter 解析/构图是 CPU 密集同步操作，用 asyncio.to_thread 隔离线程，
#   避免阻塞事件循环（asyncio.to_thread 会自动复制 contextvars 上下文，
#   租户上下文可穿透到 worker 线程）。
# - 索引入口幂等：可对同一 meeting 重复索引（覆盖式注册图 + 追加向量，见
#   store.add_chunks 与 register_graph 语义），供「重新索引」场景。
from __future__ import annotations

import asyncio
from pathlib import Path

from app.logging_config import get_logger
from app.rag.chunker import Chunk
from app.rag.code_chunker import chunk_repo
from app.rag.code_graph import CodeGraph
from app.rag.graph_expand import register_graph

logger = get_logger("rag.code_index")


def _register_indexed(meeting_id: str, chunks: list[Chunk], graph: CodeGraph) -> dict[str, int]:
    """把构图 + 切块结果注册到会议级图索引（同步纯逻辑，可脱离 tree-sitter 单测）。

    返回索引统计（chunks / nodes / edges），供网关返回与日志审计。
    """
    register_graph(meeting_id, graph)
    return {
        "chunks": len(chunks),
        "nodes": len(graph.nodes),
        "edges": len(graph.edges),
    }


async def index_repo(
    repo_root: str | Path,
    meeting_id: str,
) -> dict[str, int]:
    """对已摄入的代码仓库做「构图 + 切块 + 注册图 + 向量入库」。

    Args:
        repo_root: 已摄入仓库的绝对路径（workspace/{meeting_id}/{repo}）。
        meeting_id: 会议作用域，决定图索引与向量库的隔离边界。

    Returns:
        索引统计 dict（chunks / nodes / edges）。
    """
    repo_root = Path(repo_root).resolve()

    # CPU 密集的 tree-sitter 解析 + 构图放到线程池，避免阻塞事件循环。
    # asyncio.to_thread 内部用 contextvars.copy_context() 运行，租户上下文可穿透。
    chunks, graph = await asyncio.to_thread(chunk_repo, repo_root, meeting_id)

    stats = _register_indexed(meeting_id, chunks, graph)

    # 符号 chunk 向量入库（批量 embedding + 多租户盖章在 store.add_chunks 内完成）
    from app.rag.store import get_store

    store = get_store(meeting_id)
    await store.add_chunks(chunks)

    logger.info(
        "代码索引完成 meeting_id=%s chunks=%d nodes=%d edges=%d",
        meeting_id,
        stats["chunks"],
        stats["nodes"],
        stats["edges"],
    )
    return stats
