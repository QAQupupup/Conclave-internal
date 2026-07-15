# § Stage Runners：阶段业务逻辑（与节点解耦）
# Phase 3：把原来散落在 nodes/*.py 中的状态更新逻辑集中到此处。
# Runner 不再依赖具体节点文件，只通过 MeetingManager -> Planner -> Scheduler -> Reducer -> StageRunner 驱动。
#
# 辅助函数已全部提取到 orchestrator/ 层独立模块：
#   - borrow_helpers.py: _let_borrowed_agents_speak, _moderator_assess_borrow
#   - evidence_helpers.py: _prefetch_evidence, _collect_evidence
#   - produce_helpers.py: _scan_artifacts, _emit_progress
# nodes/ 层保留 re-export 以向后兼容。
from __future__ import annotations

from typing import Any

from app.events import bus, make_event
from app.logging_config import get_logger
from app.models import MeetingState, MeetingStatus, Role, Stage
from conclave_core.charter import build_charter_from_clarify
from conclave_core.conclusion_logic import lock_conclusion
from conclave_core.confidence import worst_confidence
from conclave_core.roles import match_role
from conclave_core.state import get_skipped_stages, next_stage as _next_stage
from conclave_core.text import (
    compress_decisions_to_brief,
    format_arbitrate_as_text,
    format_claims_as_text,
)

from .stage_common import emit_agent_spoke, record_drift

_logger = get_logger("orchestrator.stage_runners")


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
    lock_conclusion(state.conclusion_chain, "clarify", result)
    state.confidence_flags["clarify"] = confidence

    topic_text = state.clarified_topic.rstrip("。.！!？?")
    summary = (
        f"议题已澄清：{topic_text}。"
        f"关键问题 {len(state.key_questions)} 个，团队 {len(state.team_config)} 人。"
    )
    await emit_agent_spoke(state, Role.MODERATOR, Stage.CLARIFY, summary)
    record_drift(state, Role.MODERATOR, Stage.CLARIFY, summary)

    complexity = result.get("complexity", "full")
    # 若意图分流已判定为 plan（先计划后执行），则保留 plan 模式不被 clarify 覆盖
    if state.flow_plan == "plan":
        state.debate_depth = "deep"
    elif complexity in ("simple", "standard", "full"):
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
    lock_conclusion(state.conclusion_chain, "arbitrate", state.decision_record)
    state.confidence_flags["arbitrate"] = confidence

    content = format_arbitrate_as_text(state.decision_record, state.claims, state.conflicts)
    await emit_agent_spoke(state, Role.MODERATOR, Stage.ARBITRATE, content)
    record_drift(state, Role.MODERATOR, Stage.ARBITRATE, content)

    nxt = _next_stage(Stage.ARBITRATE, state.flow_plan)
    state.stage = nxt or Stage.PRODUCE
    return state


async def run_cross_team(state: MeetingState, result: dict[str, Any], confidence: str = "high") -> MeetingState:
    """CrossTeam 阶段：把 LLM 返回结果写回 MeetingState"""
    from app.orchestrator.borrow_helpers import _let_borrowed_agents_speak, _moderator_assess_borrow
    from app.orchestrator.evidence_helpers import _prefetch_evidence

    conflicts = result.get("conflicts", [])
    for c in conflicts:
        if "conflict_type" not in c and "type" in c:
            c["conflict_type"] = c.pop("type")
    state.conflicts = conflicts
    lock_conclusion(state.conclusion_chain, "cross_team", {"conflicts": conflicts})
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
    from app.orchestrator.borrow_helpers import _let_borrowed_agents_speak, _moderator_assess_borrow
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
    lock_conclusion(state.conclusion_chain, "intra_team", {"claims": state.claims, "team_conclusions": conclusions})
    state.confidence_flags["intra_team"] = worst_conf

    await _moderator_assess_borrow(state, Stage.INTRA_TEAM)
    await _let_borrowed_agents_speak(state, Stage.INTRA_TEAM)

    nxt = _next_stage(Stage.INTRA_TEAM, state.flow_plan)
    state.stage = nxt or Stage.PRODUCE
    return state


async def run_evidence_check(
    state: MeetingState,
    conflict_results: list[dict[str, Any]],
) -> MeetingState:
    """EvidenceCheck 阶段：聚合每个冲突的 LLM 判断结果，更新 MeetingState。

    conflict_results 每项结构：
        {
            "conflict": dict,
            "evidence_chunks": list[dict],
            "result": dict,         # LLM 返回的 evidence_assessments
            "confidence": str,
        }
    """
    from app.orchestrator.borrow_helpers import _let_borrowed_agents_speak

    worst_conf = "high"
    evidence_set: list[dict[str, Any]] = []

    for cr in conflict_results:
        conflict = cr.get("conflict", {})
        result = cr.get("result", {})
        confidence = cr.get("confidence", "high")
        cid = conflict.get("id", "c0")
        worst_conf = worst_confidence(worst_conf, confidence)
        assessments = result.get("evidence_assessments", [])
        es = {
            "conflict_id": result.get("conflict_id", cid),
            "assessments": assessments,
        }
        evidence_set.append(es)

        for a in assessments:
            await bus.publish(
                make_event(
                    "evidence.attached",
                    state.meeting_id,
                    {
                        "meeting_id": state.meeting_id,
                        "conflict_id": es["conflict_id"],
                        "quote": a.get("quote", ""),
                        "source": a.get("source", ""),
                        "supports": a.get("supports", "neutral"),
                    },
                )
            )

    state.evidence_set = evidence_set
    lock_conclusion(state.conclusion_chain, "evidence_check", {"evidence_set": evidence_set})
    state.confidence_flags["evidence_check"] = worst_conf

    total_ev = sum(len(es.get("assessments", [])) for es in evidence_set)
    supporting = sum(
        1 for es in evidence_set
        for a in es.get("assessments", [])
        if a.get("supports") in ("a", "b")
    )
    neutral = total_ev - supporting
    summary = (
        f"证据对照完成：共检索 {total_ev} 条证据，"
        f"其中 {supporting} 条明确支持某一方观点，{neutral} 条为中性/通用知识。"
    )
    await emit_agent_spoke(state, Role.MODERATOR, Stage.EVIDENCE_CHECK, summary)

    await _let_borrowed_agents_speak(state, Stage.EVIDENCE_CHECK)
    nxt = _next_stage(Stage.EVIDENCE_CHECK, state.flow_plan)
    state.stage = nxt or Stage.PRODUCE
    return state


async def run_produce(
    state: MeetingState,
    confidence: str = "high",
) -> MeetingState:
    """Produce 阶段：收尾状态写入、事件发布、漂移检查、终态设置。

    注意：artifact 构建、沙箱执行/部署等复杂逻辑仍保留在 produce.py 中。
    本函数仅负责 artifact 已构建完成后的统一收尾。
    """
    import json
    from pathlib import Path

    from app.config import settings

    # 附件扫描：代码/服务类产出收集工作区文件
    if state.deliverable_type in ("code_analysis", "tested_system", "deployable_service"):
        ws_root = Path(settings.workspace_root) / state.meeting_id
        try:
            from app.orchestrator.produce_helpers import _scan_artifacts
            attachments = _scan_artifacts(ws_root, state.meeting_id)
            if attachments:
                state.artifact["attachments"] = attachments
                _logger.info(
                    f"produce: 扫描到 {len(attachments)} 个附件文件",
                    extra={"attachment_files": [a["filename"] for a in attachments]},
                )
        except Exception as e:
            _logger.warning(f"produce: 附件扫描失败（不影响主流程）: {e}")

    # 锁定 produce 结论
    lock_conclusion(state.conclusion_chain, "produce", state.artifact)
    state.confidence_flags["produce"] = confidence

    prd = state.artifact.get("prd", {})
    openapi = state.artifact.get("openapi", "")
    _logger.info(
        "produce: artifact 已构造, 锁定结论完成",
        extra={
            "prd_title": prd.get("title", "?") if isinstance(prd, dict) else "?",
            "openapi_len": len(openapi) if isinstance(openapi, str) else 0,
            "deliverable_type": state.deliverable_type,
        },
    )

    # 发布 artifact.generated 事件
    await bus.publish(
        make_event(
            "artifact.generated",
            state.meeting_id,
            {
                "meeting_id": state.meeting_id,
                "deliverable_type": state.deliverable_type,
                "prd": prd,
                "openapi": openapi,
            },
        )
    )

    # 发送进度：产出完成
    try:
        from app.orchestrator.produce_helpers import _emit_progress
        await _emit_progress(state, "done", "产出物生成完成！", 100)
    except Exception as e:
        _logger.warning(f"produce: 进度事件发送失败（不影响主流程）: {e}")

    # 漂移检查
    artifact_text = json.dumps(state.artifact, ensure_ascii=False, default=str)
    record_drift(state, Role.MODERATOR, Stage.PRODUCE, artifact_text)

    # 终态
    from datetime import datetime, timezone
    state.stage = Stage.PRODUCE
    state.status = MeetingStatus.DONE
    state.completed_at = datetime.now(timezone.utc)
    _logger.info("produce: 状态已设为 DONE")

    # LLM 降级检测
    fallback_stages = [s for s, flag in state.confidence_flags.items() if flag == "fallback"]
    if fallback_stages:
        await bus.publish(make_event(
            "meeting.fallback_warning",
            state.meeting_id,
            {
                "fallback_stages": fallback_stages,
                "message": f"以下阶段使用了降级数据（非真实 LLM 输出）：{', '.join(fallback_stages)}。产出物可能不可靠，请谨慎参考。",
                "severity": "warning",
            },
        ))
        _logger.warning(f"会议完成但有 {len(fallback_stages)} 个阶段降级：{fallback_stages}")

    # 记忆提取
    try:
        from app.memory.profile import trigger_extraction
        await trigger_extraction(state)
        _logger.info("produce: 记忆提取完成")
    except Exception as e:
        _logger.warning(f"produce: 记忆提取失败（不影响主流程）: {e}")

    # Agent 反馈闭环
    try:
        from app.agents.feedback import evaluate_agents
        evaluations = await evaluate_agents(state)
        if evaluations:
            _logger.info(
                f"produce: Agent 评估完成 — {len(evaluations)} 个角色, "
                f"top={max(evaluations.items(), key=lambda x: x[1]['overall_score'])[0]}",
            )
    except Exception as fb_err:
        _logger.warning(f"produce: Agent 评估失败（不影响主流程）: {fb_err}")

    return state
