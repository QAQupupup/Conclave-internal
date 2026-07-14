# Cross-team stage node (legacy wrapper)
# Phase 3：业务逻辑已下沉到 stage_runners.py，本文件保留兼容导出。
from __future__ import annotations

from typing import Any

from app.agents.compute import execute_think, build_cross_team_prompt
from app.agents.trace import set_current_trace
from app.models import MeetingState, Role

from app.orchestrator.stage_runners import run_cross_team
from ._helpers import _run_with_consistency, _resolve_model_for_call


async def cross_team_node(state: MeetingState) -> MeetingState:
    """CrossTeam 阶段：跨队辩论，暴露冲突点"""
    set_current_trace(state.llm_trace)

    async def call_fn(anchor: str) -> dict[str, Any]:
        req = build_cross_team_prompt(state.team_conclusions, anchor=anchor)
        req.model = _resolve_model_for_call(state, Role.MODERATOR.value, "cross_team")
        resp = await execute_think(req)
        return resp.result

    result, confidence = await _run_with_consistency(state, "cross_team", call_fn)
    return await run_cross_team(state, result, confidence)
