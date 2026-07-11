# Clarify stage node
from __future__ import annotations

from typing import Any

from app.agents.compute import get_compute, build_clarify_prompt
from app.agents.trace import set_current_trace
from app.events import bus, make_event
from app.models import MeetingState, Role, Stage
from app.orchestrator.charter import build_charter_from_clarify
from app.orchestrator.state import next_stage as _next_stage, get_skipped_stages

from ._helpers import _emit_agent_spoke, _record_drift, _run_with_consistency, _resolve_model_for_call


async def clarify_node(state: MeetingState) -> MeetingState:
    """Clarify 阶段：主持人澄清议题，确认团队组成，构造会议宪章"""
    # 设置 trace 上下文（RealLLM 会记录调用，stub 静默跳过）
    set_current_trace(state.llm_trace)
    compute = get_compute()

    # 带一致性自检的 LLM 调用：构造 ThinkRequest 并经 compute 接口执行
    async def call_fn(anchor: str) -> dict[str, Any]:
        req = build_clarify_prompt(state.topic, state.doc_summaries, anchor=anchor, reference_context=state.reference_context)
        req.model = _resolve_model_for_call(state, Role.MODERATOR.value, "clarify")
        resp = await compute.think(req)
        return resp.result

    result, confidence = await _run_with_consistency(state, "clarify", call_fn)

    state.clarified_topic = result.get("clarified_topic", state.topic)
    state.key_questions = result.get("key_questions", [])
    state.team_config = result.get("team_config", [])
    # 构造会议宪章（不可变锚点），注入后续所有阶段防漂移
    state.charter = build_charter_from_clarify(
        meeting_id=state.meeting_id,
        original_topic=state.topic,
        clarified_topic=state.clarified_topic,
        key_questions=state.key_questions,
    )
    # 第2层：锁定 clarify 结论
    state.conclusion_chain.lock("clarify", result)
    # 第5层：记录置信度
    state.confidence_flags["clarify"] = confidence
    # 主持人发言
    topic_text = state.clarified_topic.rstrip("。.！!？?")
    summary = (
        f"议题已澄清：{topic_text}。"
        f"关键问题 {len(state.key_questions)} 个，团队 {len(state.team_config)} 人。"
    )
    await _emit_agent_spoke(state, Role.MODERATOR, Stage.CLARIFY, summary)
    _record_drift(state, Role.MODERATOR, Stage.CLARIFY, summary)
    # 议题路由：根据 complexity 设置 flow_plan 和 debate_depth
    complexity = result.get("complexity", "full")
    if complexity in ("simple", "standard", "full"):
        state.flow_plan = complexity
    # 辩论深度映射：simple→light, standard→standard, full→deep
    depth_map = {"simple": "light", "standard": "standard", "full": "deep"}
    state.debate_depth = depth_map.get(complexity, "standard")
    # 发布路由计划事件（前端可据此显示裁剪后的流程）
    await bus.publish(make_event(
        "flow_plan.set",
        state.meeting_id,
        {
            "flow_plan": state.flow_plan,
            "debate_depth": state.debate_depth,
            "skipped_stages": [s.value for s in get_skipped_stages(state.flow_plan)],
        },
    ))
    # 按路由计划跳转下一阶段
    nxt = _next_stage(Stage.CLARIFY, state.flow_plan)
    state.stage = nxt or Stage.INTRA_TEAM
    return state
