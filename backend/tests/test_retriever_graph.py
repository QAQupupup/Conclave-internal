# 代码检索图扩展集成测试（ADR-016 Phase C）
# 验证 retrieve_code：向量入口 → 图扩展 → 图扩展结果带 graph_hit 交 reranker；
# 以及无图/无 chunk/图扩展命中非 chunk 节点的降级与跳过分支。
#
# store 用 MagicMock/AsyncMock 隔离（向量检索是既有依赖，非被测逻辑），
# 图索引用真实 CodeGraph + GraphIndex，命中真实 expand 逻辑。
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.rag.chunker import Chunk
from app.rag.code_graph import CodeGraph
from app.rag.graph_expand import GraphIndex
from app.rag.retriever import retrieve_code


def _chunk(chunk_id: str, text: str) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        doc_id="a.py",
        section=text,
        text=text,
        char_start=0,
        char_end=len(text),
        source=f"a.py:{chunk_id}",
    )


def _graph() -> CodeGraph:
    """A 调 B、D 调 B（B 的反向调用方 A/D）+ Child 继承 Base。"""
    g = CodeGraph()
    g.add_edge("CALLS", "a.py::A", "a.py::B")
    g.add_edge("CALLS", "a.py::D", "a.py::B")
    g.add_edge("INHERITS", "a.py::Child", "a.py::Base")
    return g


def _make_store(seed: Chunk, chunk_map: dict[str, Chunk]) -> MagicMock:
    """构造 mock store：search 返回既定种子，get_chunk 按映射取 chunk。"""
    store = MagicMock()
    store.all_chunks.return_value = [seed]
    store.search = AsyncMock(return_value=[(seed, 0.9)])
    store.get_chunk.side_effect = lambda nid: chunk_map.get(nid)
    store.get_neighbor_context.return_value = ""
    return store


def _preserve_order_reranker() -> MagicMock:
    """reranker mock：按输入顺序返回 top_n，保证结果确定性。"""
    r = MagicMock()
    r.rerank = AsyncMock(
        side_effect=lambda _q, docs, top_n=None: [(i, 1.0 - i * 0.1) for i in range(min(len(docs), top_n or len(docs)))]
    )
    return r


class TestRetrieveCode:
    @pytest.mark.asyncio
    async def test_no_chunks_returns_empty(self) -> None:
        store = MagicMock()
        store.all_chunks.return_value = []
        with patch("app.rag.retriever.get_store", return_value=store):
            assert await retrieve_code("m", "query") == []

    @pytest.mark.asyncio
    async def test_no_graph_degrades_to_seed_only(self) -> None:
        seed = _chunk("a.py::A", "def A(): pass")
        store = _make_store(seed, {"a.py::A": seed})
        reranker = _preserve_order_reranker()
        with (
            patch("app.rag.retriever.get_store", return_value=store),
            patch("app.rag.retriever.get_graph", return_value=None),
            patch("app.rag.retriever.get_reranker", return_value=reranker),
        ):
            results = await retrieve_code("m", "A", top_k=5)
        assert [r["chunk_id"] for r in results] == ["a.py::A"]
        assert all("graph_hit" not in r for r in results)

    @pytest.mark.asyncio
    async def test_expands_graph_neighbors_with_graph_hit(self) -> None:
        seed = _chunk("a.py::A", "def A(): pass")
        index = GraphIndex(_graph())
        store = _make_store(seed, {"a.py::A": seed, "a.py::B": _chunk("a.py::B", "def B(): pass")})
        reranker = _preserve_order_reranker()
        with (
            patch("app.rag.retriever.get_store", return_value=store),
            patch("app.rag.retriever.get_graph", return_value=index),
            patch("app.rag.retriever.get_reranker", return_value=reranker),
        ):
            results = await retrieve_code("m", "A", top_k=5, max_hops=1)

        by_id = {r["chunk_id"]: r for r in results}
        assert set(by_id) == {"a.py::A", "a.py::B"}
        # 种子无 graph_hit，图扩展的 B 携带 CALLS 来源元数据
        assert "graph_hit" not in by_id["a.py::A"]
        hit = by_id["a.py::B"]["graph_hit"]
        assert hit["edge_type"] == "CALLS"
        assert hit["hop"] == 1
        assert hit["via"] == "a.py::A"

    @pytest.mark.asyncio
    async def test_skips_related_node_without_chunk(self) -> None:
        seed = _chunk("a.py::A", "def A(): pass")
        index = GraphIndex(_graph())
        # B 相关但 get_chunk 返回 None（file/doc 节点无 chunk 场景）
        store = _make_store(seed, {"a.py::A": seed})
        reranker = _preserve_order_reranker()
        with (
            patch("app.rag.retriever.get_store", return_value=store),
            patch("app.rag.retriever.get_graph", return_value=index),
            patch("app.rag.retriever.get_reranker", return_value=reranker),
        ):
            results = await retrieve_code("m", "A", top_k=5, max_hops=1)
        assert [r["chunk_id"] for r in results] == ["a.py::A"]

    @pytest.mark.asyncio
    async def test_seed_not_graph_node_is_kept_as_vector_result(self) -> None:
        # 纯文本 chunk（无对应图节点）不参与扩展，但作为向量结果保留
        seed = _chunk("doc-0", "纯文本段落，无代码符号")
        index = GraphIndex(_graph())
        store = _make_store(seed, {"doc-0": seed})
        reranker = _preserve_order_reranker()
        with (
            patch("app.rag.retriever.get_store", return_value=store),
            patch("app.rag.retriever.get_graph", return_value=index),
            patch("app.rag.retriever.get_reranker", return_value=reranker),
        ):
            results = await retrieve_code("m", "文本", top_k=5, max_hops=1)
        assert [r["chunk_id"] for r in results] == ["doc-0"]
        assert all("graph_hit" not in r for r in results)
