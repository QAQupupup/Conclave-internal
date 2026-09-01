# Intra-team stage node (legacy wrapper)
# Phase 3：状态更新逻辑已下沉到 stage_runners.py，本文件保留兼容导出。
# ADR-010: 全并发思考，消除锚定偏误，所有角色独立产出 claims。
from __future__ import annotations

import asyncio
from typing import Any

from app.agents.compute import build_intra_prompt
from app.agents.trace import set_current_trace
from app.logging_config import get_logger
from app.models import MeetingState, Role
from app.orchestrator.stage_runners import run_intra_team

from ._helpers import (
    _build_tool_registry,
    _match_role,
    _run_stage_step,
)

logger = get_logger("orchestrator.nodes.intra_team")


async def intra_team_node(state: MeetingState) -> MeetingState:
    """IntraTeam 阶段：全并发思考，所有角色独立产出 claims

    ADR-010: 砍掉"最后 1 反应"逻辑，消除锚定偏误。
    所有角色用 build_intra_prompt（独立思考）全并发。
    build_intra_react_prompt 保留但不再调用（未来可作配置项恢复）。

    支持门禁 supplement 模式：当 gate_pending_action.action == "supplement" 时，
    仅运行 target_roles 指定的角色，替换其原有 claims（而非全量追加）。

    支持子步骤断点续传：当 completed_roles 非空时（前次执行被余额不足等中断），
    跳过已完成角色，仅运行未完成角色，结果与 intra_team_partial_results 合并后
    传入 run_intra_team。阶段完成后清空检查点字段。
    """
    set_current_trace(state.llm_trace)
    tool_registry = _build_tool_registry()

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
            # 断点续传：非 supplement 模式下跳过已完成的角色
            if not is_supplement and matched.value in state.completed_roles:
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

    # 断点续传：如果所有角色都已在之前的中断中完成，直接用已保存的结果
    # （此检查必须在 default fallback 之前，否则会重新运行已完成角色）
    if not is_supplement and not members and state.intra_team_partial_results:
        logger.info(
            "会议 %s intra_team 全部角色已完成（断点续传），直接聚合结果",
            state.meeting_id,
        )
        all_results = list(state.intra_team_partial_results)
        state.completed_roles = []
        state.intra_team_partial_results = []
        return await run_intra_team(state, all_results, replace_roles=None)

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
        def build_prompt(anchor: str, available_tools: Any) -> Any:
            # 合并门禁补充锚点与常规锚点
            merged_anchor = anchor
            if supplement_anchor:
                merged_anchor = f"{supplement_anchor}\n\n{anchor}" if anchor else supplement_anchor
            return build_intra_prompt(
                role,
                state.clarified_topic or state.topic,
                stance,
                anchor=merged_anchor,
                available_tools=available_tools,
            )

        result, confidence = await _run_stage_step(
            state,
            "intra_team",
            role.value,
            build_prompt,
            tool_registry=tool_registry,
        )
        output = {
            "role": role.value,
            "stance": stance,
            "claims": result.get("claims", []),
            "confidence": confidence,
            "react": False,
        }
        # 子步骤检查点：标记角色已完成并保存结果（survives gather 异常中断）
        if not is_supplement and role.value not in state.completed_roles:
            state.completed_roles.append(role.value)
            state.intra_team_partial_results.append(output)
        return output

    # 全并发执行未完成的角色，使用 return_exceptions=True 捕获部分失败
    raw_results = await asyncio.gather(*[_think_one(r, s) for r, s in members], return_exceptions=True)

    # 分离成功结果与异常
    gathered_results: list[dict[str, Any]] = list(state.intra_team_partial_results)
    first_exc: Exception | None = None
    for r in raw_results:
        if isinstance(r, Exception):
            if first_exc is None:
                first_exc = r
        elif isinstance(r, dict):
            gathered_results.append(r)

    if first_exc is not None:
        # 部分角色失败（如余额不足）。已完成角色的结果已保存在 state 中。
        # Runner 的异常处理会持久化 state（含 completed_roles），然后暂停/重试。
        raise first_exc

    # 全部角色成功完成，清空检查点字段
    state.completed_roles = []
    state.intra_team_partial_results = []
    return await run_intra_team(state, gathered_results, replace_roles=supplement_roles if is_supplement else None)
