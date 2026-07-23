# Intra-team stage node (legacy wrapper)
# Phase 3：状态更新逻辑已下沉到 stage_runners.py，本文件保留兼容导出。
# ADR-010: 全并发思考，消除锚定偏误，所有角色独立产出 claims。
from __future__ import annotations

import asyncio
from typing import Any

from app.agents.compute import build_intra_prompt, execute_think
from app.agents.trace import set_current_trace
from app.models import MeetingState, Role
from app.orchestrator.stage_runners import run_intra_team

from ._helpers import (
    _match_role,
    _resolve_model_for_call,
    _run_with_consistency,
)


async def intra_team_node(state: MeetingState) -> MeetingState:
    """IntraTeam 阶段：全并发思考，所有角色独立产出 claims

    ADR-010: 砍掉"最后 1 反应"逻辑，消除锚定偏误。
    所有角色用 build_intra_prompt（独立思考）全并发。
    build_intra_react_prompt 保留但不再调用（未来可作配置项恢复）。

    支持门禁 supplement 模式：当 gate_pending_action.action == "supplement" 时，
    仅运行 target_roles 指定的角色，替换其原有 claims（而非全量追加）。
    """
    set_current_trace(state.llm_trace)

    if not state.team_config:
        state.team_config = [
            {"role": "product_architect", "stance": "重价值与边界"},
            {"role": "engineer", "stance": "重可行性与风险"},
        ]

    # ADR-010: 检测 supplement 模式
    supplement_info = state.gate_pending_action or {}
    is_supplement = supplement_info.get("action") == "supplement"
    supplement_roles: set[str] = set()
    supplement_reason = ""
    if is_supplement:
        supplement_roles = set(supplement_info.get("target_roles", []))
        supplement_reason = supplement_info.get("reason", "")

    members: list[tuple[Role, str]] = []
    seen_roles: set[Role] = set()
    for member in state.team_config:
        role_str = member.get("role", "")
        stance = member.get("stance", "")
        matched = _match_role(role_str)
        if matched is not None and matched not in seen_roles:
            # supplement 模式下仅运行目标角色
            if is_supplement and matched.value not in supplement_roles:
                continue
            seen_roles.add(matched)
            members.append((matched, stance))

    # supplement 模式下可能所有角色都匹配不到（target_roles 含无效值），回退到全量
    if is_supplement and not members:
        seen_roles.clear()
        for member in state.team_config:
            role_str = member.get("role", "")
            stance = member.get("stance", "")
            matched = _match_role(role_str)
            if matched is not None and matched not in seen_roles:
                seen_roles.add(matched)
                members.append((matched, stance))

    if not members:
        members = [(Role.PRODUCT_ARCHITECT, "重价值与边界"), (Role.ENGINEER, "重可行性与风险")]

    # supplement 模式下构建补充锚点，告知角色需要补充什么
    supplement_anchor = ""
    if is_supplement and supplement_reason:
        role_names = ", ".join(r.value for r, _ in members)
        supplement_anchor = (
            f"[门禁补充要求 第{supplement_info.get('round', '?')}轮]\n"
            f"以下角色的论点在跨队辩论中未被充分引用或反驳，需要补充论点：{role_names}\n"
            f"原因：{supplement_reason}\n"
            f"请针对已有冲突点补充更有力的论点或证据，不要重复已有观点。"
        )

    async def _think_one(role: Role, stance: str) -> dict[str, Any]:
        async def call_fn(anchor: str) -> dict[str, Any]:
            # 合并门禁补充锚点与常规锚点
            merged_anchor = anchor
            if supplement_anchor:
                merged_anchor = f"{supplement_anchor}\n\n{anchor}" if anchor else supplement_anchor
            req = build_intra_prompt(role, state.clarified_topic or state.topic, stance, anchor=merged_anchor)
            req.model = _resolve_model_for_call(state, role.value, "intra_team")
            resp = await execute_think(req)
            return resp.result

        result, confidence = await _run_with_consistency(state, "intra_team", call_fn)
        return {
            "role": role.value,
            "stance": stance,
            "claims": result.get("claims", []),
            "confidence": confidence,
            "react": False,
        }

    role_results = await asyncio.gather(*[_think_one(r, s) for r, s in members])
    return await run_intra_team(state, list(role_results), replace_roles=supplement_roles if is_supplement else None)
