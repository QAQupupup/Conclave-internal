# § Stage Runners：阶段业务逻辑（与节点解耦）
# Phase 3：把原来散落在 nodes/*.py 中的状态更新逻辑集中到此处。
# Runner 不再依赖具体节点文件，只通过 MeetingManager -> Planner -> Scheduler -> Reducer -> StageRunner 驱动。
from __future__ import annotations

from typing import Any

from app.events import bus, make_event
from app.models import MeetingState, Role, Stage
from app.orchestrator.charter import build_charter_from_clarify
from app.orchestrator.state import next_stage as _next_stage, get_skipped_stages

from .stage_common import (
    compress_decisions_to_brief,
    emit_agent_spoke,
    format_arbitrate_as_text,
    record_drift,
)


async def run_clarify(state: MeetingState, result: dict[str, Any], confidence: str = "high") -> MeetingState:
    """Clarify 阶段：把 LLM 返回结果写回 MeetingState"""
    state.clarified_topic = result.get("clarified_topic", state.topic)
    state.key_questions = result.get("key_questions", [])
    state.team_config = result.get("team_config", [])
    state.charter = build_charter_from_clarify(
        meeting_id=state.meeting_id,
        original_topic=state.topic,
        clarified_topic=state.clarified_topic,
        key_questions=state.key_questions,
    )
    state.conclusion_chain.lock("clarify", result)
    state.confidence_flags["clarify"] = confidence

    topic_text = state.clarified_topic.rstrip("。.！!？?")
    summary = (
        f"议题已澄清：{topic_text}。"
        f"关键问题 {len(state.key_questions)} 个，团队 {len(state.team_config)} 人。"
    )
    await emit_agent_spoke(state, Role.MODERATOR, Stage.CLARIFY, summary)
    record_drift(state, Role.MODERATOR, Stage.CLARIFY, summary)

    complexity = result.get("complexity", "full")
    if complexity in ("simple", "standard", "full"):
        state.flow_plan = complexity
    depth_map = {"simple": "light", "standard": "standard", "full": "deep"}
    state.debate_depth = depth_map.get(complexity, "standard")

    await bus.publish(make_event(
        "flow_plan.set",
        state.meeting_id,
        {
            "flow_plan": state.flow_plan,
            "debate_depth": state.debate_depth,
            "skipped_stages": [s.value for s in get_skipped_stages(state.flow_plan)],
        },
    ))

    nxt = _next_stage(Stage.CLARIFY, state.flow_plan)
    state.stage = nxt or Stage.INTRA_TEAM
    return state


async def run_arbitrate(state: MeetingState, result: dict[str, Any], confidence: str = "high") -> MeetingState:
    """Arbitrate 阶段：把 LLM 返回结果写回 MeetingState"""
    decisions = result.get("decisions", [])
    adopted_claims = result.get("adopted_claims", [])

    # 无冲突时自动采纳所有 claims
    if not state.conflicts and not adopted_claims and state.claims:
        adopted_claims = [c.get("id", "") for c in state.claims if c.get("id")]

    state.decision_record = {
        "decisions": decisions,
        "adopted_claims": adopted_claims,
        "action_brief": compress_decisions_to_brief(
            {"decisions": decisions, "adopted_claims": adopted_claims},
            state.claims,
            state.conflicts,
            state.evidence_set,
        ),
    }
    state.conclusion_chain.lock("arbitrate", state.decision_record)
    state.confidence_flags["arbitrate"] = confidence

    content = format_arbitrate_as_text(state.decision_record, state.claims, state.conflicts)
    await emit_agent_spoke(state, Role.MODERATOR, Stage.ARBITRATE, content)
    record_drift(state, Role.MODERATOR, Stage.ARBITRATE, content)

    nxt = _next_stage(Stage.ARBITRATE, state.flow_plan)
    state.stage = nxt or Stage.PRODUCE
    return state
