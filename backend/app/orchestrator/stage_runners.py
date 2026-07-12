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
    format_claims_as_text,
    match_role,
    record_drift,
    worst_confidence,
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


async def run_intra_team(
    state: MeetingState,
    role_results: list[dict[str, Any]],
) -> MeetingState:
    """IntraTeam 阶段：聚合每个角色的 claims，更新 MeetingState。

    role_results 每项结构：
        {"role": str, "stance": str, "claims": list[dict], "confidence": str, "react": bool}
    """
    from app.orchestrator.nodes.borrow import _let_borrowed_agents_speak, _moderator_assess_borrow
    import uuid

    if not state.team_config:
        state.team_config = [
            {"role": "product_architect", "stance": "重价值与边界"},
            {"role": "engineer", "stance": "重可行性与风险"},
        ]

    # 按原始顺序整理成员，未匹配角色跳过
    members: list[tuple[Role, str]] = []
    seen_roles: set[Role] = set()
    for member in state.team_config:
        role_str = member.get("role", "")
        stance = member.get("stance", "")
        matched = match_role(role_str)
        if matched is not None and matched not in seen_roles:
            seen_roles.add(matched)
            members.append((matched, stance))
    if not members:
        members = [(Role.PRODUCT_ARCHITECT, "重价值与边界"), (Role.ENGINEER, "重可行性与风险")]

    conclusions: list[dict[str, Any]] = []
    worst_conf = "high"

    # 保证按 members 顺序处理结果，与 role_results 顺序一致（Scheduler 拓扑层保证）
    for (role, stance), rr in zip(members, role_results):
        conf = rr.get("confidence", "high")
        worst_conf = worst_confidence(worst_conf, conf)
        claims = rr.get("claims", [])
        claim_ids: list[str] = []
        for c in claims:
            cid = f"claim-{uuid.uuid4().hex[:8]}"
            c["id"] = cid
            c["agent_role"] = role.value
            state.claims.append(c)
            claim_ids.append(cid)
        conclusion = {"role": role.value, "stance": stance, "claims": claims}
        conclusions.append(conclusion)
        content = format_claims_as_text(claims, role.value)
        await emit_agent_spoke(state, role, Stage.INTRA_TEAM, content, claim_refs=claim_ids)
        record_drift(state, role, Stage.INTRA_TEAM, content)

    state.team_conclusions = conclusions
    state.conclusion_chain.lock("intra_team", {"claims": state.claims, "team_conclusions": conclusions})
    state.confidence_flags["intra_team"] = worst_conf

    await _moderator_assess_borrow(state, Stage.INTRA_TEAM)
    await _let_borrowed_agents_speak(state, Stage.INTRA_TEAM)

    nxt = _next_stage(Stage.INTRA_TEAM, state.flow_plan)
    state.stage = nxt or Stage.PRODUCE
    return state
