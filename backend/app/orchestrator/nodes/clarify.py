# Clarify stage node (legacy wrapper)
# Phase 3：业务逻辑已下沉到 stage_runners.py，本文件保留兼容导出。
from __future__ import annotations

from typing import Any

from app.agents.compute import get_compute, build_clarify_prompt
from app.agents.trace import set_current_trace
from app.models import MeetingState, Role

from ._helpers import _run_with_consistency, _resolve_model_for_call
from app.orchestrator.stage_runners import run_clarify


async def clarify_node(state: MeetingState) -> MeetingState:
    """Clarify 阶段：主持人澄清议题，确认团队组成，构造会议宪章"""
    set_current_trace(state.llm_trace)
    compute = get_compute()

    async def call_fn(anchor: str) -> dict[str, Any]:
        req = build_clarify_prompt(
            state.topic,
            state.doc_summaries,
            anchor=anchor,
            reference_context=state.reference_context,
        )
        req.model = _resolve_model_for_call(state, Role.MODERATOR.value, "clarify")
        resp = await compute.think(req)
        return resp.result

    result, confidence = await _run_with_consistency(state, "clarify", call_fn)
    return await run_clarify(state, result, confidence)
