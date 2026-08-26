# 图扩展检索测试（ADR-016 Phase C）
# 验证 GraphIndex.expand / callers / dependencies：方向、跳数、边类型过滤、
# 环路安全、种子去重、缺失节点、注册表。
from __future__ import annotations

from app.rag.code_graph import CodeGraph
from app.rag.graph_expand import (
    GraphIndex,
    get_graph,
    register_graph,
    structure_query,
    unregister_graph,
)


def _graph() -> CodeGraph:
    """A→B→C→A 环路 + D→B 多对一 + Child 继承 Base + 文件定义符号。"""
    g = CodeGraph()
    g.add_edge("CALLS", "a.py::A", "a.py::B")
    g.add_edge("CALLS", "a.py::B", "a.py::C")
    g.add_edge("CALLS", "a.py::C", "a.py::A")  # 环路回边
    g.add_edge("CALLS", "a.py::D", "a.py::B")
    g.add_edge("INHERITS", "a.py::Child", "a.py::Base")
    g.add_edge("DEFINES", "a.py", "a.py::A")
    g.add_edge("DEFINES", "a.py", "a.py::Child")
    return g


def _ids(hits) -> list[str]:
    return [h.node_id for h in hits]


class TestExpandDirection:
    def test_callers_reverse_calls(self) -> None:
        idx = GraphIndex(_graph())
        hits = idx.callers("a.py::B")
        assert _ids(hits) == ["a.py::A", "a.py::D"]  # 反向 CALLS，插入序
        assert all(h.edge_type == "CALLS" for h in hits)
        assert all(h.hop == 1 for h in hits)

    def test_dependencies_forward(self) -> None:
        idx = GraphIndex(_graph())
        hits = idx.dependencies("a.py::A", max_hops=1)
        assert _ids(hits) == ["a.py::B"]

    def test_file_defines_symbols(self) -> None:
        idx = GraphIndex(_graph())
        # 文件 → 符号（DEFINES 正向），改文件影响面
        hits = idx.expand(["a.py"], max_hops=1, edge_types={"DEFINES"}, include_seeds=False)
        assert set(_ids(hits)) == {"a.py::A", "a.py::Child"}


class TestHopsAndCycles:
    def test_multi_hop_and_cycle_safe(self) -> None:
        idx = GraphIndex(_graph())
        hits = idx.dependencies("a.py::A", max_hops=10)
        # B(1) → C(2)；C→A 回边因 A 已 visited 被跳过，不重复、不失控
        assert [h.hop for h in hits] == [1, 2]
        assert _ids(hits) == ["a.py::B", "a.py::C"]

    def test_callers_multi_hop(self) -> None:
        idx = GraphIndex(_graph())
        hits = idx.callers("a.py::A", max_hops=2)
        # 反向：C 调 A（1 跳），B 调 C（2 跳）
        assert [h.hop for h in hits] == [1, 2]
        assert _ids(hits) == ["a.py::C", "a.py::B"]


class TestEdgeFilter:
    def test_inherits_only(self) -> None:
        idx = GraphIndex(_graph())
        hits = idx.dependencies("a.py::Child", max_hops=1, edge_types={"INHERITS"})
        assert _ids(hits) == ["a.py::Base"]
        assert all(h.edge_type == "INHERITS" for h in hits)

    def test_all_edges_no_filter(self) -> None:
        idx = GraphIndex(_graph())
        # Child 只有 INHERITS 出边；无过滤也应只命中 Base
        hits = idx.expand(["a.py::Child"], max_hops=1)
        assert _ids(hits) == ["a.py::Child", "a.py::Base"]


class TestSeeds:
    def test_include_seeds(self) -> None:
        idx = GraphIndex(_graph())
        hits = idx.expand(["a.py::A"], max_hops=1, include_seeds=True)
        assert hits[0].node_id == "a.py::A"
        assert hits[0].hop == 0
        assert hits[0].edge_type == "SEED"
        assert hits[1].node_id == "a.py::B"
        assert hits[1].edge_type == "CALLS"

    def test_zero_hops_returns_seeds_only(self) -> None:
        idx = GraphIndex(_graph())
        hits = idx.expand(["a.py::A", "a.py::B"], max_hops=0)
        assert _ids(hits) == ["a.py::A", "a.py::B"]
        assert all(h.hop == 0 for h in hits)

    def test_seed_dedup_preserves_order(self) -> None:
        idx = GraphIndex(_graph())
        hits = idx.expand(["a.py::A", "a.py::A", "a.py::B"], max_hops=0)
        assert _ids(hits) == ["a.py::A", "a.py::B"]

    def test_empty_seeds(self) -> None:
        assert GraphIndex(_graph()).expand([]) == []

    def test_missing_node_no_crash(self) -> None:
        idx = GraphIndex(_graph())
        hits = idx.expand(["ghost::x"], max_hops=3)
        assert _ids(hits) == ["ghost::x"]
        assert idx.callers("ghost::x") == []


class TestRegistry:
    def test_register_get_unregister(self) -> None:
        idx = register_graph("m1", _graph())
        assert idx.edge_count() == 7
        assert get_graph("m1") is idx
        unregister_graph("m1")
        assert get_graph("m1") is None

    def test_unregistered_returns_none(self) -> None:
        # 隔离性：未注册的会议不返回索引
        assert get_graph("never-registered") is None


class TestStructureQuery:
    def test_callers_and_dependencies(self) -> None:
        register_graph("sm", _graph())
        r = structure_query("sm", "a.py::B")
        assert r["node_id"] == "a.py::B"
        assert [c["node_id"] for c in r["callers"]] == ["a.py::A", "a.py::D"]
        assert [d["node_id"] for d in r["dependencies"]] == ["a.py::C"]
        unregister_graph("sm")

    def test_unregistered_returns_empty(self) -> None:
        # 无图索引降级：返回空列表而非抛错（供调用方回退纯向量）
        r = structure_query("no-graph", "a.py::B")
        assert r["callers"] == []
        assert r["dependencies"] == []

    def test_missing_node_returns_empty(self) -> None:
        register_graph("sm2", _graph())
        r = structure_query("sm2", "ghost::x")
        assert r["callers"] == []
        assert r["dependencies"] == []
        unregister_graph("sm2")
