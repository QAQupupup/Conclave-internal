# 六阶段节点：每个 async def run(state) -> state，纯函数风格，副作用通过事件总线外溢
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Awaitable

from app.agents.roles import engineer, moderator, product_architect
from app.events import bus, make_event
from app.models import MeetingState, MeetingStatus, Role, Stage
from app.rag.retriever import retrieve_for_conflict

# 节点签名：async def(state) -> state
Node = Callable[[MeetingState], Awaitable[MeetingState]]


def _record_message(
    state: MeetingState,
    role: Role,
    stage: Stage,
    content: str,
    claim_refs: list[str] | None = None,
    evidence_refs: list[str] | None = None,
) -> dict[str, Any]:
    """记录发言到 state.messages 并返回消息字典（供事件 payload 复用）"""
    msg = {
        "id": f"msg-{uuid.uuid4().hex[:8]}",
        "meeting_id": state.meeting_id,
        "agent_role": role.value,
        "stage": stage.value,
        "content": content,
        "claim_refs": claim_refs or [],
        "evidence_refs": evidence_refs or [],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    state.messages.append(msg)
    return msg


async def _emit_agent_spoke(state: MeetingState, role: Role, stage: Stage, content: str,
                            claim_refs: list[str] | None = None) -> None:
    """发布 agent.spoke 事件"""
    msg = _record_message(state, role, stage, content, claim_refs)
    await bus.publish(
        make_event(
            "agent.spoke",
            state.meeting_id,
            {
                "meeting_id": state.meeting_id,
                "role": role.value,
                "stage": stage.value,
                "content": content,
                "claim_refs": claim_refs or [],
                "message_id": msg["id"],
            },
        )
    )


async def clarify_node(state: MeetingState) -> MeetingState:
    """Clarify 阶段：主持人澄清议题，确认团队组成"""
    agent = moderator()
    result = await agent.clarify(state.topic, state.doc_summaries)
    state.clarified_topic = result.get("clarified_topic", state.topic)
    state.key_questions = result.get("key_questions", [])
    state.team_config = result.get("team_config", [])
    # 主持人发言
    summary = (
        f"议题已澄清：{state.clarified_topic}。"
        f"关键问题 {len(state.key_questions)} 个，团队 {len(state.team_config)} 人。"
    )
    await _emit_agent_spoke(state, Role.MODERATOR, Stage.CLARIFY, summary)
    state.stage = Stage.INTRA_TEAM
    return state


async def intra_team_node(state: MeetingState) -> MeetingState:
    """IntraTeam 阶段：各角色队内发言，达成队内结论"""
    if not state.team_config:
        # 兜底：默认两角色
        state.team_config = [
            {"role": "product_architect", "stance": "重价值与边界"},
            {"role": "engineer", "stance": "重可行性与风险"},
        ]
    conclusions: list[dict[str, Any]] = []
    for member in state.team_config:
        role_str = member.get("role", "")
        stance = member.get("stance", "")
        if role_str == Role.PRODUCT_ARCHITECT.value:
            agent = product_architect()
            role = Role.PRODUCT_ARCHITECT
        elif role_str == Role.ENGINEER.value:
            agent = engineer()
            role = Role.ENGINEER
        else:
            # 未知角色跳过（迭代一只支持两种）
            continue
        result = await agent.intra_speak(state.clarified_topic or state.topic, stance)
        claims = result.get("claims", [])
        claim_ids = []
        for c in claims:
            cid = f"claim-{uuid.uuid4().hex[:8]}"
            c["id"] = cid
            c["agent_role"] = role.value
            state.claims.append(c)
            claim_ids.append(cid)
        # 队内结论
        conclusion = {
            "role": role.value,
            "stance": stance,
            "claims": claims,
        }
        conclusions.append(conclusion)
        content = json.dumps(claims, ensure_ascii=False)
        await _emit_agent_spoke(state, role, Stage.INTRA_TEAM, content, claim_refs=claim_ids)
    state.team_conclusions = conclusions
    state.stage = Stage.CROSS_TEAM
    return state


async def cross_team_node(state: MeetingState) -> MeetingState:
    """CrossTeam 阶段：跨队辩论，暴露冲突点"""
    agent = moderator()
    result = await agent.cross_team(state.team_conclusions)
    conflicts = result.get("conflicts", [])
    # 规范化冲突类型
    for c in conflicts:
        if "conflict_type" not in c and "type" in c:
            c["conflict_type"] = c.pop("type")
    state.conflicts = conflicts
    content = json.dumps(conflicts, ensure_ascii=False)
    await _emit_agent_spoke(state, Role.MODERATOR, Stage.CROSS_TEAM, content)
    state.stage = Stage.EVIDENCE_CHECK
    return state


async def evidence_check_node(state: MeetingState) -> MeetingState:
    """EvidenceCheck 阶段：逐冲突 RAG 检索证据，对照判断"""
    agent = moderator()
    evidence_set: list[dict[str, Any]] = []
    for conflict in state.conflicts:
        cid = conflict.get("id", "c0")
        summary = conflict.get("summary", str(conflict))
        # RAG 检索证据
        chunks = retrieve_for_conflict(state.meeting_id, summary, top_k=5)
        # 转成证据片段格式
        evidence_chunks = [
            {
                "evidence_id": f"ev-{i}",
                "quote": ck.get("text", "")[:200],
                "source": ck.get("source", "doc:unknown"),
                "char_range": [ck.get("char_start", 0), ck.get("char_end", 0)],
            }
            for i, ck in enumerate(chunks)
        ]
        if not evidence_chunks:
            # 无文档时兜底：构造一条空证据
            evidence_chunks = [
                {
                    "evidence_id": "ev-0",
                    "quote": "（无可用文档证据）",
                    "source": "doc:none",
                    "char_range": [0, 0],
                }
            ]
        result = await agent.evidence_check(conflict, evidence_chunks)
        assessments = result.get("evidence_assessments", [])
        es = {
            "conflict_id": result.get("conflict_id", cid),
            "assessments": assessments,
        }
        evidence_set.append(es)
        # 发布 evidence.attached 事件（逐条证据）
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
    state.stage = Stage.ARBITRATE
    return state


async def arbitrate_node(state: MeetingState) -> MeetingState:
    """Arbitrate 阶段：仲裁者裁决，形成结论"""
    agent = moderator()
    result = await agent.arbitrate(state.evidence_set)
    state.decision_record = {
        "decisions": result.get("decisions", []),
        "adopted_claims": result.get("adopted_claims", []),
    }
    content = json.dumps(state.decision_record, ensure_ascii=False)
    await _emit_agent_spoke(state, Role.MODERATOR, Stage.ARBITRATE, content)
    state.stage = Stage.PRODUCE
    return state


async def produce_node(state: MeetingState) -> MeetingState:
    """Produce 阶段：生成结构化 PRD 与 OpenAPI 片段"""
    agent = moderator()
    result = await agent.produce(state.decision_record or {})
    prd = result.get("prd", {})
    openapi = result.get("openapi", "")
    state.artifact = {
        "meeting_id": state.meeting_id,
        "prd": prd,
        "openapi": openapi,
    }
    # 发布 artifact.generated 事件
    await bus.publish(
        make_event(
            "artifact.generated",
            state.meeting_id,
            {
                "meeting_id": state.meeting_id,
                "prd": prd,
                "openapi": openapi,
            },
        )
    )
    # 终态
    state.stage = Stage.PRODUCE
    state.status = MeetingStatus.DONE
    return state


# 节点注册表：阶段 -> 节点函数
NODES: dict[Stage, Node] = {
    Stage.CLARIFY: clarify_node,
    Stage.INTRA_TEAM: intra_team_node,
    Stage.CROSS_TEAM: cross_team_node,
    Stage.EVIDENCE_CHECK: evidence_check_node,
    Stage.ARBITRATE: arbitrate_node,
    Stage.PRODUCE: produce_node,
}
