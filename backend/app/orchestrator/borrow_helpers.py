# Borrow helpers: 借调 agent 发言 + 主持人借调评估
# 从 nodes/borrow.py 提取到 orchestrator 层，消除 stage_runners 对 nodes/ 的反向依赖。
# nodes/borrow.py 保留 re-export 以向后兼容。
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.agents.compute import execute_think, build_intra_prompt, ThinkRequest
from app.agents.role_templates import get_borrow_prompt
from app.config import settings
from app.events import bus, make_event
from app.models import MeetingState, Role, Stage
from app.observability.log_bus import log_bus
from conclave_core.charter_logic import is_already_borrowed, register_borrow
from conclave_core.roles import match_role as _match_role
from conclave_core.anchor import get_full_anchor as _full_anchor
from conclave_core.text import format_claims_as_text as _format_claims_as_text

from app.orchestrator.stage_common import (
    record_message as _record_message,
    record_drift as _record_drift,
    resolve_model_for_call as _resolve_model_for_call,
)

# 角色ID -> 中文名称映射（用于借调prompt）
_ROLE_NAMES = {
    Role.MODERATOR: "主持人",
    Role.PRODUCT_ARCHITECT: "产品架构师",
    Role.ENGINEER: "工程师",
    Role.SECURITY_EXPERT: "安全专家",
    Role.DATA_ENGINEER: "数据工程师",
    Role.UX_DESIGNER: "UX设计师",
    Role.MARKETING_EXPERT: "市场专家",
}

# 可借调的角色列表（排除已在团队中的 moderator 和基本角色）
_BORROWABLE_ROLES = [
    {"id": "security_expert", "name": "安全专家", "desc": "安全、风控、合规、数据隐私"},
    {"id": "data_engineer", "name": "数据工程师", "desc": "数据建模、ETL、分析、数据架构"},
    {"id": "ux_designer", "name": "UX设计师", "desc": "用户体验、交互设计、可用性"},
    {"id": "marketing_expert", "name": "市场专家", "desc": "市场定位、增长策略、用户获取"},
]

# 自动借调阈值：超过此次数需用户审批
AUTO_BORROW_THRESHOLD = 3


async def _let_borrowed_agents_speak(state: MeetingState, stage: Stage) -> None:
    """让待发言（spoken=False）的借调 agent 发言一次，然后标记 spoken=True

    借调角色现在走真实 LLM 调用（用专门的借调回应 prompt），
    让 agent 针对借调申请中的具体需求/问题立即给出专业回应。
    """
    if not state.borrowed_agents:
        return
    topic = state.clarified_topic or state.topic
    for agent_info in state.borrowed_agents:
        if agent_info.get("spoken"):
            continue
        role_str = agent_info.get("role", "")
        request_info = agent_info.get("request", {}) or {}
        borrow_goal = request_info.get("goal", "")
        borrow_necessary = request_info.get("necessary", "")
        borrow_no_loan_cost = request_info.get("no_loan_cost", "")
        # 尝试匹配 Role 枚举，走真实 LLM
        matched_role = _match_role(role_str)
        if matched_role is not None:
            try:
                anchor = _full_anchor(state, stage.value)
                # 针对借调需求构建专门的 prompt，让agent直接回应急需解决的问题
                if borrow_goal:
                    # 新借调agent：针对借调需求立即回应
                    role_name = _ROLE_NAMES.get(matched_role, matched_role.value)
                    borrow_prompt = f"""[系统] 你是{role_name}，被临时借调来解决当前讨论中的专业盲区。请直接针对以下紧急问题给出你的专业意见。

议题：{topic}

借调原因 - 需要解决的问题：{borrow_goal}
必要性说明：{borrow_necessary}
不借调的代价：{borrow_no_loan_cost}

{anchor}

请直接给出你的专业回应：
1. 针对上述问题，从你的专业角度给出明确的观点和建议
2. 提出2-4条具体的claims（主张），每条必须包含可验证的内容
3. 如果发现现有讨论中存在错误或盲点，请明确指出
4. 不要做自我介绍，直接进入正题

输出JSON：{{"claims": [{{"claim": "你的主张", "confidence": 0.0-1.0, "evidence": "支撑证据或推理"}}]}}"""
                    req = ThinkRequest(
                        meeting_id=state.meeting_id,
                        agent_role=matched_role.value,
                        stage=stage.value,
                        prompt=borrow_prompt,
                        temperature=0.3,
                        schema_hint=f"borrow_{stage.value}",
                        model=_resolve_model_for_call(state, matched_role.value, stage.value),
                    )
                else:
                    # 无特定goal（旧数据兼容），使用通用intra prompt
                    req = build_intra_prompt(matched_role, topic, request_info.get("stance", ""), anchor=anchor)
                    req.model = _resolve_model_for_call(state, matched_role.value, stage.value)
                resp = await execute_think(req)
                claims = resp.result.get("claims", [])
                claim_ids: list[str] = []
                for c in claims:
                    cid = f"claim-{uuid.uuid4().hex[:8]}"
                    c["id"] = cid
                    c["agent_role"] = role_str
                    state.claims.append(c)
                    claim_ids.append(cid)
                content = _format_claims_as_text(claims, role_str)
                msg = _record_message(state, matched_role, stage, content, claim_ids)
                await bus.publish(
                    make_event("agent.spoke", state.meeting_id, {
                        "meeting_id": state.meeting_id,
                        "role": role_str,
                        "stage": stage.value,
                        "content": content,
                        "claim_refs": claim_ids,
                        "message_id": msg["id"],
                        "borrowed": True,
                    })
                )
                _record_drift(state, matched_role, stage, content)
                agent_info["spoken"] = True
                continue
            except Exception:
                # LLM 失败时回退到静态模板，保证流程不中断
                pass
        # 回退：未匹配 Role 或 LLM 失败，用静态模板
        prompt = get_borrow_prompt(role_str)
        content = (
            f"{prompt}\n"
            f"针对议题「{topic}」，我基于本领域专业视角补充意见："
            f"建议在决策中重点考虑本领域的关键风险与约束，避免遗漏。"
        )
        if borrow_goal:
            content = f"{prompt}\n针对本次借调需要解决的问题「{borrow_goal}」，我的专业意见是：建议重点关注本领域的核心约束和最佳实践，确保方案在专业维度上可行。"
        msg = {
            "id": f"msg-{uuid.uuid4().hex[:8]}",
            "meeting_id": state.meeting_id,
            "agent_role": role_str,
            "stage": stage.value,
            "content": content,
            "claim_refs": [],
            "evidence_refs": [],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        state.messages.append(msg)
        await bus.publish(
            make_event(
                "agent.spoke",
                state.meeting_id,
                {
                    "meeting_id": state.meeting_id,
                    "role": role_str,
                    "stage": stage.value,
                    "content": content,
                    "claim_refs": [],
                    "message_id": msg["id"],
                    "borrowed": True,
                },
            )
        )
        _record_drift(state, role_str, stage, content)
        agent_info["spoken"] = True


# ---------- 自动借调评估：主持人判断是否需要补充角色 ----------

async def _moderator_assess_borrow(state: MeetingState, stage: Stage) -> None:
    """主持人评估当前团队是否需要借调额外角色

    流程：
    1. 主持人LLM评估当前辩论/讨论中是否存在专业盲区
    2. 如果需要借调，生成三问内容
    3. 自动通过次数 < 3 -> 主持人自动审批通过
    4. 自动通过次数 >= 3 -> 挂起等待用户审批
    """
    # 前置检查
    if state.charter is None:
        return
    if state.borrow_frozen:
        return  # 借调已被用户冻结，不再发起新申请
    if state.pending_borrow_request is not None:
        return  # 已有待审批申请，不再发起新的
    if len(state.borrowed_agents) >= 2:
        return  # 已达借调上限
    # 已借调过的角色不再申请
    already_borrowed = {b["role"] for b in state.borrowed_agents}
    # 当前团队角色
    current_roles = {tc.get("role", "") for tc in state.team_config}
    available_roles = [r for r in _BORROWABLE_ROLES if r["id"] not in already_borrowed and r["id"] not in current_roles]
    if not available_roles:
        return

    # 取最近的发言（最多20条）作为评估上下文
    recent_msgs = state.messages[-20:] if len(state.messages) > 20 else state.messages
    recent_text = "\n".join(
        f"[{m.get('agent_role', '?')}] {m.get('content', '')[:200]}"
        for m in recent_msgs
    )

    topic = state.clarified_topic or state.topic
    current_role_names = ", ".join(
        tc.get("role", "") for tc in state.team_config
    )
    available_role_desc = "\n".join(
        f"- {r['id']}({r['name']}): {r['desc']}" for r in available_roles
    )

    assess_prompt = f"""[系统] 你是 Conclave 会议主持人。当前正在进行「{stage.value}」阶段。

议题：{topic}
当前团队成员：{current_role_names}
已借调角色：{", ".join(already_borrowed) if already_borrowed else "无"}
自动借调已用次数：{state.auto_borrow_count}/{AUTO_BORROW_THRESHOLD}

可借调的角色：
{available_role_desc}

最近讨论内容：
{recent_text}

请评估：基于当前讨论内容，团队是否存在专业盲区？是否需要借调额外角色来补充视角？

判断标准：
1. 如果当前讨论中频繁涉及某个可借调角色的专业领域（如反复讨论安全问题但团队中无安全专家），则需要借调
2. 如果现有团队角色已能覆盖讨论需要，则不需要借调
3. 谨慎借调：仅在确实存在明显专业缺口时才申请

输出严格 JSON：
{{
  "need_borrow": true/false,
  "target_role": "角色ID（从可借调角色中选择，不需要则为空字符串）",
  "goal": "借调目标（一句话说明需要该角色解决什么问题）",
  "necessary": "必要性说明（为什么现有团队无法覆盖）",
  "no_loan_cost": "不借调的代价（缺少该角色可能导致什么问题）"
}}"""

    try:
        req = ThinkRequest(
            meeting_id=state.meeting_id,
            agent_role=Role.MODERATOR.value,
            stage=stage.value,
            prompt=assess_prompt,
            temperature=0.2,
            seed=settings.llm_seed,
            schema_hint=f"borrow_assess_{stage.value}",
            model=_resolve_model_for_call(state, Role.MODERATOR.value, stage.value),
        )
        resp = await execute_think(req)
        result = resp.result
        need_borrow = result.get("need_borrow", False)
        target_role = str(result.get("target_role", "")).strip()

        if not need_borrow or not target_role:
            return
        # 验证目标角色在可用列表中
        valid_role = next((r for r in available_roles if r["id"] == target_role), None)
        if valid_role is None:
            return
        # 防止重复借调
        if is_already_borrowed(state.charter, target_role):
            return

        request_id = f"breq-{uuid.uuid4().hex[:8]}"
        borrow_request = {
            "id": request_id,
            "requester": "moderator",
            "target_role": target_role,
            "goal": str(result.get("goal", "")),
            "necessary": str(result.get("necessary", "")),
            "no_loan_cost": str(result.get("no_loan_cost", "")),
            "requested_at": datetime.now(timezone.utc).isoformat(),
            "stage": stage.value,
        }

        # 判断是自动通过还是需要用户审批
        if state.auto_borrow_count < AUTO_BORROW_THRESHOLD:
            # 主持人自动审批通过
            register_borrow(state.charter, target_role, "approve_temporary")
            state.borrowed_agents.append({
                "role": target_role,
                "verdict": "approve_temporary",
                "spoken": False,
                "request": {
                    "target_role": target_role,
                    "goal": borrow_request["goal"],
                    "necessary": borrow_request["necessary"],
                    "no_loan_cost": borrow_request["no_loan_cost"],
                    "stance": "",
                },
                "auto_approved": True,
            })
            state.auto_borrow_count += 1
            state.borrow_request_history.append({
                **borrow_request,
                "verdict": "auto_approved",
                "approved_at": datetime.now(timezone.utc).isoformat(),
            })
            state.injected_messages.append({
                "signal": "borrow_auto_approved",
                "request_id": request_id,
                "target_role": target_role,
                "goal": borrow_request["goal"],
                "at_stage": stage.value,
            })
            # 广播事件：自动批准借调
            await bus.publish(
                make_event("borrow.auto_approved", state.meeting_id, {
                    "meeting_id": state.meeting_id,
                    "request_id": request_id,
                    "target_role": target_role,
                    "target_role_name": valid_role["name"],
                    "goal": borrow_request["goal"],
                    "auto_borrow_count": state.auto_borrow_count,
                })
            )
            # 主持人发言通知
            notice = (
                f"[主持人] 检测到讨论涉及{valid_role['name']}领域的专业问题，现有团队视角不足。"
                f"已自动批准借调{valid_role['name']}参与讨论。"
                f"（自动借调 {state.auto_borrow_count}/{AUTO_BORROW_THRESHOLD}）"
            )
            msg = _record_message(state, Role.MODERATOR, stage, notice)
            await bus.publish(
                make_event("agent.spoke", state.meeting_id, {
                    "meeting_id": state.meeting_id,
                    "role": Role.MODERATOR.value,
                    "stage": stage.value,
                    "content": notice,
                    "claim_refs": [],
                    "message_id": msg["id"],
                    "system_notice": True,
                })
            )
        else:
            # 超过阈值，挂起等待用户审批
            state.pending_borrow_request = borrow_request
            state.borrow_request_history.append({
                **borrow_request,
                "verdict": "pending_user",
            })
            # 广播事件：需要用户审批
            await bus.publish(
                make_event("borrow.awaiting_user", state.meeting_id, {
                    "meeting_id": state.meeting_id,
                    "request_id": request_id,
                    "target_role": target_role,
                    "target_role_name": valid_role["name"],
                    "goal": borrow_request["goal"],
                    "necessary": borrow_request["necessary"],
                    "no_loan_cost": borrow_request["no_loan_cost"],
                    "auto_borrow_count": state.auto_borrow_count,
                })
            )
            # 主持人发言通知
            notice = (
                f"[主持人] 检测到讨论涉及{valid_role['name']}领域的专业问题。"
                f"自动借调次数已达上限（{AUTO_BORROW_THRESHOLD}次），请审批是否借调。"
            )
            msg = _record_message(state, Role.MODERATOR, stage, notice)
            await bus.publish(
                make_event("agent.spoke", state.meeting_id, {
                    "meeting_id": state.meeting_id,
                    "role": Role.MODERATOR.value,
                    "stage": stage.value,
                    "content": notice,
                    "claim_refs": [],
                    "message_id": msg["id"],
                    "system_notice": True,
                })
            )
    except Exception as e:
        # 评估失败不阻塞流程
        log_bus.warning(f"自动借调评估失败: {e}", logger="orchestrator.borrow")
