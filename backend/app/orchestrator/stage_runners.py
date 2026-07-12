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


async def run_cross_team(state: MeetingState, result: dict[str, Any], confidence: str = "high") -> MeetingState:
    """CrossTeam 阶段：把 LLM 返回结果写回 MeetingState"""
    from app.orchestrator.nodes.borrow import _let_borrowed_agents_speak, _moderator_assess_borrow
    from app.orchestrator.nodes.evidence_check import _prefetch_evidence

    conflicts = result.get("conflicts", [])
    for c in conflicts:
        if "conflict_type" not in c and "type" in c:
            c["conflict_type"] = c.pop("type")
    state.conflicts = conflicts
    state.conclusion_chain.lock("cross_team", {"conflicts": conflicts})
    state.confidence_flags["cross_team"] = confidence

    if conflicts:
        conflict_lines = [f"跨队辩论结束，识别出 {len(conflicts)} 个争议点："]
        for i, cf in enumerate(conflicts, 1):
            ctype = cf.get("conflict_type", cf.get("type", "preference"))
            summary = cf.get("summary", "").strip()
            type_label = {"factual": "事实争议", "preference": "方案偏好", "scope": "范围界定"}.get(ctype, "争议")
            if summary:
                if len(summary) > 80:
                    summary = summary[:77] + "…"
                conflict_lines.append(f"  {i}. {type_label}：{summary}")
            else:
                side_a = cf.get("side_a", "")
                side_b = cf.get("side_b", "")
                conflict_lines.append(f"  {i}. {type_label}：{side_a[:30]} vs {side_b[:30]}")
        content = "\n".join(conflict_lines)
    else:
        consensus_lines = ["跨队辩论结束，各方观点高度一致，未发现争议点。"]
        consensus_lines.append("")
        consensus_lines.append("各方核心论点汇总：")
        role_labels = {
            "product_architect": "产品架构师",
            "engineer": "工程师",
            "security_expert": "安全专家",
            "ux_designer": "UX设计师",
            "data_engineer": "数据工程师",
            "marketing_expert": "市场专家",
            "moderator": "主持人",
        }
        displayed_count = 0
        for conclusion in state.team_conclusions:
            role_val = conclusion.get("role", "")
            role_name = role_labels.get(role_val, role_val)
            claims = conclusion.get("claims", [])
            if claims:
                consensus_lines.append(f"  【{role_name}】")
                for ci, c in enumerate(claims[:2], 1):
                    claim_text = c.get("claim", c.get("text", "")).strip()
                    if claim_text:
                        if len(claim_text) > 70:
                            claim_text = claim_text[:67] + "…"
                        consensus_lines.append(f"    {ci}. {claim_text}")
                displayed_count += 1
        if displayed_count == 0 and state.claims:
            for c in state.claims[:6]:
                role_val = c.get("agent_role", "")
                role_name = role_labels.get(role_val, role_val)
                claim_text = c.get("claim", c.get("text", "")).strip()
                if claim_text:
                    if len(claim_text) > 70:
                        claim_text = claim_text[:67] + "…"
                    consensus_lines.append(f"  • [{role_name}] {claim_text}")
        content = "\n".join(consensus_lines)

    await emit_agent_spoke(state, Role.MODERATOR, Stage.CROSS_TEAM, content)
    record_drift(state, Role.MODERATOR, Stage.CROSS_TEAM, content)

    if conflicts:
        state.prefetched_evidence = await _prefetch_evidence(state, conflicts)

    nxt = _next_stage(Stage.CROSS_TEAM, state.flow_plan)
    if nxt == Stage.EVIDENCE_CHECK and not conflicts and state.flow_plan == "standard":
        nxt = _next_stage(Stage.EVIDENCE_CHECK, state.flow_plan) or Stage.PRODUCE

    await _moderator_assess_borrow(state, Stage.CROSS_TEAM)
    await _let_borrowed_agents_speak(state, Stage.CROSS_TEAM)
    state.stage = nxt or Stage.PRODUCE
    return state
