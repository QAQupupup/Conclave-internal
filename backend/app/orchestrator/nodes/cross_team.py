# Cross-team stage node (legacy wrapper)
# Phase 3：业务逻辑已下沉到 stage_runners.py，本文件保留兼容导出。
from __future__ import annotations

from typing import Any

from app.agents.compute import build_cross_team_prompt, execute_think
from app.agents.trace import set_current_trace
from app.models import MeetingState, Role
from app.orchestrator.stage_runners import run_cross_team

from ._helpers import _resolve_model_for_call, _run_with_consistency


async def cross_team_node(state: MeetingState) -> MeetingState:
    """CrossTeam 阶段：跨队辩论，暴露冲突点

    ADR-010: 支持 re_examine 模式。当 gate_pending_action.action == "re_examine" 时，
    在锚点中注入门禁反馈，让主持人针对 weak_dimensions 重新审视冲突。
    """
    set_current_trace(state.llm_trace)

    # ADR-010: 检测 re_examine 模式
    reex_info = state.gate_pending_action or {}
    is_reexamine = reex_info.get("action") == "re_examine"
    reexamine_anchor = ""
    if is_reexamine:
        weak_dims = reex_info.get("weak_dimensions", [])
        reason = reex_info.get("reason", "")
        dim_labels = {
            "1": "条件1：每个角色的 claims 中至少有 1 条被其他角色直接反驳或质疑",
            "2": "条件2：冲突列表覆盖了议题的核心决策点（非边缘细节）",
            "3": "条件3：不存在某角色 claims 全部未被任何冲突引用的情况",
        }
        dim_texts = [dim_labels.get(str(d), str(d)) for d in weak_dims]
        reexamine_anchor = (
            f"[门禁重审要求 第{reex_info.get('round', '?')}轮]\n"
            f"上一轮跨队辩论未通过质量门禁，需要重新审视冲突点。\n"
            f"原因：{reason}\n"
            f"未满足的条件：\n" + "\n".join(f"  - {dt}" for dt in dim_texts) + "\n"
            "请重新识别冲突，确保覆盖核心争议点、每个角色的论点都被冲突引用。"
        )
        # 消费门禁动作（cross_team 执行后由 run_cross_team 决定是否继续回流或推进）
        state.gate_pending_action = None

    async def call_fn(anchor: str) -> dict[str, Any]:
        # 合并门禁重审锚点
        merged_anchor = anchor
        if reexamine_anchor:
            merged_anchor = f"{reexamine_anchor}\n\n{anchor}" if anchor else reexamine_anchor
        req = build_cross_team_prompt(state.team_conclusions, anchor=merged_anchor)
        req.model = _resolve_model_for_call(state, Role.MODERATOR.value, "cross_team")
        resp = await execute_think(req)
        return resp.result

    result, confidence = await _run_with_consistency(state, "cross_team", call_fn)
    return await run_cross_team(state, result, confidence)
