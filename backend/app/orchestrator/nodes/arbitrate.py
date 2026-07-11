# Arbitrate stage node
from __future__ import annotations

from typing import Any

from app.agents.compute import get_compute, build_arbitrate_prompt
from app.agents.trace import set_current_trace
from app.models import MeetingState, Role, Stage
from app.orchestrator.state import next_stage as _next_stage

from ._helpers import (
    _format_arbitrate_as_text,
    _emit_agent_spoke,
    _record_drift,
    _run_with_consistency,
)
from .produce import _compress_decisions_to_brief


async def arbitrate_node(state: MeetingState) -> MeetingState:
    """Arbitrate 阶段：仲裁者裁决，形成结论"""
    # 设置 trace 上下文
    set_current_trace(state.llm_trace)
    compute = get_compute()
    # 带一致性自检的 LLM 调用
    async def call_fn(anchor: str) -> dict[str, Any]:
        req = build_arbitrate_prompt(state.evidence_set, anchor=anchor)
        resp = await compute.think(req)
        return resp.result

    result, confidence = await _run_with_consistency(state, "arbitrate", call_fn)
    state.decision_record = {
        "decisions": result.get("decisions", []),
        "adopted_claims": result.get("adopted_claims", []),
    }
    # [CONVERGENCE] 将松散决策压缩为紧凑 action brief，注入 decision_record
    state.decision_record["action_brief"] = _compress_decisions_to_brief(
        state.decision_record, state.claims, state.conflicts, state.evidence_set
    )
    # 第2层：锁定 arbitrate 结论
    state.conclusion_chain.lock("arbitrate", state.decision_record)
    # 第5层：记录置信度
    state.confidence_flags["arbitrate"] = confidence
    content = _format_arbitrate_as_text(
        state.decision_record,
        state.claims,
        state.conflicts,
    )
    await _emit_agent_spoke(state, Role.MODERATOR, Stage.ARBITRATE, content)
    _record_drift(state, Role.MODERATOR, Stage.ARBITRATE, content)
    nxt = _next_stage(Stage.ARBITRATE, state.flow_plan)
    state.stage = nxt or Stage.PRODUCE
    return state
