# 代码语言感知切块（ADR-016 Phase B）：符号定义区间 → Chunk
#
# 复用 rag/chunker.py 的 Chunk（不新造字段），符号定义区间即结构边界（原则 1 ① 保真切块）。
# chunk 文本 = 签名 + (docstring 或 body 头部)，完整正文通过 char_start/char_end 懒读。
# relations 填 CALLS / INHERITS（同文件内唯一消歧后的关系，来自 code_graph 单一事实源）。
from __future__ import annotations

from pathlib import Path

from app.rag.chunker import Chunk
from app.rag.code_graph import CodeGraph, build_graph

# 符号 chunk 文本长度上限（超长截断 + 省略号，完整正文懒读）
MAX_CHUNK_TEXT = 1200


def _chunk_text(signature: str, docstring: str, body_head: str, symbol_kind: str) -> str:
    """组装符号的检索摘要文本。"""
    kind_label = {"class": "class", "method": "method", "function": "function", "type": "type"}.get(
        symbol_kind, "symbol"
    )
    parts: list[str] = []
    if signature:
        parts.append(signature)
    if docstring:
        parts.append(docstring)
    elif body_head:
        parts.append(body_head)
    text = "\n".join(p for p in parts if p)
    if not text:
        text = f"{kind_label}"
    if len(text) > MAX_CHUNK_TEXT:
        # 预留 1 字符给省略号，保证截断后总长 ≤ MAX_CHUNK_TEXT
        text = text[: MAX_CHUNK_TEXT - 1].rstrip() + "…"
    return text


def chunks_from_graph(graph: CodeGraph, meeting_id: str = "", tenant_id: int | None = None) -> list[Chunk]:
    """由构图结果生成 Chunk 列表（符号切块 + relations 填充 + 同文件邻居链）。

    事实源：graph 节点携带签名/docstring/body/行区间，edges 携带 CALLS/INHERITS 关系。
    """
    # 出边索引：src -> [(edge_type, dst)]
    out_edges: dict[str, list[tuple[str, str]]] = {}
    for e in graph.edges:
        if e.edge_type in ("CALLS", "INHERITS"):
            out_edges.setdefault(e.src, []).append((e.edge_type, e.dst))

    chunks: list[Chunk] = []
    for n in graph.nodes:
        if n.kind != "symbol":
            continue
        meta = n.metadata
        text = _chunk_text(
            meta.get("signature", ""),
            meta.get("docstring", ""),
            meta.get("body_head", ""),
            meta.get("symbol_kind", "symbol"),
        )
        relations = [{"type": etype, "target": dst} for etype, dst in out_edges.get(n.node_id, [])]
        chunks.append(
            Chunk(
                chunk_id=n.node_id,
                doc_id=n.file_path,
                section=n.name,
                text=text,
                char_start=meta.get("char_start", 0),
                char_end=meta.get("char_end", 0),
                source=f"{n.file_path}:{n.name}",
                metadata={
                    "language": n.language,
                    "symbol_kind": meta.get("symbol_kind", "symbol"),
                    "qualified_name": n.node_id,
                    "class_name": meta.get("class_name", ""),
                    "start_line": meta.get("start_line", 0),
                    "end_line": meta.get("end_line", 0),
                },
                relations=relations,
                tenant_id=tenant_id,
                meeting_id=meeting_id,
            )
        )

    return _link_neighbors(chunks)


def _link_neighbors(chunks: list[Chunk]) -> list[Chunk]:
    """同文件内按定义行区间排序建立邻居链（看上下文用）。"""
    by_file: dict[str, list[Chunk]] = {}
    for c in chunks:
        by_file.setdefault(c.doc_id, []).append(c)
    for file_chunks in by_file.values():
        file_chunks.sort(key=lambda c: c.metadata.get("start_line", 0))
        for i, c in enumerate(file_chunks):
            if i > 0:
                c.prev_id = file_chunks[i - 1].chunk_id
            if i < len(file_chunks) - 1:
                c.next_id = file_chunks[i + 1].chunk_id
    return chunks


def chunk_repo(
    repo_root: str | Path, meeting_id: str = "", tenant_id: int | None = None
) -> tuple[list[Chunk], CodeGraph]:
    """扫描仓库并生成符号切块 + 图（Phase B 仓级入口）。

    Returns:
        (chunks, graph)：chunks 供向量入库，graph 供关系存储/多跳检索。
    """
    graph = build_graph(Path(repo_root))
    chunks = chunks_from_graph(graph, meeting_id=meeting_id, tenant_id=tenant_id)
    return chunks, graph
