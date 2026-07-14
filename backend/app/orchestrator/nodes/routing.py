# Meta-cognitive routing: decide_next_stage + loop tracking
from __future__ import annotations

from app.models import MeetingState, Stage
from ._helpers import _resolve_model_for_call


def _resolve_model_for_routing(state: MeetingState) -> str:
    """解析元认知 Agent 使用的模型（轻量调用，不指定角色/阶段覆盖）"""
    return _resolve_model_for_call(state, role="meta_cognition", stage="meta")

# 阶段跳转规则（元认知 Agent 的输出约束）
# 防止无限循环和无效跳转
_VALID_NEXT_STAGES: dict[Stage, set[Stage]] = {
    Stage.CLARIFY: {Stage.INTRA_TEAM, Stage.PRODUCE},
    Stage.INTRA_TEAM: {Stage.INTRA_TEAM, Stage.CROSS_TEAM, Stage.EVIDENCE_CHECK, Stage.ARBITRATE, Stage.PRODUCE},
    Stage.CROSS_TEAM: {Stage.INTRA_TEAM, Stage.CROSS_TEAM, Stage.EVIDENCE_CHECK, Stage.ARBITRATE, Stage.PRODUCE},  # +回退INTRA_TEAM
    Stage.EVIDENCE_CHECK: {Stage.CROSS_TEAM, Stage.EVIDENCE_CHECK, Stage.ARBITRATE, Stage.PRODUCE},  # +回退CROSS_TEAM
    Stage.ARBITRATE: {Stage.EVIDENCE_CHECK, Stage.CROSS_TEAM, Stage.ARBITRATE, Stage.PRODUCE},  # +回退EVIDENCE_CHECK/CROSS_TEAM
    Stage.PRODUCE: set(),  # 终态
}

# 最大循环次数：防止元认知 Agent 无限循环
_MAX_LOOP_COUNT: dict[Stage, int] = {
    Stage.INTRA_TEAM: 3,
    Stage.CROSS_TEAM: 2,
    Stage.EVIDENCE_CHECK: 2,
    Stage.ARBITRATE: 2,
}

# 阶段循环计数器（存在 state 上，不在 models 中定义以减少迁移）
_STAGE_LOOP_KEY = "_stage_loop_count"


def _get_loop_count(state: MeetingState, stage: Stage) -> int:
    """获取某阶段的循环计数"""
    if not hasattr(state, _STAGE_LOOP_KEY):
        setattr(state, _STAGE_LOOP_KEY, {})
    counts = getattr(state, _STAGE_LOOP_KEY)
    return counts.get(stage.value, 0)


def _inc_loop_count(state: MeetingState, stage: Stage) -> None:
    """递增某阶段的循环计数"""
    if not hasattr(state, _STAGE_LOOP_KEY):
        setattr(state, _STAGE_LOOP_KEY, {})
    counts = getattr(state, _STAGE_LOOP_KEY)
    counts[stage.value] = counts.get(stage.value, 0) + 1


def _build_state_summary(state: MeetingState) -> str:
    """构建当前状态摘要，供元认知 Agent 决策"""
    parts = [
        f"当前阶段: {state.stage.value}",
        f"辩论深度: {state.debate_depth}",
        f"议题: {state.clarified_topic or state.topic}",
    ]
    if state.key_questions:
        parts.append(f"关键问题: {', '.join(state.key_questions[:3])}")
    if state.team_config:
        parts.append(f"团队: {len(state.team_config)} 人")
    if state.messages:
        parts.append(f"已发言: {len(state.messages)} 条")
    if state.claims:
        parts.append(f"论点: {len(state.claims)} 个")
    if state.conflicts:
        parts.append(f"未解决冲突: {len(state.conflicts)} 个")
        for c in state.conflicts[:3]:
            parts.append(f"  - {c.get('summary', c.get('id', '?'))[:80]}")
    if state.decision_record:
        parts.append("已有裁决记录")
    # 注入消息
    unprocessed = [inj for inj in state.injected_messages
                   if inj.get("signal") == "inject" and not inj.get("rejected")]
    if unprocessed:
        parts.append(f"未处理用户注入: {len(unprocessed)} 条")
    # 置信度
    if state.confidence_flags:
        low_stages = [s for s, f in state.confidence_flags.items() if f in ("low", "fallback")]
        if low_stages:
            parts.append(f"低置信度阶段: {', '.join(low_stages)}")
    return "\n".join(parts)


async def decide_next_stage(state: MeetingState) -> Stage:
    """元认知 Agent：基于当前状态决定下一阶段

    只在 dynamic_routing=True 时调用。
    返回下一个阶段（Stage 枚举），由 runner 决定是否执行。
    """
    current = state.stage
    valid_next = _VALID_NEXT_STAGES.get(current, set())

    # 如果已在终态或无可选，返回 produce
    if current == Stage.PRODUCE or not valid_next:
        return Stage.PRODUCE

    # 如果只剩 produce 一个选项，直接返回
    if valid_next == {Stage.PRODUCE}:
        return Stage.PRODUCE

    # 检查循环上限：达到上限时推进到下一个固定阶段，而非直接跳到 PRODUCE
    max_loops = _MAX_LOOP_COUNT.get(current, 1)
    loop_count = _get_loop_count(state, current)
    if loop_count >= max_loops:
        from conclave_core.state import next_stage as _ns
        forced_next = _ns(current, state.flow_plan)
        if forced_next and forced_next in valid_next:
            # 推进到管线中的下一个阶段（非PRODUCE），给后续阶段发言机会
            return forced_next
        # 没有更多后续阶段，才返回 PRODUCE
        return Stage.PRODUCE

    # ===== 辩论深度强制阶段保护 =====
    # 防止 LLM 元认知 Agent（尤其是 Flash 模型）过于激进地跳过关键讨论阶段
    # 通过 conclusion_chain 中已锁定的阶段判断哪些阶段已被执行
    visited_stages = {c.stage for c in state.conclusion_chain.conclusions}

    mandatory_stages: set[Stage] = set()
    if state.debate_depth == "deep":
        # 深度辩论：所有中间阶段必须至少执行一次
        for s in (Stage.INTRA_TEAM, Stage.CROSS_TEAM, Stage.EVIDENCE_CHECK, Stage.ARBITRATE):
            if s.value not in visited_stages:
                mandatory_stages.add(s)
    elif state.debate_depth == "standard":
        # 标准辩论：intra_team 必须执行；有冲突时 evidence_check 也必须执行
        if Stage.INTRA_TEAM.value not in visited_stages:
            mandatory_stages.add(Stage.INTRA_TEAM)
        if state.conflicts and Stage.EVIDENCE_CHECK.value not in visited_stages:
            mandatory_stages.add(Stage.EVIDENCE_CHECK)
    elif state.debate_depth == "light":
        # 轻量辩论：快速但不跳过——至少执行 intra_team（一轮队内发言）和 arbitrate（仲裁）
        if Stage.INTRA_TEAM.value not in visited_stages:
            mandatory_stages.add(Stage.INTRA_TEAM)
        if Stage.ARBITRATE.value not in visited_stages and Stage.INTRA_TEAM.value in visited_stages:
            # intra_team跑完后必须经过arbitrate才能到produce
            mandatory_stages.add(Stage.ARBITRATE)

    if mandatory_stages:
        # 只保留强制阶段 + produce（作为最终兜底出口）
        forced_choices = (mandatory_stages | {Stage.PRODUCE}) & valid_next
        if forced_choices and Stage.PRODUCE not in mandatory_stages:
            # 强制阶段未执行完毕时，只允许选择强制阶段（排除 PRODUCE 终态出口）。
            # 注意：不能无条件排除 ARBITRATE——当 ARBITRATE 本身就是强制阶段时
            # （如 light 深度在 INTRA_TEAM 完成后），排除它会导致收窄结果为空集，
            # valid_next 不变，LLM 仍可跳过仲裁直接选 produce。
            forced_no_produce = forced_choices - {Stage.PRODUCE}
            if forced_no_produce:
                # 仍有强制阶段要跑，缩小 LLM 选择范围
                valid_next = forced_no_produce

    # 标准辩论：无冲突时跳过 evidence_check（cross_team后直接arbitrate）
    if state.debate_depth == "standard" and current == Stage.CROSS_TEAM:
        if not state.conflicts:
            return Stage.ARBITRATE if Stage.ARBITRATE in valid_next else Stage.PRODUCE

    # 调用 LLM 做元认知决策
    try:
        from app.agents.compute import execute_think, ThinkRequest
        summary = _build_state_summary(state)
        valid_stages_str = ", ".join(s.value for s in valid_next)

        # 构建强制阶段提示（如果 valid_next 被收窄了）
        mandatory_hint = ""
        if mandatory_stages:
            ms_names = ", ".join(s.value for s in mandatory_stages)
            mandatory_hint = (
                f"\n## 强制阶段\n"
                f"以下阶段尚未执行，必须至少完成一次后才能跳过：{ms_names}\n"
                f"在上述强制阶段全部完成之前，请不要选择 produce（最终产出）。\n"
            )

        prompt = (
            f"你是会议流程的元认知控制器。根据当前会议状态，决定下一个最合适的阶段。\n\n"
            f"## 当前状态\n{summary}\n\n"
            f"## 可选下一阶段\n{valid_stages_str}\n"
            f"{mandatory_hint}\n"
            f"## 决策规则\n"
            f"- 每个关键阶段（intra_team, cross_team, evidence_check）都应至少执行一次，不要跳过\n"
            f"- 如果核心问题已解决且所有必要阶段已完成，选择 produce\n"
            f"- 如果仍有未解决的冲突，选择 evidence_check 或 arbitrate\n"
            f"- 如果论点不够充分，可以重复当前阶段（intra_team/cross_team）\n"
            f"- 如果证据对照发现新冲突或证据不足，可以回退到 cross_team 重新辩论\n"
            f"- 回退有成本（额外 token + 延迟），仅在必要时使用\n"
            f"- 辩论深度为 {state.debate_depth}，轻量级应尽快结束\n\n"
            f"只输出一个阶段名称（小写英文），不要任何其他内容。"
        )

        resp = await execute_think(ThinkRequest(
            agent_role="meta_cognition",
            stage="meta",
            prompt=prompt,
            schema_hint="meta_next_stage",
            temperature=0,
            seed=42,
            model=_resolve_model_for_routing(state),
        ))

        next_stage_str = (resp.result.get("next_stage", "") if isinstance(resp.result, dict)
                          else str(resp.result)).strip().lower()

        # 验证输出
        for stage in Stage:
            if stage.value == next_stage_str and stage in valid_next:
                return stage

        # 回退：按固定顺序前进
        from conclave_core.state import next_stage as _ns
        fallback = _ns(current, state.flow_plan)
        if fallback and fallback in valid_next:
            return fallback

    except Exception:
        pass

    # 最终回退
    from conclave_core.state import next_stage as _ns
    return _ns(current, state.flow_plan) or Stage.PRODUCE
