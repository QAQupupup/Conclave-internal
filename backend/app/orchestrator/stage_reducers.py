# § Stage Reducers：把 Scheduler 返回的子任务结果归约回 MeetingState
# Phase 2 过渡实现：reducer 直接委托给旧节点函数，保证行为不退化。
# Phase 3 将逐阶段替换为基于 AgentResult 的直接状态写入，并移除旧节点。
from __future__ import annotations

from typing import Any, Callable

from app.models import MeetingState


async def reduce_clarify(
    state: MeetingState,
    stage: str,
    results: dict[str, Any],
) -> MeetingState:
    """clarify 阶段归约"""
    from app.orchestrator.nodes.clarify import clarify_node

    return await clarify_node(state)


async def reduce_intra_team(
    state: MeetingState,
    stage: str,
    results: dict[str, Any],
) -> MeetingState:
    """intra_team 阶段归约"""
    from app.orchestrator.nodes.intra_team import intra_team_node

    return await intra_team_node(state)


async def reduce_cross_team(
    state: MeetingState,
    stage: str,
    results: dict[str, Any],
) -> MeetingState:
    """cross_team 阶段归约"""
    from app.orchestrator.nodes.cross_team import cross_team_node

    return await cross_team_node(state)


async def reduce_evidence_check(
    state: MeetingState,
    stage: str,
    results: dict[str, Any],
) -> MeetingState:
    """evidence_check 阶段归约"""
    from app.orchestrator.nodes.evidence_check import evidence_check_node

    return await evidence_check_node(state)


async def reduce_arbitrate(
    state: MeetingState,
    stage: str,
    results: dict[str, Any],
) -> MeetingState:
    """arbitrate 阶段归约"""
    from app.orchestrator.nodes.arbitrate import arbitrate_node

    return await arbitrate_node(state)


async def reduce_produce(
    state: MeetingState,
    stage: str,
    results: dict[str, Any],
) -> MeetingState:
    """produce 阶段归约"""
    from app.orchestrator.nodes.produce import produce_node

    return await produce_node(state)


_STAGE_REDUCERS: dict[str, Callable[[MeetingState, str, dict[str, Any]], Any]] = {
    "clarify": reduce_clarify,
    "intra_team": reduce_intra_team,
    "cross_team": reduce_cross_team,
    "evidence_check": reduce_evidence_check,
    "arbitrate": reduce_arbitrate,
    "produce": reduce_produce,
}


async def reduce_stage_results(
    state: MeetingState,
    stage: str,
    results: dict[str, Any],
) -> MeetingState:
    """根据阶段选择对应 reducer，将子任务结果写回 MeetingState"""
    reducer = _STAGE_REDUCERS.get(stage)
    if reducer is None:
        raise ValueError(f"阶段 {stage} 无对应结果归约器")
    return await reducer(state, stage, results)


def get_stage_reducer(stage: str) -> Callable[[MeetingState, str, dict[str, Any]], Any]:
    """获取阶段 reducer（兼容层，供 Manager 使用）"""
    reducer = _STAGE_REDUCERS.get(stage)
    if reducer is None:
        raise ValueError(f"阶段 {stage} 无对应结果归约器")
    return reducer
