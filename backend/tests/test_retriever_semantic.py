# 代码检索语义级联测试（ADR-018 Phase C）
# 验证 retrieve_code：LightRAG naive chunk 召回并入候选池，与结构层
# （向量种子 + 图扩展）候选统一交 reranker；语义层不可用/故障时静默降级。
#
# store/reranker 用 mock 隔离（既有依赖，非被测逻辑），语义索引用进程内
# fake（不触达 Qdrant/LLM），命中真实 _semantic_code_candidates 组装逻辑。
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from app.rag.chunker import Chunk
from app.rag.retriever import retrieve_code


class FakeSemanticIndex:
    """LightRAGIndex 测试替身：只覆盖检索级联用到的面（initialize/retrieve_chunks/close）。"""

    def __init__(self, chunks: list[dict[str, Any]] | None = None, fail: bool = False) -> None:
        self.chunks = chunks or []
        self.fail = fail
        self.initialized = 0
        self.closed = 0
        self.queries: list[tuple[str, int]] = []

    async def initialize(self) -> None:
        self.initialized += 1

    async def retrieve_chunks(self, question: str, top_k: int = 5) -> list[dict[str, Any]]:
        if self.fail:
            raise RuntimeError("qdrant unreachable")
        self.queries.append((question, top_k))
        return list(self.chunks)

    async def close(self) -> None:
        self.closed += 1


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


def _make_store(seed: Chunk | None) -> MagicMock:
    """构造 mock store：search 返回既定种子（无种子时 all_chunks 为空）。"""
    store = MagicMock()
    store.all_chunks.return_value = [seed] if seed else []
    store.search = AsyncMock(return_value=[(seed, 0.9)] if seed else [])
    store.get_neighbor_context.return_value = ""
    return store


def _preserve_order_reranker() -> MagicMock:
    """reranker mock：按输入顺序返回 (索引, 递减分)，保证结果确定性。"""
    r = MagicMock()
    r.rerank = AsyncMock(
        side_effect=lambda _q, docs, top_n=None: [(i, 1.0 - i * 0.1) for i in range(min(len(docs), top_n or len(docs)))]
    )
    return r


def _semantic_chunk(chunk_id: str, text: str, file_path_token: str) -> dict[str, Any]:
    return {"text": text, "file_path": file_path_token, "chunk_id": chunk_id, "reference_id": f"ref-{chunk_id}"}


class TestSemanticCascade:
    async def test_semantic_chunks_merged_into_pool_and_reranked(self) -> None:
        """语义候选与向量种子同池，统一交 reranker；命中项带 semantic_hit 元数据。"""
        seed = _chunk("a.py::A", "def A(): pass")
        fake = FakeSemanticIndex([_semantic_chunk("c-1", "语义召回的仓库概述文本", "src~docs~overview.md")])
        with (
            patch("app.rag.retriever.get_store", return_value=_make_store(seed)),
            patch("app.rag.retriever.get_graph", return_value=None),
            patch("app.rag.retriever.get_reranker", return_value=_preserve_order_reranker()),
            patch("app.rag.lightrag_adapter.get_semantic_index", return_value=fake),
        ):
            results = await retrieve_code("m", "仓库概述", top_k=5)

        by_id = {r["chunk_id"]: r for r in results}
        assert set(by_id) == {"a.py::A", "c-1"}
        # 语义命中：路径解码还原 + 溯源 ID + 不可展开（不在结构 store 中）
        hit = by_id["c-1"]["semantic_hit"]
        assert hit["file_path"] == "src/docs/overview.md"
        assert hit["reference_id"] == "ref-c-1"
        assert by_id["c-1"]["expandable"] is False
        assert by_id["c-1"]["doc_id"] == "src/docs/overview.md"
        # 向量种子不带语义标记
        assert "semantic_hit" not in by_id["a.py::A"]
        # 索引用毕关闭（不长期占用存储句柄）
        assert fake.initialized == 1
        assert fake.closed == 1

    async def test_semantic_unavailable_keeps_structural_results(self) -> None:
        """语义层不可用（工厂返回 None）→ 结构层结果原样返回，无额外开销。"""
        seed = _chunk("a.py::A", "def A(): pass")
        with (
            patch("app.rag.retriever.get_store", return_value=_make_store(seed)),
            patch("app.rag.retriever.get_graph", return_value=None),
            patch("app.rag.retriever.get_reranker", return_value=_preserve_order_reranker()),
            patch("app.rag.lightrag_adapter.get_semantic_index", return_value=None),
        ):
            results = await retrieve_code("m", "A", top_k=5)
        assert [r["chunk_id"] for r in results] == ["a.py::A"]
        assert all("semantic_hit" not in r for r in results)

    async def test_semantic_failure_degrades_to_structural(self) -> None:
        """非正向：语义召回异常 → 降级为纯结构检索，不抛错不阻断。"""
        seed = _chunk("a.py::A", "def A(): pass")
        fake = FakeSemanticIndex(fail=True)
        with (
            patch("app.rag.retriever.get_store", return_value=_make_store(seed)),
            patch("app.rag.retriever.get_graph", return_value=None),
            patch("app.rag.retriever.get_reranker", return_value=_preserve_order_reranker()),
            patch("app.rag.lightrag_adapter.get_semantic_index", return_value=fake),
        ):
            results = await retrieve_code("m", "A", top_k=5)
        assert [r["chunk_id"] for r in results] == ["a.py::A"]

    async def test_semantic_only_when_structural_store_empty(self) -> None:
        """结构层无 chunk（索引失败/未建）但语义索引存在 → 仍返回语义候选。"""
        fake = FakeSemanticIndex(
            [
                _semantic_chunk("c-1", "README 概述文本", "README.md"),
                _semantic_chunk("c-2", "部署说明文本", "docs~deploy.md"),
            ]
        )
        with (
            patch("app.rag.retriever.get_store", return_value=_make_store(None)),
            patch("app.rag.retriever.get_graph", return_value=None),
            patch("app.rag.retriever.get_reranker", return_value=_preserve_order_reranker()),
            patch("app.rag.lightrag_adapter.get_semantic_index", return_value=fake),
        ):
            results = await retrieve_code("m", "部署", top_k=5)
        assert [r["chunk_id"] for r in results] == ["c-1", "c-2"]
        assert all("semantic_hit" in r for r in results)

    async def test_both_layers_empty_returns_empty(self) -> None:
        """边界：结构层与语义层均无候选 → 空列表。"""
        with (
            patch("app.rag.retriever.get_store", return_value=_make_store(None)),
            patch("app.rag.retriever.get_graph", return_value=None),
            patch("app.rag.lightrag_adapter.get_semantic_index", return_value=FakeSemanticIndex()),
        ):
            assert await retrieve_code("m", "任意查询") == []

    async def test_semantic_chunk_id_collision_with_structural_is_kept_separate(self) -> None:
        """非正向（撞键防护）：语义 chunk_id 与结构 chunk_id 同名时互不顶掉。"""
        seed = _chunk("dup-id", "结构层文本")
        fake = FakeSemanticIndex([_semantic_chunk("dup-id", "语义层文本", "x.md")])
        with (
            patch("app.rag.retriever.get_store", return_value=_make_store(seed)),
            patch("app.rag.retriever.get_graph", return_value=None),
            patch("app.rag.retriever.get_reranker", return_value=_preserve_order_reranker()),
            patch("app.rag.lightrag_adapter.get_semantic_index", return_value=fake),
        ):
            results = await retrieve_code("m", "文本", top_k=5)
        # 两条同名 ID 的结果都保留（池键带 semantic: 前缀隔离）
        assert len(results) == 2
        assert sum(1 for r in results if "semantic_hit" in r) == 1
