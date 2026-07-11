# Shared helpers for pipeline stage nodes: role matching, anchor, drift, messaging, formatting, consistency
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Awaitable

from app.events import bus, make_event
from app.models import MeetingState, Role, Stage

# 节点签名：async def(state) -> state
Node = Callable[[MeetingState], Awaitable[MeetingState]]

# ---- 角色模糊匹配（模块级，支持中英文角色名）----
# 真实 LLM 可能返回中文角色名（"产品经理"、"后端架构师"等），
# StubLLM 返回英文角色名，此处统一模糊匹配。
_ROLE_KEYWORDS: dict[str, list[str]] = {
    Role.PRODUCT_ARCHITECT.value: ["product", "architect", "产品", "架构", "pm", "产品经理", "产品架构"],
    Role.SECURITY_EXPERT.value: ["security", "安全", "风控", "sec"],
    Role.DATA_ENGINEER.value: ["data", "数据", "analytics", "分析"],
    Role.UX_DESIGNER.value: ["ux", "design", "设计", "体验", "ui"],
    Role.MARKETING_EXPERT.value: ["marketing", "市场", "营销", "brand", "growth"],
    Role.ENGINEER.value: ["engineer", "develop", "开发", "工程", "后端", "前端", "技术"],
    Role.MODERATOR.value: ["moderator", "host", "主持", "协调", "facilitator"],
}


def _match_role(role_str: str) -> Role | None:
    """模糊匹配角色名（支持中英文）

    匹配规则：角色字符串（小写）中包含任一关键词即匹配。
    返回匹配的 Role 枚举，未匹配返回 None。
    """
    role_lower = role_str.lower()
    for role, keywords in _ROLE_KEYWORDS.items():
        for kw in keywords:
            if kw in role_lower:
                return Role(role)
    return None


def _anchor(state: MeetingState) -> str:
    """取会议宪章锚点文本，charter 不存在时返回空串"""
    if state.charter is None:
        return ""
    return state.charter.to_prompt_anchor()


def _record_drift(state: MeetingState, role: Role | str, stage: Stage, content: str) -> None:
    """对发言做宪章漂移检查并记录到 drift_log（非阻塞）

    role 支持枚举角色与借调角色的字符串角色名。
    """
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


def _format_claims_as_text(claims: list[dict[str, Any]], role_label: str = "") -> str:
    """把 claims 列表格式化为自然可读文本。

    设计原则：
    - 每条论点独占一行，正文干净，不被标签打断
    - 元数据（风险等级、证据来源）换行缩进显示，用 [meta] 标签包裹，前端渲染为灰色小字元信息行
    - [type] 标签紧随编号，作为论点类型徽章（事实/假设/约束等）
    - evidence_ref 中紧跟标签后的解释性文字归入元信息行，不插在正文中打断阅读
    """
    if not claims:
        return "（暂无要点输出）"
    lines: list[str] = []
    for i, c in enumerate(claims, 1):
        claim_text = c.get("claim", c.get("text", "")).strip()
        ctype = c.get("type", "assumption")
        risk_level = c.get("risk_level")
        evidence_ref = c.get("evidence_ref", "").strip()

        # 主行：编号 + 类型标签 + 论点正文
        lines.append(f"{i}. [{ctype}] {claim_text}")

        # 元数据行：将 risk_level 和 evidence_ref 中的信息提取出来，换行缩进显示
        meta_parts: list[str] = []
        if risk_level:
            meta_parts.append(f"[risk:{risk_level}]")
        if evidence_ref:
            # evidence_ref 可能格式：[常识] 解释文字... 或 [doc:xxx] 或纯文本
            # 统一放入元信息行，标签保留为徽章，解释文字作为普通文本跟在后面
            meta_parts.append(evidence_ref)
        if meta_parts:
            # 用 [meta] 标记一个元信息行，前端识别后渲染为缩进灰色小字
            lines.append(f"   [meta] {' '.join(meta_parts)}")
    return "\n".join(lines)


def _format_arbitrate_as_text(
    decision_record: dict[str, Any],
    claims: list[dict[str, Any]],
    conflicts: list[dict[str, Any]],
) -> str:
    """把仲裁裁决格式化为可读文本。

    设计：不添加【角色·阶段】头（前端卡片已展示）；用自然段落呈现裁决结果。
    """
    # 构建 claim_id → claim 映射
    claim_map: dict[str, dict[str, Any]] = {}
    for c in claims:
        claim_map[c.get("id", "")] = c
    # 构建 conflict_id → conflict 映射
    conflict_map: dict[str, dict[str, Any]] = {}
    for cf in conflicts:
        conflict_map[cf.get("id", "")] = cf

    lines: list[str] = []

    # 采纳的论点 - 只展示前5条关键论点作为摘要，避免单条消息过长
    adopted = decision_record.get("adopted_claims", [])
    if adopted:
        lines.append(f"经审议，共采纳 {len(adopted)} 条核心论点。要点如下：")
        display_count = min(5, len(adopted))
        for i in range(display_count):
            cid = adopted[i]
            claim = claim_map.get(cid, {})
            ctype = claim.get("claim_type", claim.get("type", "assumption"))
            # LLM返回的字段名是"claim"，不是"text"；做多重回退
            text = claim.get("claim", claim.get("text", "")).strip()
            # 截断过长的论点文本
            if len(text) > 60:
                text = text[:57] + "…"
            if text:
                lines.append(f"  {i+1}. [{ctype}] {text}")
        if len(adopted) > display_count:
            lines.append(f"  …另有 {len(adopted) - display_count} 条论点已纳入最终产出。")
        lines.append("")

    # 裁决详情
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


# ---------- 第3层：一致性自检 + 结论锁定辅助 ----------

# 置信度等级排序（值越大越差）
_CONFIDENCE_RANK: dict[str, int] = {"high": 0, "low": 1, "fallback": 2}


def _full_anchor(state: MeetingState, stage: str) -> str:
    """构造完整锚点：宪章锚点 + 已锁定结论上下文 + 历史会议引用上下文

    第3层：每个节点调 agent 前把 chain.get_locked_context(stage) 注入到 anchor 里
    （与 charter anchor 一起拼到 prompt 前）。
    """
    parts: list[str] = []
    charter_anchor = _anchor(state)
    if charter_anchor:
        parts.append(charter_anchor)
    locked_context = state.conclusion_chain.get_locked_context(stage)
    if locked_context:
        parts.append(locked_context)
    # 注入历史会议引用上下文（创建时指定的 + 运行中动态注入的）
    if state.reference_context:
        parts.append(state.reference_context)
    return "\n\n".join(parts) if parts else ""


def _worst_confidence(a: str, b: str) -> str:
    """返回两个置信度中较差的一个"""
    return a if _CONFIDENCE_RANK.get(a, 0) >= _CONFIDENCE_RANK.get(b, 0) else b


def _update_trace_consistency(state: MeetingState, start_pos: int, status: str) -> None:
    """更新 trace 中自 start_pos 以来所有记录的 consistency_status"""
    for call in state.llm_trace.calls[start_pos:]:
        call.consistency_status = status


async def _run_with_consistency(
    state: MeetingState,
    stage: str,
    call_fn: Callable[[str], Awaitable[dict[str, Any]]],
) -> tuple[dict[str, Any], str]:
    """带一致性自检的 LLM 调用

    流程：
    1. 用完整锚点（宪章 + 已锁定结论上下文）调 LLM
    2. 调 chain.check_consistency(result, stage) 检查一致性
    3. 如果不一致：把矛盾信息追加到 anchor 重调 LLM（最多 2 次重试）
    4. 重试后仍不一致：标记为 low_confidence，记录到 state 但不中断流程
    5. 如果一致：返回结果和置信度

    返回 (最终结果, confidence: "high" | "low" | "fallback")
    """
    chain = state.conclusion_chain
    base_anchor = _full_anchor(state, stage)

    # 记录 trace 起始位置（用于后续更新一致性状态）
    start_pos = len(state.llm_trace.calls)

    # 首次调用
    result = await call_fn(base_anchor)
    consistency = chain.check_consistency(result, stage)

    retries = 0
    while not consistency.is_consistent and retries < 2:
        retries += 1
        # 把矛盾信息追加到 anchor 重调
        contradiction = "；".join(consistency.violations)
        augmented_anchor = (
            f"{base_anchor}\n\n"
            f"【一致性警告】你的输出与已确认结论矛盾：{contradiction}。"
            f"请基于已确认结论重新输出，不得与之矛盾。"
        )
        result = await call_fn(augmented_anchor)
        consistency = chain.check_consistency(result, stage)

    # 确定置信度并更新 trace 一致性状态
    if not consistency.is_consistent:
        # 重试后仍不一致：标记 low_confidence，不中断流程
        _update_trace_consistency(state, start_pos, "low_confidence")
        confidence = "low"
    elif retries > 0:
        # 重试后通过
        _update_trace_consistency(state, start_pos, "inconsistent_retry")
        confidence = "low"
    else:
        # 首次即通过
        _update_trace_consistency(state, start_pos, "consistent")
        confidence = "high"

    # 检查是否有降级到 stub（仅 RealLLM 会记录 fallback_stub）
    if any(
        c.validation_status == "fallback_stub"
        for c in state.llm_trace.calls[start_pos:]
    ):
        confidence = "fallback"

    return result, confidence
