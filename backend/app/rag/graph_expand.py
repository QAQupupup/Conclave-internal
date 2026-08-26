# 图扩展检索（ADR-016 Phase C）：向量入口命中节点 → 沿关系边 N 跳扩展
#
# 对应 ADR-016 D2「内存邻接表缓存」＋ Phase C.1「向量入口 + N 跳图扩展」。
# 纯内存实现，不依赖 DB / Qdrant / tree-sitter——由 CodeGraph 构建正向+反向邻接表，
# 后续 PG 递归 CTE 版本只需替换本类的数据源，接口不变。
#
# 向量管「语义入口」，图管「结构扩展」：检索时先用向量召回定位种子节点，
# 再调用 GraphIndex.expand 沿 CALLS/INHERITS/IMPORTS 做 N 跳扩展，扩展结果与
# 向量结果一起交 reranker 融合（ADR-016 D4 级联而非替代）。
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from app.rag.code_graph import CodeEdge, CodeGraph


@dataclass(frozen=True)
class GraphHit:
    """一次图扩展命中的节点（含跳数 + 来源边，供审计与加权）。"""

    node_id: str
    hop: int  # 0 = 种子节点，>0 = 第 N 跳
    edge_type: str  # 到达该节点所用的边类型；种子节点为 "SEED"
    via: str  # 上一跳节点 ID；种子节点为 ""


class GraphIndex:
    """内存邻接表图索引。

    由 CodeGraph 构建正向（src→dst）与反向（dst→src）邻接表，支持：
    - expand：从种子沿关系边做最多 max_hops 跳 BFS 扩展（可限边类型/方向）
    - callers：反向 CALLS，「谁调用它」
    - dependencies：正向扩展，「它调用/依赖谁」
    """

    def __init__(self, graph: CodeGraph) -> None:
        self._out: dict[str, list[CodeEdge]] = {}
        self._in: dict[str, list[CodeEdge]] = {}
        for e in graph.edges:
            self._out.setdefault(e.src, []).append(e)
            self._in.setdefault(e.dst, []).append(e)
        self.node_ids: frozenset[str] = frozenset({n.node_id for n in graph.nodes} | set(self._out) | set(self._in))

    def has_node(self, node_id: str) -> bool:
        return node_id in self.node_ids

    def edge_count(self) -> int:
        return sum(len(v) for v in self._out.values())

    def expand(
        self,
        seeds: Iterable[str],
        max_hops: int = 1,
        edge_types: Iterable[str] | None = None,
        *,
        incoming: bool = False,
        outgoing: bool = True,
        include_seeds: bool = True,
    ) -> list[GraphHit]:
        """从种子节点沿关系边做 BFS 扩展。

        Args:
            seeds: 种子节点 ID（向量召回命中的 chunk_id / symbol 限定名）。
            max_hops: 最大跳数（0 表示只返回种子）。
            edge_types: 限定参与扩展的边类型集合；None 表示不过滤。
            incoming: 沿反向边扩展（dst→src，如「谁调用它」）。
            outgoing: 沿正向边扩展（src→dst，如「它调用谁」）。
            include_seeds: 是否在结果中包含种子节点本身（hop=0）。

        Returns:
            按 BFS 层序排列的命中列表；种子已去重保序。环路安全：每节点只命中一次。
        """
        seeds = list(dict.fromkeys(seeds))  # 去重保序
        if max_hops < 0:
            max_hops = 0
        edge_filter = frozenset(edge_types) if edge_types is not None else None

        hits: list[GraphHit] = []
        visited: set[str] = set(seeds)  # 种子始终标记 visited，防环路回访

        if include_seeds:
            for s in seeds:
                hits.append(GraphHit(s, 0, "SEED", ""))
        if max_hops == 0:
            return hits

        frontier: list[str] = list(seeds)
        for hop in range(1, max_hops + 1):
            nxt: list[str] = []
            for node in frontier:
                if outgoing:
                    for e in self._out.get(node, []):
                        if edge_filter is not None and e.edge_type not in edge_filter:
                            continue
                        if e.dst not in visited:
                            visited.add(e.dst)
                            hits.append(GraphHit(e.dst, hop, e.edge_type, node))
                            nxt.append(e.dst)
                if incoming:
                    for e in self._in.get(node, []):
                        if edge_filter is not None and e.edge_type not in edge_filter:
                            continue
                        if e.src not in visited:
                            visited.add(e.src)
                            hits.append(GraphHit(e.src, hop, e.edge_type, node))
                            nxt.append(e.src)
            if not nxt:
                break
            frontier = nxt
        return hits

    def callers(self, symbol_id: str, max_hops: int = 1) -> list[GraphHit]:
        """反向 CALLS 扩展：「谁调用它」（不含自身）。"""
        return self.expand(
            [symbol_id],
            max_hops=max_hops,
            edge_types={"CALLS"},
            incoming=True,
            outgoing=False,
            include_seeds=False,
        )

    def dependencies(self, node_id: str, max_hops: int = 1, edge_types: Iterable[str] | None = None) -> list[GraphHit]:
        """正向扩展：「它调用/依赖谁」（不含自身，默认 CALLS + INHERITS）。"""
        if edge_types is None:
            edge_types = {"CALLS", "INHERITS"}
        return self.expand(
            [node_id],
            max_hops=max_hops,
            edge_types=edge_types,
            incoming=False,
            outgoing=True,
            include_seeds=False,
        )


# ---------------------------------------------------------------------------
# 会议级图索引注册表（对应 store.py 的 get_store 单例模式）
# ---------------------------------------------------------------------------

_graphs: dict[str, GraphIndex] = {}


def register_graph(meeting_id: str, graph: CodeGraph) -> GraphIndex:
    """为会议注册（覆盖）图索引；返回构建好的索引。"""
    idx = GraphIndex(graph)
    _graphs[meeting_id] = idx
    return idx


def unregister_graph(meeting_id: str) -> None:
    """注销会议的图索引（会议清理时调用）。"""
    _graphs.pop(meeting_id, None)


def get_graph(meeting_id: str) -> GraphIndex | None:
    """获取会议的图索引；未注册返回 None（调用方据此跳过图扩展）。"""
    return _graphs.get(meeting_id)


def structure_query(
    meeting_id: str,
    node_id: str,
    *,
    max_hops: int = 1,
) -> dict[str, object]:
    """结构查询：给定符号/文件节点，返回「谁调用它」与「它依赖谁」（ADR-016 Phase C.2）。

    这是图检索区别于纯向量检索的直接出口——向量回答"语义相似"，图回答"结构关系"。
    未注册图索引 / 节点不存在时返回空列表，方便调用方降级为纯向量结果。
    """
    idx = _graphs.get(meeting_id)
    if idx is None or not idx.has_node(node_id):
        return {"node_id": node_id, "callers": [], "dependencies": []}

    def _dump(hits: list[GraphHit]) -> list[dict[str, object]]:
        return [{"node_id": h.node_id, "hop": h.hop, "edge_type": h.edge_type, "via": h.via} for h in hits]

    return {
        "node_id": node_id,
        "callers": _dump(idx.callers(node_id, max_hops=max_hops)),
        "dependencies": _dump(idx.dependencies(node_id, max_hops=max_hops)),
    }
