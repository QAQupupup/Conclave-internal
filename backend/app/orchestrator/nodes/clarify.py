# Clarify stage node (legacy wrapper)
# Phase 3：业务逻辑已下沉到 stage_runners.py，本文件保留兼容导出。
from __future__ import annotations

from typing import Any

from app.agents.compute import build_clarify_prompt
from app.agents.trace import set_current_trace
from app.models import MeetingState, Role
from app.orchestrator.stage_runners import run_clarify

from ._helpers import _build_tool_registry, _run_stage_step


async def clarify_node(state: MeetingState) -> MeetingState:
    """Clarify 阶段：主持人澄清议题，确认团队组成，构造会议宪章"""
    set_current_trace(state.llm_trace)
    tool_registry = _build_tool_registry()

    def build_prompt(anchor: str, available_tools: Any) -> Any:
        return build_clarify_prompt(
            state.topic,
            state.doc_summaries,
            anchor=anchor,
            available_tools=available_tools,
            reference_context=state.reference_context,
        )

    result, confidence = await _run_stage_step(
        state,
        "clarify",
        Role.MODERATOR.value,
        build_prompt,
        tool_registry=tool_registry,
    )
    return await run_clarify(state, result, confidence)
