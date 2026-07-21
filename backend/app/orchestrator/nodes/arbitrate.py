# Arbitrate stage node (legacy wrapper)
# Phase 3：业务逻辑已下沉到 stage_runners.py，本文件保留兼容导出。
from __future__ import annotations

from typing import Any

from app.agents.compute import build_arbitrate_prompt, execute_think
from app.agents.trace import set_current_trace
from app.models import MeetingState, Role
from app.orchestrator.stage_runners import run_arbitrate

from ._helpers import _resolve_model_for_call, _run_with_consistency


async def arbitrate_node(state: MeetingState) -> MeetingState:
    """Arbitrate 阶段：仲裁者裁决，形成结论"""
    set_current_trace(state.llm_trace)

    async def call_fn(anchor: str) -> dict[str, Any]:
        req = build_arbitrate_prompt(state.evidence_set, anchor=anchor)
        req.model = _resolve_model_for_call(state, Role.MODERATOR.value, "arbitrate")
        resp = await execute_think(req)
        return resp.result

    result, confidence = await _run_with_consistency(state, "arbitrate", call_fn)
    return await run_arbitrate(state, result, confidence)
