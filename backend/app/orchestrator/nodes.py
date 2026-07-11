# 六阶段节点：每个 async def run(state) -> state，纯函数风格，副作用通过事件总线外溢
from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Awaitable

from app.agents.compute import (
    get_compute,
    build_clarify_prompt,
    build_intra_prompt,
    build_intra_react_prompt,
    build_cross_team_prompt,
    build_evidence_prompt,
    build_arbitrate_prompt,
    build_produce_prompt,
    ThinkRequest,
)
from app.agents.trace import set_current_trace
from app.events import bus, make_event
from app.models import MeetingState, MeetingStatus, Role, Stage
from app.observability.log_bus import log_bus
from app.orchestrator.charter import build_charter_from_clarify
from app.orchestrator.state import next_stage as _next_stage, get_skipped_stages
from app.rag.retriever import retrieve_for_conflict
from app.tools.web_search import get_web_search

# 节点签名：async def(state) -> state
Node = Callable[[MeetingState], Awaitable[MeetingState]]

# ---- 角色模糊匹配（模块级，支持中英文角色名）----
# 真实 LLM 可能返回中文角色名（"产品经理"、"后端架构师"等），
# StubLLM 返回英文角色名，此处统一模糊匹配。
_ROLE_KEYWORDS: dict[str, list[str]] = {
    Role.PRODUCT_ARCHITECT.value: ["product", "architect", "产品", "架构", "pm", "产品经理", "产品架构"],
    Role.SECURITY_EXPERT.value: ["security", "安全", "风控", "sec"],
    Role.DATA_ENGINEER.value: ["data", "数据", "analytics", "分析"],
    Role.UX_DESIGNER.value: ["ux", "design", "设计", "体验", "ui"],
    Role.MARKETING_EXPERT.value: ["marketing", "市场", "营销", "brand", "growth"],
    Role.ENGINEER.value: ["engineer", "develop", "开发", "工程", "后端", "前端", "技术"],
    Role.MODERATOR.value: ["moderator", "host", "主持", "协调", "facilitator"],
}


def _match_role(role_str: str) -> Role | None:
    """模糊匹配角色名（支持中英文）

    匹配规则：角色字符串（小写）中包含任一关键词即匹配。
    返回匹配的 Role 枚举，未匹配返回 None。
    """
    role_lower = role_str.lower()
    for role, keywords in _ROLE_KEYWORDS.items():
        for kw in keywords:
            if kw in role_lower:
                return Role(role)
    return None


def _anchor(state: MeetingState) -> str:
    """取会议宪章锚点文本，charter 不存在时返回空串"""
    if state.charter is None:
        return ""
    return state.charter.to_prompt_anchor()


def _record_drift(state: MeetingState, role: Role | str, stage: Stage, content: str) -> None:
    """对发言做宪章漂移检查并记录到 drift_log（非阻塞）

    role 支持枚举角色与借调角色的字符串角色名。
    """
    if state.charter is None or not content:
        return
    result = state.charter.check_drift(content)
    role_value = role.value if isinstance(role, Role) else str(role)
    state.drift_log.append(
        {
            "role": role_value,
            "stage": stage.value,
            "is_drift": result.is_drift,
            "severity": result.severity,
            "reason": result.reason,
            "content_preview": content[:120],
        }
    )


def _record_message(
    state: MeetingState,
    role: Role,
    stage: Stage,
    content: str,
    claim_refs: list[str] | None = None,
    evidence_refs: list[str] | None = None,
) -> dict[str, Any]:
    """记录发言到 state.messages 并返回消息字典（供事件 payload 复用）"""
    msg = {
        "id": f"msg-{uuid.uuid4().hex[:8]}",
        "meeting_id": state.meeting_id,
        "agent_role": role.value,
        "stage": stage.value,
        "content": content,
        "claim_refs": claim_refs or [],
        "evidence_refs": evidence_refs or [],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    state.messages.append(msg)
    return msg


async def _emit_agent_spoke(state: MeetingState, role: Role, stage: Stage, content: str,
                            claim_refs: list[str] | None = None) -> None:
    """发布 agent.spoke 事件"""
    msg = _record_message(state, role, stage, content, claim_refs)
    await bus.publish(
        make_event(
            "agent.spoke",
            state.meeting_id,
            {
                "meeting_id": state.meeting_id,
                "role": role.value,
                "stage": stage.value,
                "content": content,
                "claim_refs": claim_refs or [],
                "message_id": msg["id"],
            },
        )
    )


def _format_claims_as_text(claims: list[dict[str, Any]], role_label: str = "") -> str:
    """把 claims 列表格式化为自然可读文本。

    设计原则：
    - 每条论点独占一行，正文干净，不被标签打断
    - 元数据（风险等级、证据来源）换行缩进显示，用 [meta] 标签包裹，前端渲染为灰色小字元信息行
    - [type] 标签紧随编号，作为论点类型徽章（事实/假设/约束等）
    - evidence_ref 中紧跟标签后的解释性文字归入元信息行，不插在正文中打断阅读
    """
    if not claims:
        return "（暂无要点输出）"
    lines: list[str] = []
    for i, c in enumerate(claims, 1):
        claim_text = c.get("claim", c.get("text", "")).strip()
        ctype = c.get("type", "assumption")
        risk_level = c.get("risk_level")
        evidence_ref = c.get("evidence_ref", "").strip()

        # 主行：编号 + 类型标签 + 论点正文
        lines.append(f"{i}. [{ctype}] {claim_text}")

        # 元数据行：将 risk_level 和 evidence_ref 中的信息提取出来，换行缩进显示
        meta_parts: list[str] = []
        if risk_level:
            meta_parts.append(f"[risk:{risk_level}]")
        if evidence_ref:
            # evidence_ref 可能格式：[常识] 解释文字... 或 [doc:xxx] 或纯文本
            # 统一放入元信息行，标签保留为徽章，解释文字作为普通文本跟在后面
            meta_parts.append(evidence_ref)
        if meta_parts:
            # 用 [meta] 标记一个元信息行，前端识别后渲染为缩进灰色小字
            lines.append(f"   [meta] {' '.join(meta_parts)}")
    return "\n".join(lines)


def _format_arbitrate_as_text(
    decision_record: dict[str, Any],
    claims: list[dict[str, Any]],
    conflicts: list[dict[str, Any]],
) -> str:
    """把仲裁裁决格式化为可读文本。

    设计：不添加【角色·阶段】头（前端卡片已展示）；用自然段落呈现裁决结果。
    """
    # 构建 claim_id → claim 映射
    claim_map: dict[str, dict[str, Any]] = {}
    for c in claims:
        claim_map[c.get("id", "")] = c
    # 构建 conflict_id → conflict 映射
    conflict_map: dict[str, dict[str, Any]] = {}
    for cf in conflicts:
        conflict_map[cf.get("id", "")] = cf

    lines: list[str] = []

    # 采纳的论点 - 只展示前5条关键论点作为摘要，避免单条消息过长
    adopted = decision_record.get("adopted_claims", [])
    if adopted:
        lines.append(f"经审议，共采纳 {len(adopted)} 条核心论点。要点如下：")
        display_count = min(5, len(adopted))
        for i in range(display_count):
            cid = adopted[i]
            claim = claim_map.get(cid, {})
            ctype = claim.get("claim_type", claim.get("type", "assumption"))
            # LLM返回的字段名是"claim"，不是"text"；做多重回退
            text = claim.get("claim", claim.get("text", "")).strip()
            # 截断过长的论点文本
            if len(text) > 60:
                text = text[:57] + "…"
            if text:
                lines.append(f"  {i+1}. [{ctype}] {text}")
        if len(adopted) > display_count:
            lines.append(f"  …另有 {len(adopted) - display_count} 条论点已纳入最终产出。")
        lines.append("")

    # 裁决详情
    decisions = decision_record.get("decisions", [])
    if decisions:
        lines.append("对争议点的裁决：")
        for d in decisions:
            cid = d.get("conflict_id", "")
            verdict = d.get("verdict", "compromise")
            rationale = d.get("rationale", "")
            conflict = conflict_map.get(cid, {})
            side_a = conflict.get("side_a", "A 方观点")
            side_b = conflict.get("side_b", "B 方观点")
            verdict_label = {"a": f"采纳「{side_a}」", "b": f"采纳「{side_b}」", "compromise": "折中融合"}
            lines.append(f"  • {verdict_label.get(verdict, verdict)}：{rationale}")
    else:
        lines.append("本次议题各方观点一致，无冲突需裁决。")

    return "\n".join(lines)


# ---------- 改造三：借调 agent 发言 ----------

# 迭代二：借调角色 prompt 改为从动态角色库获取（替换原硬编码 BORROW_ROLE_PROMPTS）
from app.agents.role_templates import get_borrow_prompt


async def _let_borrowed_agents_speak(state: MeetingState, stage: Stage) -> None:
    """让待发言（spoken=False）的借调 agent 发言一次，然后标记 spoken=True

    借调角色现在走真实 LLM 调用（用专门的借调回应 prompt），
    让 agent 针对借调申请中的具体需求/问题立即给出专业回应。
    """
    if not state.borrowed_agents:
        return
    topic = state.clarified_topic or state.topic
    compute = get_compute()
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
                        schema_hint=f"borrow_{stage.value}",  # [AUDIT-FIX P1-2] 补全 schema_hint
                    )
                else:
                    # 无特定goal（旧数据兼容），使用通用intra prompt
                    req = build_intra_prompt(matched_role, topic, request_info.get("stance", ""), anchor=anchor)
                resp = await compute.think(req)
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

# 角色ID → 中文名称映射（用于借调prompt）
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


async def _moderator_assess_borrow(state: MeetingState, stage: Stage) -> None:
    """主持人评估当前团队是否需要借调额外角色

    流程：
    1. 主持人LLM评估当前辩论/讨论中是否存在专业盲区
    2. 如果需要借调，生成三问内容
    3. 自动通过次数 < 3 → 主持人自动审批通过
    4. 自动通过次数 >= 3 → 挂起等待用户审批
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
        compute = get_compute()
        req = ThinkRequest(
            meeting_id=state.meeting_id,
            agent_role=Role.MODERATOR.value,
            stage=stage.value,
            prompt=assess_prompt,
            temperature=0.2,
            seed=42,
            schema_hint=f"borrow_assess_{stage.value}",  # [AUDIT-FIX P1-2] 补全 schema_hint
        )
        resp = await compute.think(req)
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
        if state.charter.is_already_borrowed(target_role):
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
            state.charter.register_borrow(target_role, "approve_temporary")
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


# ---------- 第3层：一致性自检 + 结论锁定辅助 ----------

# 置信度等级排序（值越大越差）
_CONFIDENCE_RANK: dict[str, int] = {"high": 0, "low": 1, "fallback": 2}


def _full_anchor(state: MeetingState, stage: str) -> str:
    """构造完整锚点：宪章锚点 + 已锁定结论上下文 + 历史会议引用上下文

    第3层：每个节点调 agent 前把 chain.get_locked_context(stage) 注入到 anchor 里
    （和 charter anchor 一起拼到 prompt 前）。
    """
    parts: list[str] = []
    charter_anchor = _anchor(state)
    if charter_anchor:
        parts.append(charter_anchor)
    locked_context = state.conclusion_chain.get_locked_context(stage)
    if locked_context:
        parts.append(locked_context)
    # 注入历史会议引用上下文（创建时指定的 + 运行中动态注入的）
    if state.reference_context:
        parts.append(state.reference_context)
    return "\n\n".join(parts) if parts else ""


def _worst_confidence(a: str, b: str) -> str:
    """返回两个置信度中较差的一个"""
    return a if _CONFIDENCE_RANK.get(a, 0) >= _CONFIDENCE_RANK.get(b, 0) else b


def _update_trace_consistency(state: MeetingState, start_pos: int, status: str) -> None:
    """更新 trace 中自 start_pos 以来所有记录的 consistency_status"""
    for call in state.llm_trace.calls[start_pos:]:
        call.consistency_status = status


async def _run_with_consistency(
    state: MeetingState,
    stage: str,
    call_fn: Callable[[str], Awaitable[dict[str, Any]]],
) -> tuple[dict[str, Any], str]:
    """带一致性自检的 LLM 调用

    流程：
    1. 用完整锚点（宪章 + 已锁定结论上下文）调 LLM
    2. 调 chain.check_consistency(result, stage) 检查一致性
    3. 如果不一致：把矛盾信息追加到 anchor 重调 LLM（最多 2 次重试）
    4. 重试后仍不一致：标记为 low_confidence，记录到 state 但不中断流程
    5. 如果一致：返回结果和置信度

    返回 (最终结果, confidence: "high" | "low" | "fallback")
    """
    chain = state.conclusion_chain
    base_anchor = _full_anchor(state, stage)

    # 记录 trace 起始位置（用于后续更新一致性状态）
    start_pos = len(state.llm_trace.calls)

    # 首次调用
    result = await call_fn(base_anchor)
    consistency = chain.check_consistency(result, stage)

    retries = 0
    while not consistency.is_consistent and retries < 2:
        retries += 1
        # 把矛盾信息追加到 anchor 重调
        contradiction = "；".join(consistency.violations)
        augmented_anchor = (
            f"{base_anchor}\n\n"
            f"【一致性警告】你的输出与已确认结论矛盾：{contradiction}。"
            f"请基于已确认结论重新输出，不得与之矛盾。"
        )
        result = await call_fn(augmented_anchor)
        consistency = chain.check_consistency(result, stage)

    # 确定置信度并更新 trace 一致性状态
    if not consistency.is_consistent:
        # 重试后仍不一致：标记 low_confidence，不中断流程
        _update_trace_consistency(state, start_pos, "low_confidence")
        confidence = "low"
    elif retries > 0:
        # 重试后通过
        _update_trace_consistency(state, start_pos, "inconsistent_retry")
        confidence = "low"
    else:
        # 首次即通过
        _update_trace_consistency(state, start_pos, "consistent")
        confidence = "high"

    # 检查是否有降级到 stub（仅 RealLLM 会记录 fallback_stub）
    if any(
        c.validation_status == "fallback_stub"
        for c in state.llm_trace.calls[start_pos:]
    ):
        confidence = "fallback"

    return result, confidence


async def clarify_node(state: MeetingState) -> MeetingState:
    """Clarify 阶段：主持人澄清议题，确认团队组成，构造会议宪章"""
    # 设置 trace 上下文（RealLLM 会记录调用，stub 静默跳过）
    set_current_trace(state.llm_trace)
    compute = get_compute()

    # 带一致性自检的 LLM 调用：构造 ThinkRequest 并经 compute 接口执行
    async def call_fn(anchor: str) -> dict[str, Any]:
        req = build_clarify_prompt(state.topic, state.doc_summaries, anchor=anchor, reference_context=state.reference_context)
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
        content = "跨队辩论结束，各方观点一致，未发现争议点。"
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


def _make_common_knowledge_evidence(conflict: dict) -> list[dict]:
    """无文档/网络证据时的降级：为每个冲突生成双方向通用工程原则证据。

    替代旧的单条中性占位符，让 evidence_check 仍有方向可判断：
    - ev-a：呼应 side_a 立场的通用原则
    - ev-b：呼应 side_b 立场的通用原则
    标记 strength=weak 和 source=common_knowledge，让 LLM 知道这是弱证据。
    """
    side_a = conflict.get("side_a", "")
    side_b = conflict.get("side_b", "")
    summary = conflict.get("summary", str(conflict))
    return [
        {
            "evidence_id": "ev-a",
            "quote": f"（通用工程实践 · 倾向 A 方）{side_a or summary}。此原则基于行业常识，非具体文档证据，需用户验证。",
            "source": "common_knowledge:side_a",
            "char_range": [0, 0],
            "strength": "weak",
        },
        {
            "evidence_id": "ev-b",
            "quote": f"（通用工程实践 · 倾向 B 方）{side_b or summary}。此原则基于行业常识，非具体文档证据，需用户验证。",
            "source": "common_knowledge:side_b",
            "char_range": [0, 0],
            "strength": "weak",
        },
    ]


def _detect_network_level(code: str) -> str:
    """根据代码内容自动判断需要的沙箱网络级别

    L1(无网络)：默认，纯计算代码
    L2(限网)：包含 pip install，需要安装依赖
    L3(全联网)：包含 requests/urllib/httpx/http(s)://，需要访问外部 API

    判断逻辑：
    1. 有 pip install → L2（需要 pypi）
    2. 有 HTTP 库 import 或 URL → L3（需要联网）
    3. 其他 → L1（纯计算）
    """
    code_lower = code.lower()

    # L3: 外部 HTTP 请求
    http_indicators = [
        "import requests", "from requests",
        "import urllib", "from urllib",
        "import httpx", "from httpx",
        "import aiohttp", "from aiohttp",
        "http://", "https://",
        "urlopen", "requests.get", "requests.post",
    ]
    for indicator in http_indicators:
        if indicator in code_lower:
            return "L3"

    # L2: pip install
    if "pip install" in code_lower or "subprocess" in code_lower and "pip" in code_lower:
        return "L2"

    # L1: 默认纯计算
    return "L1"


def _scan_artifacts(ws_root: Path, meeting_id: str) -> list[dict[str, Any]]:
    """扫描沙箱工作区，收集产出的文件作为附件。

    ws_root 可以是 workspace 根目录（自动找 meeting_id 子目录），
    也可以已经是 meeting_id 子目录（不再重复拼接）。
    支持代码文件、文档、图片等常见产出类型。
    返回附件元数据列表，文件本体保留在 workspace 中通过 API 下载。
    """
    attachments: list[dict[str, Any]] = []
    # 支持的文件扩展名（含代码文件）
    supported_exts = {
        # 代码
        ".py", ".js", ".jsx", ".ts", ".tsx", ".html", ".css", ".vue", ".java", ".go", ".rs",
        ".yml", ".yaml", ".toml", ".ini", ".cfg", ".sh", ".bat", ".ps1", ".sql",
        # 文档/数据
        ".md", ".txt", ".json", ".csv", ".log", ".pdf", ".doc", ".docx",
        # 图片
        ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp",
    }
    # 无扩展名但重要的文件
    supported_noext = {"Dockerfile", "Makefile", "README", "LICENSE", ".env", ".gitignore"}

    # 智能判断扫描目录：如果 ws_root 末尾已经是 meeting_id，直接扫描
    if ws_root.name == meeting_id and ws_root.exists() and ws_root.is_dir():
        scan_dir = ws_root
    else:
        # 否则优先找 meeting_id 子目录，不存在则扫 ws_root 本身
        meeting_dir = ws_root / meeting_id
        scan_dir = meeting_dir if meeting_dir.exists() and meeting_dir.is_dir() else ws_root

    if not scan_dir.exists():
        return attachments

    for f in sorted(scan_dir.iterdir()):
        if not f.is_file():
            continue
        # 匹配扩展名或无扩展名的知名文件
        is_supported = (
            f.suffix.lower() in supported_exts
            or f.name in supported_noext
            or (not f.suffix and f.name.startswith("Dockerfile"))
        )
        if not is_supported:
            continue
        try:
            stat = f.stat()
        except OSError:
            continue
        # 附件"path"字段是相对于 workspace 根的路径（便于 API 下载）
        # 找到 workspace 根（即包含 meeting_id 作为其子目录的那个目录）
        if ws_root.name == meeting_id:
            rel_path = f"{meeting_id}/{f.name}"
        elif (ws_root / meeting_id).exists():
            rel_path = f"{meeting_id}/{f.name}"
        else:
            rel_path = f.name
        attachments.append({
            "filename": f.name,
            "path": rel_path,
            "size": stat.st_size,
            "ext": f.suffix.lower().lstrip(".") if f.suffix else "",
            "meeting_id": meeting_id,
        })
    return attachments


async def _collect_evidence(meeting_id: str, conflict: dict) -> list[dict]:
    """为单个冲突检索证据（RAG + Web Search + 通用知识降级）

    统一检索流程：cross_team 预检索和 evidence_check 实时检索共用此函数（DRY）。
    """
    summary = conflict.get("summary", str(conflict))
    chunks = await retrieve_for_conflict(meeting_id, summary, top_k=5)
    evidence_chunks = [
        {
            "evidence_id": f"ev-{i}",
            "quote": ck.get("text", "")[:200],
            "source": ck.get("source", "doc:unknown"),
            "char_range": [ck.get("char_start", 0), ck.get("char_end", 0)],
            # 附带邻居上下文（让 LLM 看到证据所在段落的上下文）
            "context": ck.get("neighbor_context", ""),
        }
        for i, ck in enumerate(chunks)
    ]
    if len(evidence_chunks) < 3:
        web_search = get_web_search()
        web_results = await web_search.search(summary, top_k=3)
        for i, wr in enumerate(web_results):
            evidence_chunks.append({
                "evidence_id": f"web-{i}",
                "quote": wr.get("quote", "")[:200],
                "source": wr.get("source", "web:unknown"),
                "char_range": [0, 0],
            })
    if not evidence_chunks:
        evidence_chunks = _make_common_knowledge_evidence(conflict)
    return evidence_chunks


async def _prefetch_evidence(state: MeetingState, conflicts: list[dict]) -> dict[str, list[dict]]:
    """预检索所有冲突的证据（流水线优化：与借调发言并行）

    返回 {conflict_id: [evidence_chunks]} 字典，evidence_check 节点优先使用。
    """
    async def _retrieve_one(conflict: dict) -> tuple[str, list[dict]]:
        cid = conflict.get("id", "c0")
        chunks = await _collect_evidence(state.meeting_id, conflict)
        return cid, chunks

    # 并行检索所有冲突
    results = await asyncio.gather(*[_retrieve_one(c) for c in conflicts])
    return {cid: chunks for cid, chunks in results}


async def evidence_check_node(state: MeetingState) -> MeetingState:
    """EvidenceCheck 阶段：并行 RAG 检索证据 + 并行对照判断

    优化：逐冲突串行 → 全部并行（asyncio.gather）
    - 每个冲突独立做 RAG 检索 + Web Search + LLM 思考
    - 支持 ReactLoop 多轮工具调用（如果工具注册表可用）
    - 副作用（事件发布）串行收集
    """
    # 设置 trace 上下文
    set_current_trace(state.llm_trace)
    compute = get_compute()
    worst_confidence = "high"

    # ---- Phase 0：准备工具注册表（如果可用）----
    tool_registry = None
    try:
        from app.orchestrator.react_loop import ReactLoop, create_default_tool_registry
        tool_registry = create_default_tool_registry()
    except Exception:
        pass  # 工具注册失败时降级为无工具模式

    # ---- Phase 1：使用预检索结果或并行检索（流水线优化）----
    # cross_team 阶段已预检索的证据存在 state.prefetched_evidence
    # [UNIQ-07 修复] 旧版 _prefetched_evidence 字段名（下划线前缀）pydantic 不序列化，
    # 进程崩溃重启后丢失；改为 prefetched_evidence（无下划线）后持久化生效。
    # 兼容旧快照：getattr + None fallback
    prefetched = getattr(state, "prefetched_evidence", None) or getattr(
        state, "_prefetched_evidence", None
    )

    if prefetched:
        # 使用预检索结果（已由 cross_team 阶段提前完成）
        retrieval_results = [
            (conflict, prefetched.get(conflict.get("id", "c0"), []))
            for conflict in state.conflicts
        ]
    else:
        # 无预检索时，并行检索（兼容旧路径）
        async def _retrieve_evidence(conflict: dict) -> tuple[dict, list[dict]]:
            """为单个冲突检索证据（委托 _collect_evidence 统一流程）"""
            chunks = await _collect_evidence(state.meeting_id, conflict)
            return conflict, chunks

        retrieval_results = await asyncio.gather(
            *[_retrieve_evidence(c) for c in state.conflicts]
        )

    # ---- Phase 2：并行 LLM 思考（每个冲突独立思考，支持 ReactLoop）----
    async def _think_one_conflict(
        conflict: dict, evidence_chunks: list[dict]
    ) -> tuple[dict[str, Any], str, dict, list[dict]]:
        """对单个冲突做带一致性自检的 LLM 调用（支持 ReactLoop 多轮）"""
        # 如果工具注册表可用，使用 ReactLoop 多轮模式
        if tool_registry is not None:
            try:
                react = ReactLoop(
                    compute=compute,
                    tools=tool_registry,
                    meeting_id=state.meeting_id,
                )
                # 构建初始 prompt（含工具描述）
                anchor = _full_anchor(state, "evidence_check")
                req = build_evidence_prompt(conflict, evidence_chunks, anchor=anchor,
                                            available_tools=tool_registry.get_available_tools())
                # ReactLoop 多轮执行（默认 10 轮，可通过 REACT_MAX_ITERATIONS 环境变量配置）
                resp = await react.run(req)
                result = resp.result
                confidence = resp.confidence if hasattr(resp, 'confidence') else "high"
                return result, confidence, conflict, evidence_chunks
            except Exception:
                # ReactLoop 失败时降级到单次调用
                pass

        # 降级：单次 LLM 调用（无工具）
        async def call_fn(anchor: str, _conflict=conflict, _chunks=evidence_chunks) -> dict[str, Any]:
            req = build_evidence_prompt(_conflict, _chunks, anchor=anchor)
            resp = await compute.think(req)
            return resp.result

        result, confidence = await _run_with_consistency(state, "evidence_check", call_fn)
        return result, confidence, conflict, evidence_chunks

    # 并行思考所有冲突
    think_results = await asyncio.gather(
        *[_think_one_conflict(c, chunks) for c, chunks in retrieval_results]
    )

    # ---- Phase 3：串行收集结果 + 发布事件 ----
    evidence_set: list[dict[str, Any]] = []
    for result, confidence, conflict, evidence_chunks in think_results:
        cid = conflict.get("id", "c0")
        worst_confidence = _worst_confidence(worst_confidence, confidence)
        assessments = result.get("evidence_assessments", [])
        es = {
            "conflict_id": result.get("conflict_id", cid),
            "assessments": assessments,
        }
        evidence_set.append(es)
        # 发布 evidence.attached 事件（逐条证据）
        for a in assessments:
            await bus.publish(
                make_event(
                    "evidence.attached",
                    state.meeting_id,
                    {
                        "meeting_id": state.meeting_id,
                        "conflict_id": es["conflict_id"],
                        "quote": a.get("quote", ""),
                        "source": a.get("source", ""),
                        "supports": a.get("supports", "neutral"),
                    },
                )
            )
    state.evidence_set = evidence_set
    # 第2层：锁定 evidence_check 结论
    state.conclusion_chain.lock("evidence_check", {"evidence_set": evidence_set})
    # 第5层：记录置信度（取最差值）
    state.confidence_flags["evidence_check"] = worst_confidence
    # 改造三：让待发言的借调 agent 在证据对照阶段也发言一次（兜底）
    await _let_borrowed_agents_speak(state, Stage.EVIDENCE_CHECK)
    nxt = _next_stage(Stage.EVIDENCE_CHECK, state.flow_plan)
    state.stage = nxt or Stage.PRODUCE
    return state


async def arbitrate_node(state: MeetingState) -> MeetingState:
    """Arbitrate 阶段：仲裁者裁决，形成结论"""
    # 设置 trace 上下文
    set_current_trace(state.llm_trace)
    compute = get_compute()
    # 带一致性自检的 LLM 调用
    async def call_fn(anchor: str) -> dict[str, Any]:
        req = build_arbitrate_prompt(state.evidence_set, anchor=anchor)
        resp = await compute.think(req)
        return resp.result

    result, confidence = await _run_with_consistency(state, "arbitrate", call_fn)
    state.decision_record = {
        "decisions": result.get("decisions", []),
        "adopted_claims": result.get("adopted_claims", []),
    }
    # [CONVERGENCE] 将松散决策压缩为紧凑 action brief，注入 decision_record
    state.decision_record["action_brief"] = _compress_decisions_to_brief(
        state.decision_record, state.claims, state.conflicts, state.evidence_set
    )
    # 第2层：锁定 arbitrate 结论
    state.conclusion_chain.lock("arbitrate", state.decision_record)
    # 第5层：记录置信度
    state.confidence_flags["arbitrate"] = confidence
    content = _format_arbitrate_as_text(
        state.decision_record,
        state.claims,
        state.conflicts,
    )
    await _emit_agent_spoke(state, Role.MODERATOR, Stage.ARBITRATE, content)
    _record_drift(state, Role.MODERATOR, Stage.ARBITRATE, content)
    nxt = _next_stage(Stage.ARBITRATE, state.flow_plan)
    state.stage = nxt or Stage.PRODUCE
    return state


def _compress_decisions_to_brief(
    decision_record: dict,
    claims: list[dict],
    conflicts: list[dict],
    evidence_set: list[dict],
) -> dict[str, Any]:
    """将松散的仲裁结果压缩为紧凑的 action brief。

    纯确定性提取（不调 LLM），确保低延迟零额外成本。
    产出结构:
    - core_decisions: 最重要的 3-5 项决策（一行一条）
    - evidence_backing: 支撑核心决策的证据方向
    - rejected_alternatives: 被否决的方向及原因
    - action_items: 从决策推导的具体行动项
    """
    decisions = decision_record.get("decisions", [])
    adopted = decision_record.get("adopted_claims", [])

    # 核心决策：取前 5 条（LLM 已按重要性排序）
    core_decisions = []
    for d in decisions[:5]:
        if isinstance(d, dict):
            text = d.get("summary", d.get("verdict", str(d)))
        else:
            text = str(d)
        if text:
            core_decisions.append(text[:120])

    # 证据方向统计
    support_counts = {"supports": 0, "refutes": 0, "neutral": 0}
    for es in evidence_set:
        for a in es.get("assessments", []):
            direction = a.get("supports", "neutral")
            if direction in support_counts:
                support_counts[direction] += 1
    evidence_backing = (
        f"{support_counts['supports']} 条证据支持, "
        f"{support_counts['refutes']} 条反驳, "
        f"{support_counts['neutral']} 条中性"
    ) if evidence_set else "无证据数据"

    # 被否决的方向：从 conflicts 中找出未被采纳的
    rejected = []
    adopted_ids = set()
    for a in adopted:
        if isinstance(a, dict):
            adopted_ids.add(a.get("id", a.get("claim_id", "")))
        elif isinstance(a, str):
            adopted_ids.add(a)
    for c in conflicts[:5]:
        c_id = c.get("id", "")
        # 如果冲突的某一方未被采纳，记录为 rejected
        for side in c.get("sides", []):
            if isinstance(side, dict) and side.get("claim_id", "") not in adopted_ids:
                reason = side.get("rejection_reason", "证据不足或与共识冲突")
                rejected.append(f"{side.get('text', '?')[:80]} — {reason[:60]}")

    # 行动项：从 adopted_claims 提取可执行的下一步
    action_items = []
    for a in adopted[:5]:
        if isinstance(a, dict):
            next_step = a.get("next_step", a.get("action", ""))
            if next_step:
                action_items.append(next_step[:100])
            else:
                text = a.get("text", a.get("claim", ""))
                if text:
                    action_items.append(f"落实: {text[:80]}")

    return {
        "core_decisions": core_decisions,
        "evidence_backing": evidence_backing,
        "rejected_alternatives": rejected[:3],
        "action_items": action_items,
    }


def _synthesize_evidence_for_produce(state: MeetingState) -> dict[str, Any]:
    """将 evidence_set + decision_record 综合为结构化数据规格，
    供代码生成类 deliverable (code_analysis / data_science) 使用。

    返回空 dict 表示无可用证据（非代码类产出不受影响）。
    """
    if not state.evidence_set:
        return {}

    evidence_sources: list[str] = []
    evidence_quotes: list[dict] = []
    for es in state.evidence_set:
        for a in es.get("assessments", []):
            source = a.get("source", "")
            quote = a.get("quote", "")
            if source and source not in evidence_sources:
                evidence_sources.append(source)
            if quote:
                evidence_quotes.append({
                    "quote": quote[:200],
                    "source": source,
                    "supports": a.get("supports", "neutral"),
                    "conflict_id": es.get("conflict_id", ""),
                })

    decisions = (state.decision_record or {}).get("decisions", [])
    adopted = (state.decision_record or {}).get("adopted_claims", [])

    return {
        "available_data_sources": evidence_sources[:10],
        "evidence_count": len(evidence_quotes),
        "evidence_samples": evidence_quotes[:15],
        "decisions_count": len(decisions),
        "adopted_claims_count": len(adopted),
    }


async def produce_node(state: MeetingState) -> MeetingState:
    """Produce 阶段：根据 deliverable_type 切换模板，生成对应交付物

    [AUDIT-FIX P0-2] 修复：部署失败时确保 artifact 仍被保存（不返回 null）。
    节点级异常兜底由 Runner.run() 的 try/except 统一处理（P0-4）。
    """
    # 设置 trace 上下文
    set_current_trace(state.llm_trace)
    compute = get_compute()
    from app.observability.log_bus import log_bus as _lb
    # 根据产出类型选择模板
    from app.agents.prompts import get_produce_template
    template = get_produce_template(state.deliverable_type)

    # [DATA-BRIDGE] 综合证据数据，供代码生成类产出使用
    evidence_summary = _synthesize_evidence_for_produce(state)
    if evidence_summary:
        _lb.info(
            f"produce: 证据桥接激活 — {evidence_summary['evidence_count']} 条证据, "
            f"{len(evidence_summary['available_data_sources'])} 个数据来源",
            logger="orchestrator.nodes.produce",
        )

    # 带一致性自检的 LLM 调用
    async def call_fn(anchor: str) -> dict[str, Any]:
        req = build_produce_prompt(
            state.decision_record or {},
            anchor=anchor,
            template=template,
            deliverable_type=state.deliverable_type,
            evidence_summary=evidence_summary or None,
        )
        resp = await compute.think(req)
        return resp.result

    result, confidence = await _run_with_consistency(state, "produce", call_fn)
    _lb.info("produce: LLM 调用+一致性检查完成", logger="orchestrator.nodes.produce",
             extra={"confidence": confidence, "deliverable_type": state.deliverable_type,
                    "has_prd": bool(result.get("prd")), "openapi_len": len(result.get("openapi", ""))})
    # 构建 artifact
    prd = result.get("prd", {})
    openapi = result.get("openapi", "")
    state.artifact = {
        "meeting_id": state.meeting_id,
        "deliverable_type": state.deliverable_type,
        "prd": prd,
        "openapi": openapi,
    }

    # 代码执行类产出：调用沙箱执行代码
    if state.deliverable_type in ("code_analysis", "data_science"):
        code_data = result.get("code_analysis") or {}
        code = code_data.get("code", "")
        if code:
            from app.sandbox import run_python, SANDBOX_IMAGE_DATASCIENCE
            from app.orchestrator.refine_loop import refine_python_code, _summarize_task
            ws_env = os.environ.get("CONCLAVE_WORKSPACE_DIR", "")
            # [CON-24 修复] 用 config.settings.workspace_root 作为持久化工作区根
            from app.config import settings
            ws_root = Path(settings.workspace_root) / state.meeting_id
            ws_root.mkdir(parents=True, exist_ok=True)
            try:
                # code_analysis 模板更可能需要数据分析库，使用数据科学镜像
                # 根据代码内容判断网络级别
                net_level = _detect_network_level(code)
                async def _run(code, level=net_level):
                    r = await run_python(code, ws_root, timeout=30,
                                         image=SANDBOX_IMAGE_DATASCIENCE,
                                         network_level=level)
                    return r.to_dict()
                task_summary = _summarize_task("code_analysis", result)
                refined = await refine_python_code(
                    code, task_summary, _run, max_rounds=5,
                    meeting_id=state.meeting_id, stage="produce",
                    detected_level=net_level,
                )
                # 网络授权获批后用新级别重试
                if refined.get("need_retry_with_level"):
                    new_level = refined["need_retry_with_level"]
                    _lb.info(f"produce: 网络授权获批 level={new_level}，重新执行代码",
                             logger="orchestrator.nodes.produce")
                    async def _run_approved(code):
                        r = await run_python(code, ws_root, timeout=30,
                                             image=SANDBOX_IMAGE_DATASCIENCE,
                                             network_level=new_level)
                        return r.to_dict()
                    refined = await refine_python_code(
                        refined["code"], task_summary, _run_approved, max_rounds=3,
                        meeting_id=state.meeting_id, stage="produce",
                        detected_level=new_level,
                    )
                code_data["code"] = refined["code"]
                state.artifact["code_analysis"] = code_data
                state.artifact["execution"] = refined["execution"]
                state.artifact["refine_info"] = {
                    "rounds_used": refined["rounds_used"],
                    "success": refined["success"],
                }
                if refined.get("net_auth"):
                    state.artifact["net_auth"] = refined["net_auth"]
            except Exception as e:
                state.artifact["code_analysis"] = code_data
                state.artifact["execution"] = {"error": str(e), "exit_code": -1}
        else:
            state.artifact["code_analysis"] = code_data

    elif state.deliverable_type == "tested_system":
        ts_data = result.get("tested_system") or {}
        main_code = ts_data.get("main_code", "")
        test_code = ts_data.get("test_code", "")
        if test_code:
            from app.sandbox import run_command, SANDBOX_IMAGE_DATASCIENCE
            from app.orchestrator.refine_loop import refine_python_code, _summarize_task
            # [CON-24 修复] 用持久化工作区
            from app.config import settings
            ws_root = Path(settings.workspace_root) / state.meeting_id
            ws_root.mkdir(parents=True, exist_ok=True)
            ws_root.mkdir(parents=True, exist_ok=True)
            try:
                # 把代码写入工作区
                test_file = ws_root / "test_generated.py"
                test_file.write_text(test_code, encoding="utf-8")
                main_file = ws_root / "main_generated.py"
                if main_code:
                    main_file.write_text(main_code, encoding="utf-8")
                # tested_system 模板更可能需要数据分析库，使用数据科学镜像
                net_level = _detect_network_level(test_code)
                async def _run_tests(code, level=net_level):
                    test_file.write_text(code, encoding="utf-8")
                    r = await run_command(
                        "python -m pytest test_generated.py -v",
                        ws_root, timeout=30, image=SANDBOX_IMAGE_DATASCIENCE,
                        network_level=level,
                    )
                    return r.to_dict()
                task_summary = _summarize_task("tested_system", result)
                refined = await refine_python_code(
                    test_code, task_summary, _run_tests, max_rounds=5,
                    meeting_id=state.meeting_id, stage="produce",
                    detected_level=net_level,
                )
                # 网络授权获批后用新级别重试
                if refined.get("need_retry_with_level"):
                    new_level = refined["need_retry_with_level"]
                    _lb.info(f"produce: 网络授权获批 level={new_level}，重新执行测试",
                             logger="orchestrator.nodes.produce")
                    async def _run_tests_approved(code):
                        test_file.write_text(code, encoding="utf-8")
                        r = await run_command(
                            "python -m pytest test_generated.py -v",
                            ws_root, timeout=30, image=SANDBOX_IMAGE_DATASCIENCE,
                            network_level=new_level,
                        )
                        return r.to_dict()
                    refined = await refine_python_code(
                        refined["code"], task_summary, _run_tests_approved, max_rounds=3,
                        meeting_id=state.meeting_id, stage="produce",
                        detected_level=new_level,
                    )
                ts_data["test_code"] = refined["code"]
                state.artifact["tested_system"] = ts_data
                state.artifact["execution"] = refined["execution"]
                state.artifact["refine_info"] = {
                    "rounds_used": refined["rounds_used"],
                    "success": refined["success"],
                }
                if refined.get("net_auth"):
                    state.artifact["net_auth"] = refined["net_auth"]
            except Exception as e:
                state.artifact["tested_system"] = ts_data
                state.artifact["execution"] = {"error": str(e), "exit_code": -1}
        else:
            state.artifact["tested_system"] = ts_data

    elif state.deliverable_type == "deployable_service":
        ds_data = result.get("deployable_service") or {}
        app_code = ds_data.get("app_code", "")
        requirements_txt = ds_data.get("requirements_txt", "")
        dockerfile_content = ds_data.get("dockerfile", "")
        docker_compose_content = ds_data.get("docker_compose", "")
        readme_content = ds_data.get("readme", "")
        credentials = ds_data.get("credentials") or {}
        service_port = ds_data.get("port", 8000)
        if app_code:
            from app.config import settings
            ws_root = Path(settings.workspace_root) / state.meeting_id
            ws_root.mkdir(parents=True, exist_ok=True)

            # === 代码 Review + BugFix 循环 ===
            # [AUDIT-FIX P0-3] 修复：增加连续修复失败计数器，超过阈值提前退出循环
            review_rounds = 0
            max_review_rounds = 3
            max_consecutive_fix_failures = 3  # 连续修复失败上限
            consecutive_fix_failures = 0
            review_passed = False
            review_summary = ""
            code_files = {
                "app.py": app_code,
                "requirements.txt": requirements_txt,
                "Dockerfile": dockerfile_content,
                "docker-compose.yml": docker_compose_content,
            }

            for review_rounds in range(1, max_review_rounds + 1):
                _lb.info(f"produce: 代码审查第{review_rounds}轮", logger="orchestrator.nodes.produce")
                # 调用LLM做代码审查
                from app.agents.prompts import CODE_REVIEW_PROMPT, CODE_FIX_PROMPT
                from app.agents.bug_patterns import format_bug_patterns_for_prompt
                bug_patterns = format_bug_patterns_for_prompt()

                review_prompt = CODE_REVIEW_PROMPT.format(
                    bug_patterns=bug_patterns,
                    app_code=code_files["app.py"],
                    requirements_txt=code_files["requirements.txt"],
                    dockerfile=code_files["Dockerfile"],
                    docker_compose=code_files["docker-compose.yml"],
                )
                review_req = ThinkRequest(
                    agent_role=Role.ENGINEER.value,
                    stage="review",
                    prompt=review_prompt,
                    schema_hint="code_review",
                )
                # 为review阶段注入Skills（deliverable_quality, code_conventions等）
                try:
                    from app.agents.skills import format_skills_for_prompt
                    skills_text = format_skills_for_prompt(stage="review", deliverable_type="deployable_service", role=Role.ENGINEER.value)
                    if skills_text:
                        review_req.prompt = review_req.prompt + "\n\n" + skills_text
                except Exception:
                    pass
                review_resp = await compute.think(review_req)
                review_result = review_resp.result if hasattr(review_resp, 'result') else {}
                if isinstance(review_result, dict):
                    issues = review_result.get("issues", [])
                    review_summary = review_result.get("summary", "")
                    critical_high = [i for i in issues if i.get("severity") in ("critical", "high")]
                    # [AUDIT-FIX P2] 审查一致性：综合 passed 字段和 critical/high 问题判断
                    # 避免 LLM 输出 passed=true 但 issues 中含 critical 的矛盾
                    passed_from_llm = review_result.get("passed", False)
                    if not critical_high:
                        # [AUDIT-FIX P2] 无 critical/high 问题即通过，并记录 LLM passed 字段是否一致
                        review_passed = True
                        if not passed_from_llm:
                            _lb.warning("produce: 审查 passed=false 但无 critical/high 问题，按问题判定为通过",
                                        logger="orchestrator.nodes.produce")
                        _lb.info(f"produce: 代码审查通过（第{review_rounds}轮，{len(issues)}个低/中级别问题）",
                                 logger="orchestrator.nodes.produce")
                        break

                    # 有critical/high问题，修复
                    _lb.info(f"produce: 发现{len(critical_high)}个严重问题，开始修复",
                             logger="orchestrator.nodes.produce",
                             extra={"issues": [i.get("description", "")[:100] for i in critical_high]})
                    for issue in critical_high:
                        file_to_fix = issue.get("file", "app.py")
                        file_key_map = {"app.py": "app.py", "requirements.txt": "requirements.txt",
                                        "Dockerfile": "Dockerfile", "docker-compose.yml": "docker-compose.yml"}
                        fkey = file_key_map.get(file_to_fix, "app.py")
                        original = code_files[fkey]
                        issues_text = f"- [{issue.get('severity','high')}] {issue.get('description','')}\n  修复建议: {issue.get('fix','')}"
                        fix_prompt = CODE_FIX_PROMPT.format(
                            original_code=original,
                            issues_text=issues_text,
                            bug_patterns=bug_patterns,
                            file_to_fix=fkey,
                        )
                        fix_req = ThinkRequest(
                            agent_role=Role.ENGINEER.value,
                            stage="bugfix",
                            prompt=fix_prompt,
                            schema_hint="bugfix",  # [AUDIT-FIX P1-2] 修复：补全 schema_hint 确保 trace 记录正确 stage
                        )
                        # 为bugfix阶段注入Skills（code_conventions等）
                        try:
                            from app.agents.skills import format_skills_for_prompt
                            skills_text = format_skills_for_prompt(stage="bugfix", deliverable_type="deployable_service", role=Role.ENGINEER.value)
                            if skills_text:
                                fix_req.prompt = fix_req.prompt + "\n\n" + skills_text
                        except Exception:
                            pass
                        fix_resp = await compute.think(fix_req)
                        # 正确解析LLM返回的JSON：可能是 {"fixed_code": "..."} 格式，也可能直接是代码字符串
                        fixed_code = ""
                        if isinstance(fix_resp.result, dict):
                            fixed_code = str(fix_resp.result.get("fixed_code", "") or fix_resp.result.get("code", "") or "")
                            # 如果dict中没有fixed_code字段，尝试取第一个字符串值
                            if not fixed_code:
                                for v in fix_resp.result.values():
                                    if isinstance(v, str) and len(v) > 20:
                                        fixed_code = v
                                        break
                        elif isinstance(fix_resp.result, str):
                            fixed_code = fix_resp.result
                        else:
                            fixed_code = str(fix_resp.result)
                        # 清理可能的markdown代码块标记
                        fixed_code = fixed_code.strip()
                        if fixed_code.startswith("```"):
                            lines = fixed_code.split("\n")
                            # 去掉第一行```language和最后一行```
                            lines = lines[1:]
                            while lines and lines[-1].strip().startswith("```"):
                                lines = lines[:-1]
                            fixed_code = "\n".join(lines)
                        # [AUDIT-FIX P0-1] 修复：用 ast.parse 校验 Python 代码有效性，
                        # 替代原来粗暴的 startswith("{") 检查（会误拒以 "{" 开头的合法代码）
                        # [AUDIT-FIX P0-3] 修复：增加连续失败计数，超过阈值时退出循环
                        _fix_ok = False
                        if not fixed_code:
                            _lb.warning(f"produce: 修复 {fkey} 返回空代码，保留原版本",
                                        logger="orchestrator.nodes.produce")
                        elif fkey.endswith(".py"):
                            import ast as _ast
                            try:
                                _ast.parse(fixed_code)
                                code_files[fkey] = fixed_code
                                _fix_ok = True
                            except SyntaxError as _se:
                                _lb.warning(f"produce: 修复 {fkey} 代码有语法错误 ({_se})，保留原版本",
                                            logger="orchestrator.nodes.produce")
                        else:
                            # 非 .py 文件（requirements.txt, Dockerfile 等）：非空即接受
                            code_files[fkey] = fixed_code
                            _fix_ok = True
                        # P0-3: 连续失败计数
                        if _fix_ok:
                            consecutive_fix_failures = 0
                        else:
                            consecutive_fix_failures += 1
                            if consecutive_fix_failures >= max_consecutive_fix_failures:
                                _lb.warning(
                                    f"produce: 连续 {consecutive_fix_failures} 次修复失败，"
                                    f"跳过剩余问题并在本轮终止审查循环",
                                    logger="orchestrator.nodes.produce")
                                review_passed = False
                                break
                else:
                    review_passed = True  # 审查返回非JSON，跳过
                    break

            # 更新代码
            app_code = code_files["app.py"]
            requirements_txt = code_files["requirements.txt"]
            dockerfile_content = code_files["Dockerfile"]
            docker_compose_content = code_files["docker-compose.yml"]

            # 写入所有部署文件到工作区
            (ws_root / "app.py").write_text(app_code, encoding="utf-8")
            if requirements_txt:
                (ws_root / "requirements.txt").write_text(requirements_txt, encoding="utf-8")
            if dockerfile_content:
                (ws_root / "Dockerfile").write_text(dockerfile_content, encoding="utf-8")
            if docker_compose_content:
                (ws_root / "docker-compose.yml").write_text(docker_compose_content, encoding="utf-8")
            # 写入 README
            if readme_content:
                (ws_root / "README.md").write_text(readme_content, encoding="utf-8")
            else:
                default_readme = f"""# {ds_data.get('title', 'Deployable Service')}

{ds_data.get('description', '')}

## 快速开始
```bash
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port {service_port}
```
服务端口: {service_port}
"""
                (ws_root / "README.md").write_text(default_readme, encoding="utf-8")

            # 更新ds_data中的代码为修复后的版本
            ds_data["app_code"] = app_code
            ds_data["requirements_txt"] = requirements_txt
            ds_data["dockerfile"] = dockerfile_content
            ds_data["docker_compose"] = docker_compose_content
            state.artifact["deployable_service"] = ds_data
            state.artifact["deployment_dir"] = str(ws_root)
            state.artifact["review"] = {
                "rounds": review_rounds,
                "passed": review_passed,
                "summary": review_summary,
            }

            # === 沙箱自动部署 ===
            deployment_info = {}
            try:
                from app.sandbox import deploy_service
                _lb.info("produce: 开始沙箱部署服务...", logger="orchestrator.nodes.produce")

                # 确保有/health端点 - 如果app_code中没有，自动注入
                if "/health" not in app_code and '"/health"' not in app_code and "'/health'" not in app_code:
                    health_code = """

@app.get("/health")
def health():
    return {"status": "ok"}
"""
                    # 注入到 if __name__ == "__main__" 之前
                    if 'if __name__' in app_code:
                        app_code = app_code.replace('if __name__', health_code + '\nif __name__')
                        (ws_root / "app.py").write_text(app_code, encoding="utf-8")

                deploy_result = await deploy_service(
                    meeting_id=state.meeting_id,
                    workspace_root=settings.workspace_root,
                    container_port=service_port,
                    health_path="/health",
                    wait_seconds=45,
                    credentials=credentials if credentials else None,
                    env_vars={"SECRET_KEY": "dev-conclave-secret-change-me"},
                )
                deployment_info = deploy_result.to_dict()
                _lb.info(
                    f"produce: 服务部署{'成功' if deploy_result.ok else '失败'}",
                    logger="orchestrator.nodes.produce",
                    extra={"access_url": deploy_result.access_url, "ok": deploy_result.ok},
                )

                # 发布服务部署事件
                await bus.publish(make_event(
                    "service.deployed" if deploy_result.ok else "service.deploy_failed",
                    state.meeting_id,
                    deployment_info,
                ))
            except Exception as deploy_err:
                _lb.error(f"produce: 服务部署异常: {deploy_err}", logger="orchestrator.nodes.produce")
                deployment_info = {"ok": False, "error": str(deploy_err)}

            state.artifact["deployment"] = deployment_info
            state.artifact["execution"] = {
                "exit_code": 0 if review_passed else 1,
                "stdout": (
                    f"代码审查: {review_rounds}轮, {'通过' if review_passed else '存在未修复问题'}\n"
                    f"部署文件: app.py / requirements.txt / Dockerfile / docker-compose.yml / README.md\n"
                    f"服务部署: {'成功 ✅ ' + deployment_info.get('access_url', '') if deployment_info.get('ok') else '失败: ' + deployment_info.get('error', '未知错误')}"
                ),
                "stderr": deployment_info.get("logs", "") if not deployment_info.get("ok") else "",
                "sandboxed": True,
                "files": ["app.py", "requirements.txt", "Dockerfile", "docker-compose.yml", "README.md"],
            }
        else:
            state.artifact["deployable_service"] = ds_data
    else:
        # 其他类型直接存入 artifact
        for key in ["design_doc", "comprehensive", "research_report", "business_report"]:
            if key in result:
                state.artifact[key] = result[key]

    # 附件扫描：所有代码/服务类产出都扫描工作区收集产出文件
    if state.deliverable_type in ("code_analysis", "tested_system", "deployable_service"):
        # [CON-24 修复] 用持久化工作区
        from app.config import settings
        ws_root = Path(settings.workspace_root) / state.meeting_id
        attachments = _scan_artifacts(ws_root, state.meeting_id)
        if attachments:
            state.artifact["attachments"] = attachments
            _lb.info("produce: 扫描到 %d 个附件文件", len(attachments),
                     logger="orchestrator.nodes.produce",
                     extra={"attachment_files": [a["filename"] for a in attachments]})

    # 第2层：锁定 produce 结论
    state.conclusion_chain.lock("produce", state.artifact)
    # 第5层：记录置信度
    state.confidence_flags["produce"] = confidence
    _lb.info("produce: artifact 已构造, 锁定结论完成", logger="orchestrator.nodes.produce",
             extra={"prd_title": prd.get("title", "?"), "openapi_len": len(openapi),
                    "deliverable_type": state.deliverable_type})
    # 发布 artifact.generated 事件
    await bus.publish(
        make_event(
            "artifact.generated",
            state.meeting_id,
            {
                "meeting_id": state.meeting_id,
                "deliverable_type": state.deliverable_type,
                "prd": prd,
                "openapi": openapi,
            },
        )
    )
    _lb.info("produce: artifact.generated 事件已发布", logger="orchestrator.nodes.produce")
    # 产物阶段也做一次漂移检查（针对产出文本）
    artifact_text = json.dumps(state.artifact, ensure_ascii=False, default=str)
    _record_drift(state, Role.MODERATOR, Stage.PRODUCE, artifact_text)
    _lb.info("produce: 漂移检查完成", logger="orchestrator.nodes.produce")
    # 终态
    state.stage = Stage.PRODUCE
    state.status = MeetingStatus.DONE
    _lb.info("produce: 状态已设为 DONE", logger="orchestrator.nodes.produce")

    # LLM 降级检测：如果有阶段使用了 StubLLM 兜底，发 warning 事件
    fallback_stages = [s for s, flag in state.confidence_flags.items() if flag == "fallback"]
    if fallback_stages:
        await bus.publish(make_event(
            "meeting.fallback_warning",
            state.meeting_id,
            {
                "fallback_stages": fallback_stages,
                "message": f"以下阶段使用了降级数据（非真实 LLM 输出）：{', '.join(fallback_stages)}。产出物可能不可靠，请谨慎参考。",
                "severity": "warning",
            },
        ))
        _lb.warning(
            f"会议完成但有 {len(fallback_stages)} 个阶段降级：{fallback_stages}",
            logger="orchestrator.nodes.produce",
        )
    # 迭代二：会议结束后触发记忆提取（失败不影响主流程）
    from app.memory.profile import trigger_extraction
    trigger_extraction(state)
    _lb.info("produce: 记忆提取完成, 准备返回", logger="orchestrator.nodes.produce")
    # [FEEDBACK] Agent 反馈闭环：评估每个 Agent 的判断质量，写回画像供迭代
    try:
        from app.agents.feedback import evaluate_agents
        evaluations = evaluate_agents(state)
        if evaluations:
            _lb.info(
                f"produce: Agent 评估完成 — {len(evaluations)} 个角色, "
                f"top={max(evaluations.items(), key=lambda x: x[1]['overall_score'])[0]}",
                logger="orchestrator.nodes.produce",
            )
    except Exception as fb_err:
        _lb.warning(f"produce: Agent 评估失败（不影响主流程）: {fb_err}",
                     logger="orchestrator.nodes.produce")
    return state


# 节点注册表：阶段 -> 节点函数
NODES: dict[Stage, Node] = {
    Stage.CLARIFY: clarify_node,
    Stage.INTRA_TEAM: intra_team_node,
    Stage.CROSS_TEAM: cross_team_node,
    Stage.EVIDENCE_CHECK: evidence_check_node,
    Stage.ARBITRATE: arbitrate_node,
    Stage.PRODUCE: produce_node,
}


# ---------- 元认知路由节点：动态决定下一阶段 ----------

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

    # 检查循环上限
    max_loops = _MAX_LOOP_COUNT.get(current, 1)
    loop_count = _get_loop_count(state, current)
    if loop_count >= max_loops and Stage.PRODUCE in valid_next:
        return Stage.PRODUCE

    # 轻量辩论：intra_team 后直接 produce
    if state.debate_depth == "light" and current == Stage.INTRA_TEAM:
        return Stage.PRODUCE

    # 标准辩论：无冲突时跳过 evidence_check
    if state.debate_depth == "standard" and current == Stage.CROSS_TEAM:
        if not state.conflicts:
            return Stage.ARBITRATE if Stage.ARBITRATE in valid_next else Stage.PRODUCE

    # 调用 LLM 做元认知决策
    try:
        compute = get_compute()
        summary = _build_state_summary(state)
        valid_stages_str = ", ".join(s.value for s in valid_next)

        prompt = (
            f"你是会议流程的元认知控制器。根据当前会议状态，决定下一个最合适的阶段。\n\n"
            f"## 当前状态\n{summary}\n\n"
            f"## 可选下一阶段\n{valid_stages_str}\n\n"
            f"## 决策规则\n"
            f"- 如果核心问题已解决且裁决充分，选择 produce\n"
            f"- 如果仍有未解决的冲突，选择 evidence_check 或 arbitrate\n"
            f"- 如果论点不够充分，可以重复当前阶段（intra_team/cross_team）\n"
            f"- 如果证据对照发现新冲突或证据不足，可以回退到 cross_team 重新辩论\n"
            f"- 如果裁决结论不够收敛，可以回退到 evidence_check 补充证据\n"
            f"- 回退有成本（额外 token + 延迟），仅在必要时使用\n"
            f"- 辩论深度为 {state.debate_depth}，轻量级应尽快结束\n\n"
            f"只输出一个阶段名称（小写英文），不要任何其他内容。"
        )

        from app.agents.compute import ThinkRequest
        resp = await compute.think(ThinkRequest(
            agent_role="meta_cognition",
            stage="meta",
            prompt=prompt,
            schema_hint="meta_next_stage",
            temperature=0,
            seed=42,
        ))

        next_stage_str = (resp.result.get("next_stage", "") if isinstance(resp.result, dict)
                          else str(resp.result)).strip().lower()

        # 验证输出
        for stage in Stage:
            if stage.value == next_stage_str and stage in valid_next:
                return stage

        # 回退：按固定顺序前进
        from app.orchestrator.state import next_stage as _ns
        fallback = _ns(current, state.flow_plan)
        if fallback and fallback in valid_next:
            return fallback

    except Exception:
        pass

    # 最终回退
    from app.orchestrator.state import next_stage as _ns
    return _ns(current, state.flow_plan) or Stage.PRODUCE
