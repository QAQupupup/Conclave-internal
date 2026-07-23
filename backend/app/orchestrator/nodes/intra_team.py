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
    """
    set_current_trace(state.llm_trace)

    if not state.team_config:
        state.team_config = [
            {"role": "product_architect", "stance": "重价值与边界"},
            {"role": "engineer", "stance": "重可行性与风险"},
        ]

    members: list[tuple[Role, str]] = []
    seen_roles: set[Role] = set()
    for member in state.team_config:
        role_str = member.get("role", "")
        stance = member.get("stance", "")
        matched = _match_role(role_str)
        if matched is not None and matched not in seen_roles:
            seen_roles.add(matched)
            members.append((matched, stance))
    if not members:
        members = [(Role.PRODUCT_ARCHITECT, "重价值与边界"), (Role.ENGINEER, "重可行性与风险")]

    async def _think_one(role: Role, stance: str) -> dict[str, Any]:
        async def call_fn(anchor: str) -> dict[str, Any]:
            req = build_intra_prompt(role, state.clarified_topic or state.topic, stance, anchor=anchor)
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
    return await run_intra_team(state, list(role_results))
