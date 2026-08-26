# 代码语言感知切块测试（ADR-016 Phase B）
# 验证 chunks_from_graph / _chunk_text / _link_neighbors：
# 符号→Chunk、relations 填充、docstring 优先、同文件邻居链、跨文件隔离。
from __future__ import annotations

from app.rag.code_chunker import _chunk_text, chunks_from_graph
from app.rag.code_graph import CodeGraph, CodeNode


def _sym_node(qname: str, name: str, file: str, start_line: int, kind: str = "function", **meta) -> CodeNode:
    base = {
        "symbol_kind": kind,
        "start_line": start_line,
        "end_line": start_line,
        "signature": f"def {name}():",
        "docstring": "",
        "body_head": "",
    }
    base.update(meta)
    return CodeNode(node_id=qname, kind="symbol", name=name, file_path=file, language="python", metadata=base)


def _graph() -> CodeGraph:
    g = CodeGraph()
    g.add_node(CodeNode(node_id="a.py", kind="file", name="a.py", file_path="a.py", language="python"))
    g.add_node(CodeNode(node_id="b.py", kind="file", name="b.py", file_path="b.py", language="python"))
    # a.py 三个符号（start_line 5/10/20），b.py 一个符号
    g.add_node(_sym_node("a.py::Bar", "Bar", "a.py", 5, kind="class"))
    g.add_node(_sym_node("a.py::foo", "foo", "a.py", 10))
    g.add_node(_sym_node("a.py::bar", "bar", "a.py", 20))
    g.add_node(_sym_node("b.py::helper", "helper", "b.py", 1))
    # DEFINES
    for q in ("a.py::Bar", "a.py::foo", "a.py::bar"):
        g.add_edge("DEFINES", "a.py", q)
    g.add_edge("DEFINES", "b.py", "b.py::helper")
    # 关系边：bar 调用 foo；foo 继承 Bar（同文件）
    g.add_edge("CALLS", "a.py::bar", "a.py::foo", line=20)
    g.add_edge("INHERITS", "a.py::foo", "a.py::Bar", line=10)
    return g


class TestChunkText:
    def test_prefers_docstring_over_body_head(self) -> None:
        text = _chunk_text("def f():", "这是文档", "这是正文", "function")
        assert "这是文档" in text
        assert "这是正文" not in text

    def test_falls_back_to_body_head(self) -> None:
        assert "body" in _chunk_text("def f():", "", "body", "function")

    def test_truncates_overlong(self) -> None:
        text = _chunk_text("def f():", "x" * 3000, "", "function")
        assert text.endswith("…")
        assert len(text) <= 1200

    def test_empty_falls_back_to_kind_label(self) -> None:
        assert _chunk_text("", "", "", "class") == "class"


class TestChunksFromGraph:
    def test_only_symbol_nodes_become_chunks(self) -> None:
        chunks = chunks_from_graph(_graph())
        assert {c.chunk_id for c in chunks} == {"a.py::Bar", "a.py::foo", "a.py::bar", "b.py::helper"}

    def test_relations_filled_from_edges(self) -> None:
        by = {c.chunk_id: c for c in chunks_from_graph(_graph())}
        assert {"type": "CALLS", "target": "a.py::foo"} in by["a.py::bar"].relations
        assert {"type": "INHERITS", "target": "a.py::Bar"} in by["a.py::foo"].relations
        # helper 无出边 → 空 relations
        assert by["b.py::helper"].relations == []

    def test_metadata_propagated(self) -> None:
        by = {c.chunk_id: c for c in chunks_from_graph(_graph())}
        foo = by["a.py::foo"]
        assert foo.metadata["language"] == "python"
        assert foo.metadata["qualified_name"] == "a.py::foo"
        assert foo.metadata["start_line"] == 10
        assert foo.doc_id == "a.py"
        assert foo.source == "a.py:foo"

    def test_meeting_and_tenant_propagated(self) -> None:
        chunks = chunks_from_graph(_graph(), meeting_id="m1", tenant_id=3)
        assert chunks
        assert all(c.meeting_id == "m1" and c.tenant_id == 3 for c in chunks)


class TestNeighborLinking:
    def test_prev_next_within_file_sorted_by_line(self) -> None:
        by = {c.chunk_id: c for c in chunks_from_graph(_graph())}
        # a.py 按 start_line 排序：Bar(5) → foo(10) → bar(20)
        assert by["a.py::Bar"].next_id == "a.py::foo"
        assert by["a.py::Bar"].prev_id == ""
        assert by["a.py::foo"].prev_id == "a.py::Bar"
        assert by["a.py::foo"].next_id == "a.py::bar"
        assert by["a.py::bar"].prev_id == "a.py::foo"
        assert by["a.py::bar"].next_id == ""

    def test_neighbor_chain_cross_file_isolated(self) -> None:
        by = {c.chunk_id: c for c in chunks_from_graph(_graph())}
        # b.py 单独成链，不与 a.py 串接
        assert by["b.py::helper"].prev_id == ""
        assert by["b.py::helper"].next_id == ""


class TestEmptyGraph:
    def test_no_nodes_returns_empty(self) -> None:
        assert chunks_from_graph(CodeGraph()) == []
