# 格式化相关纯函数
from __future__ import annotations

from typing import Any


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
        text = d.get("summary", d.get("verdict", str(d))) if isinstance(d, dict) else str(d)
        if text:
            core_decisions.append(text[:120])

    support_a = 0
    support_b = 0
    neutral_count = 0
    irrelevant_count = 0
    for es in evidence_set:
        for a in es.get("assessments", []):
            direction = a.get("supports", "neutral")
            if direction == "a":
                support_a += 1
            elif direction == "b":
                support_b += 1
            elif direction == "irrelevant":
                irrelevant_count += 1
            else:
                neutral_count += 1
    evidence_backing = (
        (
            f"{support_a} 条支持A方, "
            f"{support_b} 条支持B方, "
            f"{neutral_count} 条中立" + (f", {irrelevant_count} 条无关" if irrelevant_count else "")
        )
        if evidence_set
        else "无证据数据"
    )

    rejected = []
    adopted_ids = set()
    for a in adopted:
        if isinstance(a, dict):
            adopted_ids.add(a.get("id", a.get("claim_id", "")))
        elif isinstance(a, str):
            adopted_ids.add(a)
    for c in conflicts[:5]:
        c.get("id", "")
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
                lines.append(f"  {i + 1}. [{ctype}] {role_prefix}{text}")
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
