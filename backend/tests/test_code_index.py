# 代码索引编排测试（ADR-016 Phase C）
# 验证 _register_indexed（纯逻辑，脱离 tree-sitter）与 index_repo（真实解析 + 注册 + 入库）。
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.rag.chunker import Chunk
from app.rag.code_graph import CodeGraph
from app.rag.code_index import _register_indexed, index_repo
from app.rag.code_parser import tree_sitter_available
from app.rag.graph_expand import get_graph, unregister_graph
from app.rag.store import InMemoryVectorStore, StubEmbedding

_SAMPLE_PY = 'def foo():\n    """foo doc"""\n    return 1\n\n\ndef bar():\n    return foo()\n'


class TestRegisterIndexed:
    def test_registers_graph_and_reports_stats(self) -> None:
        g = CodeGraph()
        g.add_edge("CALLS", "a.py::A", "a.py::B")
        chunks = [Chunk(chunk_id="a.py::A", doc_id="a.py", section="A", text="", char_start=0, char_end=0)]

        stats = _register_indexed("idxm", chunks, g)

        assert stats == {"chunks": 1, "nodes": 0, "edges": 1}
        idx = get_graph("idxm")
        assert idx is not None
        assert idx.has_node("a.py::A")
        unregister_graph("idxm")


class TestIndexRepo:
    @pytest.mark.skipif(
        not tree_sitter_available(),
        reason="tree-sitter grammar 未安装时无法解析真实源码（已在 requirements.txt 声明，Docker CI 环境可运行）",
    )
    @pytest.mark.asyncio
    async def test_index_repo_parses_registers_and_stores(self, tmp_path) -> None:
        (tmp_path / "foo.py").write_text(_SAMPLE_PY, encoding="utf-8")
        mid = "idx-repo-test"
        unregister_graph(mid)

        # 隔离 store：本机可能未装 qdrant_client，用内存 store 验证编排流程
        # （Qdrant/memory 双存储的分派逻辑已在 store.py 单独测试）。
        mem_store = InMemoryVectorStore(embedding=StubEmbedding(), meeting_id=mid)
        with patch("app.rag.store.get_store", return_value=mem_store):
            stats = await index_repo(tmp_path, mid)

        assert stats["chunks"] == 2  # foo / bar 两个函数符号
        assert stats["nodes"] == 3  # 1 个 file + 2 个 symbol
        assert stats["edges"] == 3  # 2 条 DEFINES + 1 条 CALLS

        idx = get_graph(mid)
        assert idx is not None
        assert "foo.py::foo" in idx.node_ids
        assert "foo.py::bar" in idx.node_ids
        # bar 调用 foo 的关系已入图（向量管语义，图管结构）
        assert mem_store.get_chunk("foo.py::bar") is not None

        unregister_graph(mid)
