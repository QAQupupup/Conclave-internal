# Arbitrate stage node (legacy wrapper)
# Phase 3：业务逻辑已下沉到 stage_runners.py，本文件保留兼容导出。
from __future__ import annotations

from typing import Any

from app.agents.compute import build_arbitrate_prompt
from app.agents.trace import set_current_trace
from app.models import MeetingState, Role
from app.orchestrator.stage_runners import run_arbitrate

from ._helpers import _build_tool_registry, _run_stage_step


async def arbitrate_node(state: MeetingState) -> MeetingState:
    """Arbitrate 阶段：仲裁者裁决，形成结论"""
    set_current_trace(state.llm_trace)
    tool_registry = _build_tool_registry()

    def build_prompt(anchor: str, available_tools: Any) -> Any:
        return build_arbitrate_prompt(
            state.evidence_set,
            anchor=anchor,
            available_tools=available_tools,
        )

    result, confidence = await _run_stage_step(
        state,
        "arbitrate",
        Role.MODERATOR.value,
        build_prompt,
        tool_registry=tool_registry,
    )
    return await run_arbitrate(state, result, confidence)
