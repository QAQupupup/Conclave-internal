# Intra-team stage node
from __future__ import annotations

import asyncio
import uuid
from typing import Any

from app.agents.compute import get_compute, build_intra_prompt, build_intra_react_prompt
from app.agents.trace import set_current_trace
from app.models import MeetingState, Role, Stage
from app.orchestrator.state import next_stage as _next_stage

from ._helpers import (
    _match_role,
    _format_claims_as_text,
    _emit_agent_spoke,
    _record_drift,
    _run_with_consistency,
    _worst_confidence,
)
from .borrow import _let_borrowed_agents_speak, _moderator_assess_borrow


async def intra_team_node(state: MeetingState) -> MeetingState:
    """IntraTeam 阶段：混合模式思考（前 N-1 并行 + 最后 1 反应）

    优化策略：
    - 前 N-1 个角色并行独立思考（互不可见，速度快）
    - 最后 1 个角色等前面完成后，基于全部前序结论做反应性思考（看到其他人观点）
    - 兼顾速度和辩论质量：O(max(T1..Tn-1) + Tn) 而非 O(T1+T2+...+Tn)
    - 只有 1 个角色时退化为纯并行（无反应环节）

    副作用（claims/事件/漂移）串行执行，保持顺序与 team_config 一致。
    """
    # 设置 trace 上下文
    set_current_trace(state.llm_trace)
    compute = get_compute()
    if not state.team_config:
        # 兜底：默认两角色
        state.team_config = [
            {"role": "product_architect", "stance": "重价值与边界"},
            {"role": "engineer", "stance": "重可行性与风险"},
        ]
    # 解析 team_config 为 (role, stance) 列表，保持顺序
    # 支持模糊匹配：LLM 可能返回中文角色名（"产品经理"、"后端架构师"等）
    # _ROLE_KEYWORDS 和 _match_role 已提升为模块级函数

    members: list[tuple[Role, str]] = []
    seen_roles: set[Role] = set()
    for member in state.team_config:
        role_str = member.get("role", "")
        stance = member.get("stance", "")
        matched = _match_role(role_str)
        if matched is not None:
            # 去重：同一 Role 只保留第一次出现（LLM 可能返回中文和英文两个名称指向同一角色）
            if matched in seen_roles:
                continue
            seen_roles.add(matched)
            members.append((matched, stance))
        # 未匹配的角色跳过（当前支持 7 种角色，其他角色可作为借调处理）

    # 兜底：如果模糊匹配后没有有效角色，使用默认配置
    if not members:
        members = [(Role.PRODUCT_ARCHITECT, "重价值与边界"), (Role.ENGINEER, "重可行性与风险")]

    # ---- Phase 1：前 N-1 个角色并行独立思考 ----
    parallel_members = members[:-1] if len(members) > 1 else members
    last_member = members[-1] if len(members) > 1 else None

    async def _think_one(role: Role, stance: str) -> tuple[dict[str, Any], str]:
        async def call_fn(anchor: str) -> dict[str, Any]:
            req = build_intra_prompt(role, state.clarified_topic or state.topic, stance, anchor=anchor)
            resp = await compute.think(req)
            return resp.result
        return await _run_with_consistency(state, "intra_team", call_fn)

    # 并行思考前 N-1 个角色
    parallel_results = await asyncio.gather(
        *[_think_one(r, s) for r, s in parallel_members]
    )

    # ---- 串行收集前 N-1 个角色的结论（构造 prior_conclusions 供反应角色使用）----
    conclusions: list[dict[str, Any]] = []
    worst_confidence = "high"
    prior_conclusions_for_react: list[dict[str, Any]] = []

    for (role, stance), (result, confidence) in zip(parallel_members, parallel_results):
        worst_confidence = _worst_confidence(worst_confidence, confidence)
        claims = result.get("claims", [])
        claim_ids = []
        for c in claims:
            cid = f"claim-{uuid.uuid4().hex[:8]}"
            c["id"] = cid
            c["agent_role"] = role.value
            state.claims.append(c)
            claim_ids.append(cid)
        conclusion = {"role": role.value, "stance": stance, "claims": claims}
        conclusions.append(conclusion)
        prior_conclusions_for_react.append(conclusion)
        content = _format_claims_as_text(claims, role.value)
        await _emit_agent_spoke(state, role, Stage.INTRA_TEAM, content, claim_refs=claim_ids)
        _record_drift(state, role, Stage.INTRA_TEAM, content)

    # ---- Phase 2：最后 1 个角色基于前序结论做反应性思考 ----
    if last_member is not None:
        last_role, last_stance = last_member
        async def _think_react(role: Role, stance: str, prior: list[dict]) -> tuple[dict[str, Any], str]:
            async def call_fn(anchor: str) -> dict[str, Any]:
                req = build_intra_react_prompt(
                    role, state.clarified_topic or state.topic, stance, prior, anchor=anchor
                )
                resp = await compute.think(req)
                return resp.result
            return await _run_with_consistency(state, "intra_team", call_fn)

        react_result, react_confidence = await _think_react(last_role, last_stance, prior_conclusions_for_react)
        worst_confidence = _worst_confidence(worst_confidence, react_confidence)
        # 收集反应角色的结论
        react_claims = react_result.get("claims", [])
        react_claim_ids = []
        for c in react_claims:
            cid = f"claim-{uuid.uuid4().hex[:8]}"
            c["id"] = cid
            c["agent_role"] = last_role.value
            state.claims.append(c)
            react_claim_ids.append(cid)
        conclusion = {"role": last_role.value, "stance": last_stance, "claims": react_claims}
        conclusions.append(conclusion)
        content = _format_claims_as_text(react_claims, last_role.value)
        await _emit_agent_spoke(state, last_role, Stage.INTRA_TEAM, content, claim_refs=react_claim_ids)
        _record_drift(state, last_role, Stage.INTRA_TEAM, content)

    state.team_conclusions = conclusions
    # 第2层：锁定 intra_team 结论
    state.conclusion_chain.lock("intra_team", {"claims": state.claims, "team_conclusions": conclusions})
    # 第5层：记录置信度（取最差值）
    state.confidence_flags["intra_team"] = worst_confidence
    # 自动借调评估：队内发言结束后，主持人判断是否需要补充角色（在借调发言前评估，以便新借调角色也能本轮发言）
    await _moderator_assess_borrow(state, Stage.INTRA_TEAM)
    # 让待发言的借调 agent（含刚自动批准的）在队内讨论末尾发言一次
    await _let_borrowed_agents_speak(state, Stage.INTRA_TEAM)
    # 按路由计划跳转下一阶段
    nxt = _next_stage(Stage.INTRA_TEAM, state.flow_plan)
    state.stage = nxt or Stage.PRODUCE
    return state
