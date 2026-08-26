# 代码图构图测试（ADR-016 Phase B）
# 验证 build_graph_from_parsed：DEFINES/CALLS/INHERITS 落边规则、
# 同名消歧、跨文件拒解析、unsupported 跳过、import 元数据。
from __future__ import annotations

from app.rag.code_graph import build_graph_from_parsed, is_doc_file
from app.rag.code_parser import CallRef, ImportRef, InheritRef, ParsedFile, Symbol


def _sym(name: str, kind: str, qname: str) -> Symbol:
    return Symbol(
        name=name,
        kind=kind,
        qualified_name=qname,
        class_name="",
        start_line=1,
        end_line=1,
        char_start=0,
        char_end=0,
        text=name,
        signature=f"def {name}():",
        docstring="",
    )


class TestDefines:
    def test_defines_edges_and_nodes(self) -> None:
        pf = ParsedFile(
            path="a.py",
            language="python",
            symbols=[_sym("foo", "function", "a.py::foo"), _sym("bar", "function", "a.py::bar")],
        )
        g = build_graph_from_parsed([pf])
        defines = [e for e in g.edges if e.edge_type == "DEFINES"]
        assert {e.dst for e in defines} == {"a.py::foo", "a.py::bar"}
        assert {n.kind for n in g.nodes} == {"file", "symbol"}
        assert len([n for n in g.nodes if n.kind == "symbol"]) == 2


class TestCalls:
    def test_unique_resolution(self) -> None:
        pf = ParsedFile(
            path="a.py",
            language="python",
            symbols=[_sym("foo", "function", "a.py::foo"), _sym("bar", "function", "a.py::bar")],
            calls=[CallRef(caller_qualified="a.py::bar", callee_name="foo", line=2)],
        )
        g = build_graph_from_parsed([pf])
        calls = [e for e in g.edges if e.edge_type == "CALLS"]
        assert len(calls) == 1
        assert calls[0].src == "a.py::bar"
        assert calls[0].dst == "a.py::foo"

    def test_self_recursion_preserved(self) -> None:
        pf = ParsedFile(
            path="a.py",
            language="python",
            symbols=[_sym("fact", "function", "a.py::fact")],
            calls=[CallRef(caller_qualified="a.py::fact", callee_name="fact", line=2)],
        )
        g = build_graph_from_parsed([pf])
        calls = [e for e in g.edges if e.edge_type == "CALLS"]
        assert len(calls) == 1
        assert calls[0].src == calls[0].dst == "a.py::fact"

    def test_ambiguous_skipped(self) -> None:
        # 同文件两个同名符号：按简单名无法唯一消歧 → 不落边（防错连，Phase C 再消歧）
        pf = ParsedFile(
            path="a.py",
            language="python",
            symbols=[_sym("foo", "function", "a.py::A::foo"), _sym("foo", "method", "a.py::B::foo")],
            calls=[CallRef(caller_qualified="a.py::A::foo", callee_name="foo", line=1)],
        )
        g = build_graph_from_parsed([pf])
        assert not any(e.edge_type == "CALLS" for e in g.edges)

    def test_cross_file_not_resolved(self) -> None:
        # 被叫名不在同文件 → 不落边（跨文件 import 解析属 Phase C）
        pf = ParsedFile(
            path="a.py",
            language="python",
            symbols=[_sym("bar", "function", "a.py::bar")],
            calls=[CallRef(caller_qualified="a.py::bar", callee_name="other.foo", line=1)],
        )
        g = build_graph_from_parsed([pf])
        assert not any(e.edge_type == "CALLS" for e in g.edges)


class TestInherits:
    def test_resolves_class_only(self) -> None:
        pf = ParsedFile(
            path="a.py",
            language="python",
            symbols=[_sym("Base", "class", "a.py::Base"), _sym("Child", "class", "a.py::Child")],
            inherits=[InheritRef(class_qualified="a.py::Child", base_name="Base", line=2)],
        )
        g = build_graph_from_parsed([pf])
        inh = [e for e in g.edges if e.edge_type == "INHERITS"]
        assert len(inh) == 1
        assert inh[0].src == "a.py::Child"
        assert inh[0].dst == "a.py::Base"

    def test_base_not_a_class_skipped(self) -> None:
        # 基类名命中一个 function（非 class）→ 不落 INHERITS 边
        pf = ParsedFile(
            path="a.py",
            language="python",
            symbols=[_sym("X", "function", "a.py::X"), _sym("Child", "class", "a.py::Child")],
            inherits=[InheritRef(class_qualified="a.py::Child", base_name="X", line=2)],
        )
        g = build_graph_from_parsed([pf])
        assert not any(e.edge_type == "INHERITS" for e in g.edges)


class TestGuardRails:
    def test_unsupported_file_skipped(self) -> None:
        pf = ParsedFile(path="x.cpp", language="", supported=False, error="unsupported_extension")
        g = build_graph_from_parsed([pf])
        assert g.nodes == []
        assert g.edges == []

    def test_imports_recorded_in_file_metadata(self) -> None:
        pf = ParsedFile(
            path="a.py",
            language="python",
            imports=[ImportRef(module="os", alias=None, line=1)],
            symbols=[],
        )
        g = build_graph_from_parsed([pf])
        file_node = next(n for n in g.nodes if n.kind == "file")
        assert file_node.metadata["imports"] == ["os"]


class TestDocDetection:
    def test_is_doc_file(self) -> None:
        from pathlib import Path

        assert is_doc_file(Path("README.md"))
        assert is_doc_file(Path("docs/design.md"))
        assert not is_doc_file(Path("a.py"))
