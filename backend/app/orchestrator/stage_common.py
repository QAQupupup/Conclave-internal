# 阶段共享辅助函数（从 nodes/ 包抽取，供新架构与旧节点共用）
# 注意：本模块不得反向依赖 nodes/ 包中的任何模块，以避免循环导入。
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from app.events import bus, make_event
from app.models import MeetingState, Role, Stage

# ---- 角色模糊匹配（模块级，支持中英文角色名）----
_ROLE_KEYWORDS: dict[str, list[str]] = {
    Role.PRODUCT_ARCHITECT.value: ["product", "architect", "产品", "架构", "pm", "产品经理", "产品架构"],
    Role.SECURITY_EXPERT.value: ["security", "安全", "风控", "sec"],
    Role.DATA_ENGINEER.value: ["data", "数据", "analytics", "分析"],
    Role.UX_DESIGNER.value: ["ux", "design", "设计", "体验", "ui"],
    Role.MARKETING_EXPERT.value: ["marketing", "市场", "营销", "brand", "growth"],
    Role.ENGINEER.value: ["engineer", "develop", "开发", "工程", "后端", "前端", "技术"],
    Role.MODERATOR.value: ["moderator", "host", "主持", "协调", "facilitator"],
}


def match_role(role_str: str) -> Role | None:
    """模糊匹配角色名（支持中英文）"""
    role_lower = role_str.lower()
    for role, keywords in _ROLE_KEYWORDS.items():
        for kw in keywords:
            if kw in role_lower:
                return Role(role)
    return None


# ---- 宪章锚点 ----

def get_charter_anchor(state: MeetingState) -> str:
    """取会议宪章锚点文本，charter 不存在时返回空串"""
    if state.charter is None:
        return ""
    return state.charter.to_prompt_anchor()


def get_full_anchor(state: MeetingState, stage: str) -> str:
    """构造完整锚点：宪章锚点 + 已锁定结论上下文 + 历史会议引用上下文"""
    parts: list[str] = []
    charter_anchor = get_charter_anchor(state)
    if charter_anchor:
        parts.append(charter_anchor)
    locked_context = state.conclusion_chain.get_locked_context(stage)
    if locked_context:
        parts.append(locked_context)
    if state.reference_context:
        parts.append(state.reference_context)
    return "\n\n".join(parts) if parts else ""


# ---- 消息与事件 ----

def record_message(
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


async def emit_agent_spoke(
    state: MeetingState,
    role: Role,
    stage: Stage,
    content: str,
    claim_refs: list[str] | None = None,
    borrowed: bool = False,
) -> dict[str, Any]:
    """发布 agent.spoke 事件并记录消息"""
    msg = record_message(state, role, stage, content, claim_refs)
    payload = {
        "meeting_id": state.meeting_id,
        "role": role.value,
        "stage": stage.value,
        "content": content,
        "claim_refs": claim_refs or [],
        "message_id": msg["id"],
    }
    if borrowed:
        payload["borrowed"] = True
    await bus.publish(make_event("agent.spoke", state.meeting_id, payload))
    return msg


# ---- 漂移检查 ----

def record_drift(state: MeetingState, role: Role | str, stage: Stage, content: str) -> None:
    """对发言做宪章漂移检查并记录到 drift_log（非阻塞）"""
    if state.charter is None or not content:
        return
    result = state.charter.check_drift(content)
    role_value = role.value if isinstance(role, Role) else str(role)
    state.drift_log.append(
        {
            "role": role_value,
            "stage": stage.value,
            "is_drift": result.is_drift,
            "severity": result.severity,
            "reason": result.reason,
            "content_preview": content[:120],
        }
    )


# ---- 格式化 ----

def format_claims_as_text(claims: list[dict[str, Any]], role_label: str = "") -> str:
    """把 claims 列表格式化为自然可读文本"""
    if not claims:
        return "（暂无要点输出）"
    lines: list[str] = []
    for i, c in enumerate(claims, 1):
        claim_text = c.get("claim", c.get("text", "")).strip()
        ctype = c.get("type", "assumption")
        risk_level = c.get("risk_level")
        evidence_ref = c.get("evidence_ref", "").strip()

        lines.append(f"{i}. [{ctype}] {claim_text}")

        meta_parts: list[str] = []
        if risk_level:
            meta_parts.append(f"[risk:{risk_level}]")
        if evidence_ref:
            meta_parts.append(evidence_ref)
        if meta_parts:
            lines.append(f"   [meta] {' '.join(meta_parts)}")
    return "\n".join(lines)


def compress_decisions_to_brief(
    decision_record: dict,
    claims: list[dict],
    conflicts: list[dict],
    evidence_set: list[dict],
) -> dict[str, Any]:
    """将松散的仲裁结果压缩为紧凑的 action brief。

    纯确定性提取（不调 LLM），确保低延迟零额外成本。
    产出结构:
    - core_decisions: 最重要的 3-5 项决策（一行一条）
    - evidence_backing: 支撑核心决策的证据方向
    - rejected_alternatives: 被否决的方向及原因
    - action_items: 从决策推导的具体行动项
    """
    decisions = decision_record.get("decisions", [])
    adopted = decision_record.get("adopted_claims", [])

    core_decisions = []
    for d in decisions[:5]:
        if isinstance(d, dict):
            text = d.get("summary", d.get("verdict", str(d)))
        else:
            text = str(d)
        if text:
            core_decisions.append(text[:120])

    support_counts = {"supports": 0, "refutes": 0, "neutral": 0}
    for es in evidence_set:
        for a in es.get("assessments", []):
            direction = a.get("supports", "neutral")
            if direction in support_counts:
                support_counts[direction] += 1
    evidence_backing = (
        f"{support_counts['supports']} 条证据支持, "
        f"{support_counts['refutes']} 条反驳, "
        f"{support_counts['neutral']} 条中性"
    ) if evidence_set else "无证据数据"

    rejected = []
    adopted_ids = set()
    for a in adopted:
        if isinstance(a, dict):
            adopted_ids.add(a.get("id", a.get("claim_id", "")))
        elif isinstance(a, str):
            adopted_ids.add(a)
    for c in conflicts[:5]:
        c_id = c.get("id", "")
        for side in c.get("sides", []):
            if isinstance(side, dict) and side.get("claim_id", "") not in adopted_ids:
                reason = side.get("rejection_reason", "证据不足或与共识冲突")
                rejected.append(f"{side.get('text', '?')[:80]} — {reason[:60]}")

    action_items = []
    for a in adopted[:5]:
        if isinstance(a, dict):
            next_step = a.get("next_step", a.get("action", ""))
            if next_step:
                action_items.append(next_step[:100])
            else:
                text = a.get("text", a.get("claim", ""))
                if text:
                    action_items.append(f"落实: {text[:80]}")

    return {
        "core_decisions": core_decisions,
        "evidence_backing": evidence_backing,
        "rejected_alternatives": rejected[:3],
        "action_items": action_items,
    }


def format_arbitrate_as_text(
    decision_record: dict[str, Any],
    claims: list[dict[str, Any]],
    conflicts: list[dict[str, Any]],
) -> str:
    """把仲裁裁决格式化为可读文本"""
    claim_map = {c.get("id", ""): c for c in claims}
    conflict_map = {cf.get("id", ""): cf for cf in conflicts}

    lines: list[str] = []
    adopted = decision_record.get("adopted_claims", [])
    if adopted:
        lines.append(f"经审议，共采纳 {len(adopted)} 条核心论点。要点如下：")
        display_count = min(8, len(adopted))
        for i in range(display_count):
            cid = adopted[i]
            claim = claim_map.get(cid, {})
            ctype = claim.get("claim_type", claim.get("type", "assumption"))
            text = claim.get("claim", claim.get("text", "")).strip()
            if not text and isinstance(cid, str) and len(cid) > 2:
                text = cid.strip()
                ctype = "fact"
            if len(text) > 70:
                text = text[:67] + "…"
            if text:
                role_val = claim.get("agent_role", "")
                role_prefix = f"[{role_val}] " if role_val else ""
                lines.append(f"  {i+1}. [{ctype}] {role_prefix}{text}")
        if len(adopted) > display_count:
            lines.append(f"  …另有 {len(adopted) - display_count} 条论点已纳入最终产出。")
        lines.append("")

    decisions = decision_record.get("decisions", [])
    if decisions:
        lines.append("对争议点的裁决：")
        for d in decisions:
            cid = d.get("conflict_id", "")
            verdict = d.get("verdict", "compromise")
            rationale = d.get("rationale", "")
            conflict = conflict_map.get(cid, {})
            side_a = conflict.get("side_a", "A 方观点")
            side_b = conflict.get("side_b", "B 方观点")
            verdict_label = {"a": f"采纳「{side_a}」", "b": f"采纳「{side_b}」", "compromise": "折中融合"}
            lines.append(f"  • {verdict_label.get(verdict, verdict)}：{rationale}")
    else:
        lines.append("本次议题各方观点一致，无冲突需裁决。")

    return "\n".join(lines)


# ---- 模型解析 ----

def resolve_model_for_call(state: MeetingState, role: str = "", stage: str = "") -> str:
    """从 resolved_models 快照解析当前 LLM 调用应使用的模型"""
    from app.llm_providers import resolve_model_from_snapshot
    return resolve_model_from_snapshot(state.resolved_models, agent_role=role, stage=stage)


# ---- 一致性自检 ----

_CONFIDENCE_RANK: dict[str, int] = {"high": 0, "low": 1, "fallback": 2}


def worst_confidence(a: str, b: str) -> str:
    """返回两个置信度中较差的一个"""
    return a if _CONFIDENCE_RANK.get(a, 0) >= _CONFIDENCE_RANK.get(b, 0) else b


def _update_trace_consistency(state: MeetingState, start_pos: int, status: str) -> None:
    """更新 trace 中自 start_pos 以来所有记录的 consistency_status"""
    for call in state.llm_trace.calls[start_pos:]:
        call.consistency_status = status


async def run_with_consistency(
    state: MeetingState,
    stage: str,
    call_fn: Callable[[str], Awaitable[dict[str, Any]]],
) -> tuple[dict[str, Any], str]:
    """带一致性自检的 LLM 调用

    返回 (最终结果, confidence: "high" | "low" | "fallback")
    """
    chain = state.conclusion_chain
    base_anchor = get_full_anchor(state, stage)
    start_pos = len(state.llm_trace.calls)

    result = await call_fn(base_anchor)
    consistency = chain.check_consistency(result, stage)

    retries = 0
    while not consistency.is_consistent and retries < 2:
        retries += 1
        contradiction = "；".join(consistency.violations)
        augmented_anchor = (
            f"{base_anchor}\n\n"
            f"【一致性警告】你的输出与已确认结论矛盾：{contradiction}。"
            f"请基于已确认结论重新输出，不得与之矛盾。"
        )
        result = await call_fn(augmented_anchor)
        consistency = chain.check_consistency(result, stage)

    if not consistency.is_consistent:
        _update_trace_consistency(state, start_pos, "low_confidence")
        confidence = "low"
    elif retries > 0:
        _update_trace_consistency(state, start_pos, "inconsistent_retry")
        confidence = "low"
    else:
        _update_trace_consistency(state, start_pos, "consistent")
        confidence = "high"

    if any(c.validation_status == "fallback_stub" for c in state.llm_trace.calls[start_pos:]):
        confidence = "fallback"

    return result, confidence
