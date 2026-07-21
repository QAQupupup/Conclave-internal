# Pipeline stage nodes package
# Re-exports maintain backward compatibility with the old monolithic nodes.py module.
from __future__ import annotations

from app.models import Stage

from ._helpers import Node, _match_role
from .arbitrate import arbitrate_node
from .borrow import _let_borrowed_agents_speak
from .clarify import clarify_node
from .cross_team import cross_team_node
from .evidence_check import evidence_check_node
from .intra_team import intra_team_node
from .produce import produce_node
from .routing import _inc_loop_count, decide_next_stage

# Public alias (without underscore prefix)
let_borrowed_agents_speak = _let_borrowed_agents_speak

# 节点注册表：阶段 -> 节点函数
NODES: dict[Stage, Node] = {
    Stage.CLARIFY: clarify_node,
    Stage.INTRA_TEAM: intra_team_node,
    Stage.CROSS_TEAM: cross_team_node,
    Stage.EVIDENCE_CHECK: evidence_check_node,
    Stage.ARBITRATE: arbitrate_node,
    Stage.PRODUCE: produce_node,
}

__all__ = [
    "NODES",
    "_inc_loop_count",
    "_let_borrowed_agents_speak",
    # Helpers (used by tests and runner)
    "_match_role",
    "arbitrate_node",
    # Individual nodes
    "clarify_node",
    "cross_team_node",
    "decide_next_stage",
    "evidence_check_node",
    "intra_team_node",
    "let_borrowed_agents_speak",
    "produce_node",
]
