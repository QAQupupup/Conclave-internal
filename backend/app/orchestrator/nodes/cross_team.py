# Cross-team stage node
from __future__ import annotations

from typing import Any

from app.agents.compute import get_compute, build_cross_team_prompt
from app.agents.trace import set_current_trace
from app.events import bus, make_event
from app.models import MeetingState, Role, Stage
from app.orchestrator.state import next_stage as _next_stage

from ._helpers import (
    _emit_agent_spoke,
    _record_drift,
    _run_with_consistency,
    _resolve_model_for_call,
)
from .borrow import _let_borrowed_agents_speak, _moderator_assess_borrow
from .evidence_check import _prefetch_evidence


async def cross_team_node(state: MeetingState) -> MeetingState:
    """CrossTeam 阶段：跨队辩论，暴露冲突点

    流水线优化：冲突产生后，后台预启动 evidence_check 的 RAG 检索，
    与后续的借调发言 + 阶段切换事件并行，减少 evidence_check 等待时间。
    """
    # 设置 trace 上下文
    set_current_trace(state.llm_trace)
    compute = get_compute()
    # 带一致性自检的 LLM 调用
    async def call_fn(anchor: str) -> dict[str, Any]:
        req = build_cross_team_prompt(state.team_conclusions, anchor=anchor)
        req.model = _resolve_model_for_call(state, Role.MODERATOR.value, "cross_team")
        resp = await compute.think(req)
        return resp.result

    result, confidence = await _run_with_consistency(state, "cross_team", call_fn)
    conflicts = result.get("conflicts", [])
    # 规范化冲突类型
    for c in conflicts:
        if "conflict_type" not in c and "type" in c:
            c["conflict_type"] = c.pop("type")
    state.conflicts = conflicts
    # 第2层：锁定 cross_team 结论
    state.conclusion_chain.lock("cross_team", {"conflicts": conflicts})
    # 第5层：记录置信度
    state.confidence_flags["cross_team"] = confidence
    # 格式化冲突摘要为可读文本（不再发送原始JSON）
    if conflicts:
        conflict_lines = [f"跨队辩论结束，识别出 {len(conflicts)} 个争议点："]
        for i, cf in enumerate(conflicts, 1):
            ctype = cf.get("conflict_type", cf.get("type", "preference"))
            summary = cf.get("summary", "").strip()
            type_label = {"factual": "事实争议", "preference": "方案偏好", "scope": "范围界定"}.get(ctype, "争议")
            if summary:
                if len(summary) > 80:
                    summary = summary[:77] + "…"
                conflict_lines.append(f"  {i}. {type_label}：{summary}")
            else:
                side_a = cf.get("side_a", "")
                side_b = cf.get("side_b", "")
                conflict_lines.append(f"  {i}. {type_label}：{side_a[:30]} vs {side_b[:30]}")
        content = "\n".join(conflict_lines)
    else:
        # 无冲突时展示各方核心共识，而非只说"未发现争议点"
        consensus_lines = ["跨队辩论结束，各方观点高度一致，未发现争议点。"]
        consensus_lines.append("")
        consensus_lines.append("各方核心论点汇总：")
        # 从 team_conclusions 中提取每个角色的核心论点（每角色最多展示2条）
        role_labels = {
            "product_architect": "产品架构师",
            "engineer": "工程师",
            "security_expert": "安全专家",
            "ux_designer": "UX设计师",
            "data_engineer": "数据工程师",
            "marketing_expert": "市场专家",
            "moderator": "主持人",
        }
        displayed_count = 0
        for conclusion in state.team_conclusions:
            role_val = conclusion.get("role", "")
            role_name = role_labels.get(role_val, role_val)
            claims = conclusion.get("claims", [])
            if claims:
                consensus_lines.append(f"  【{role_name}】")
                for ci, c in enumerate(claims[:2], 1):
                    claim_text = c.get("claim", c.get("text", "")).strip()
                    if claim_text:
                        if len(claim_text) > 70:
                            claim_text = claim_text[:67] + "…"
                        consensus_lines.append(f"    {ci}. {claim_text}")
                displayed_count += 1
        if displayed_count == 0 and state.claims:
            # team_conclusions 为空时从 state.claims 汇总
            for c in state.claims[:6]:
                role_val = c.get("agent_role", "")
                role_name = role_labels.get(role_val, role_val)
                claim_text = c.get("claim", c.get("text", "")).strip()
                if claim_text:
                    if len(claim_text) > 70:
                        claim_text = claim_text[:67] + "…"
                    consensus_lines.append(f"  • [{role_name}] {claim_text}")
        content = "\n".join(consensus_lines)
    await _emit_agent_spoke(state, Role.MODERATOR, Stage.CROSS_TEAM, content)
    _record_drift(state, Role.MODERATOR, Stage.CROSS_TEAM, content)

    # ---- 流水线优化：后台预检索 evidence（与借调发言并行）----
    # 冲突已确定，RAG 检索是 I/O 密集型，可以提前启动
    # 检索结果存入 state.prefetched_evidence，evidence_check 节点优先使用
    # [UNIQ-07 修复] 旧版用下划线前缀 _prefetched_evidence，pydantic 不序列化，
    # 进程崩溃重启后该字段丢失，evidence_check 节点需要重新检索（重复 RAG 调用）。
    if conflicts:
        state.prefetched_evidence = await _prefetch_evidence(state, conflicts)

    # 议题路由：standard 模式下无冲突时动态跳过 evidence_check
    # standard 模式的 _FLOW_SKIP_MAP 为空（不像 simple 那样无条件跳过），
    # 此处根据实际冲突情况决定是否跳过 evidence_check
    nxt = _next_stage(Stage.CROSS_TEAM, state.flow_plan)
    if nxt == Stage.EVIDENCE_CHECK and not conflicts and state.flow_plan == "standard":
        nxt = _next_stage(Stage.EVIDENCE_CHECK, state.flow_plan) or Stage.PRODUCE
    # 跨队辩论结束后，评估是否需要借调补充角色
    await _moderator_assess_borrow(state, Stage.CROSS_TEAM)
    # 让新借调的agent有机会发言
    await _let_borrowed_agents_speak(state, Stage.CROSS_TEAM)
    state.stage = nxt or Stage.PRODUCE
    return state
