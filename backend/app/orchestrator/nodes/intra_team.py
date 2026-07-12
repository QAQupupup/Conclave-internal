# Intra-team stage node (legacy wrapper)
# Phase 3：状态更新逻辑已下沉到 stage_runners.py，本文件保留兼容导出。
from __future__ import annotations

import asyncio
from typing import Any

from app.agents.compute import get_compute, build_intra_prompt, build_intra_react_prompt
from app.agents.trace import set_current_trace
from app.models import MeetingState, Role

from app.orchestrator.stage_runners import run_intra_team
from ._helpers import (
    _match_role,
    _run_with_consistency,
    _resolve_model_for_call,
)


async def intra_team_node(state: MeetingState) -> MeetingState:
    """IntraTeam 阶段：混合模式思考（前 N-1 并行 + 最后 1 反应）"""
    set_current_trace(state.llm_trace)
    compute = get_compute()

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

    parallel_members = members[:-1] if len(members) > 1 else members
    last_member = members[-1] if len(members) > 1 else None

    async def _think_one(role: Role, stance: str) -> dict[str, Any]:
        async def call_fn(anchor: str) -> dict[str, Any]:
            req = build_intra_prompt(role, state.clarified_topic or state.topic, stance, anchor=anchor)
            req.model = _resolve_model_for_call(state, role.value, "intra_team")
            resp = await compute.think(req)
            return resp.result
        result, confidence = await _run_with_consistency(state, "intra_team", call_fn)
        return {"role": role.value, "stance": stance, "claims": result.get("claims", []), "confidence": confidence, "react": False}

    parallel_results = await asyncio.gather(*[_think_one(r, s) for r, s in parallel_members])

    prior_conclusions: list[dict[str, Any]] = []
    for rr in parallel_results:
        prior_conclusions.append({
            "role": rr["role"],
            "stance": rr["stance"],
            "claims": rr["claims"],
        })

    role_results: list[dict[str, Any]] = list(parallel_results)

    if last_member is not None:
        last_role, last_stance = last_member

        async def _think_react(role: Role, stance: str, prior: list[dict]) -> dict[str, Any]:
            async def call_fn(anchor: str) -> dict[str, Any]:
                req = build_intra_react_prompt(role, state.clarified_topic or state.topic, stance, prior, anchor=anchor)
                req.model = _resolve_model_for_call(state, role.value, "intra_team")
                resp = await compute.think(req)
                return resp.result
            result, confidence = await _run_with_consistency(state, "intra_team", call_fn)
            return {"role": role.value, "stance": stance, "claims": result.get("claims", []), "confidence": confidence, "react": True}

        react_result = await _think_react(last_role, last_stance, prior_conclusions)
        role_results.append(react_result)

    return await run_intra_team(state, role_results)
