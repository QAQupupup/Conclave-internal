# 状态机 + 控制信号处理
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from app.models import MeetingState, MeetingStatus, Stage


# ---------- 控制信号 ----------

VALID_SIGNALS = {"pause", "resume", "abort", "inject", "loan", "reject_user", "approve_borrow", "reject_borrow", "freeze_borrow"}


class ControlError(Exception):
    """控制信号处理异常"""


# ---------- 信号处理器（命令模式）----------
# 每个信号对应一个 handler: (state, payload) -> state
# 新增信号只需实现 handler 并注册到 _SIGNAL_HANDLERS，无需改 apply_signal（开闭原则）

def _handle_pause(state: MeetingState, payload: dict[str, Any]) -> MeetingState:
    """pause: 保存快照，标记 paused"""
    if state.status != MeetingStatus.RUNNING:
        raise ControlError(f"当前状态 {state.status} 不可暂停")
    state.paused_snapshot = state.snapshot()
    state.status = MeetingStatus.PAUSED
    return state


def _handle_resume(state: MeetingState, payload: dict[str, Any]) -> MeetingState:
    """resume: 恢复快照，标记 running"""
    if state.status != MeetingStatus.PAUSED:
        raise ControlError(f"当前状态 {state.status} 不可恢复")
    snapshot = state.paused_snapshot
    if snapshot:
        restored = MeetingState(**snapshot)
        restored.status = MeetingStatus.RUNNING
        restored.paused_snapshot = None
        return restored
    state.status = MeetingStatus.RUNNING
    return state


def _handle_abort(state: MeetingState, payload: dict[str, Any]) -> MeetingState:
    """abort: 标记 aborted，进入归档"""
    state.status = MeetingStatus.ABORTED
    return state


def _handle_inject(state: MeetingState, payload: dict[str, Any]) -> MeetingState:
    """inject: 追加注入消息，下一轮可见"""
    import uuid
    msg = payload.get("message", payload.get("content", ""))
    if msg:
        msg_id = f"inject-{uuid.uuid4().hex[:8]}"
        state.injected_messages.append(
            {
                "signal": "inject",
                "message_id": msg_id,
                "content": msg,
                "at_stage": state.stage.value,
                "rejected": False,
            }
        )
    return state


def _handle_loan(state: MeetingState, payload: dict[str, Any]) -> MeetingState:
    """loan: 借调三问裁决（基于会议宪章防重复借调）"""
    target_role = str(payload.get("target_role", "")).strip()
    charter = state.charter
    if charter is None or not target_role:
        # 宪章尚未建立或目标角色缺失：暂存请求，defer 等待 clarify 后再裁决
        state.injected_messages.append(
            {
                "signal": "loan",
                "request": payload,
                "at_stage": state.stage.value,
                "verdict": "defer",
                "reason": "会议宪章尚未建立或未指定 target_role，暂缓裁决",
            }
        )
        return state

    # 1. 防重复借调：已借调过该角色则 reject
    if charter.is_already_borrowed(target_role):
        verdict = "reject"
        reason = f"角色 {target_role} 已借调过，拒绝重复借调"
    # 2. 借调数量上限：单次会议最多 2 个借调 agent
    elif len(state.borrowed_agents) >= 2:
        verdict = "reject"
        reason = f"借调数量已达上限（2），拒绝借调 {target_role}"
    else:
        # 3. 登记借调：register_borrow 记入 borrow_history，临时批准
        verdict = "approve_temporary"
        reason = f"角色 {target_role} 借调批准（临时加入，待发言）"
        charter.register_borrow(target_role, verdict)
        # 4. 追加到 borrowed_agents，标记为待发言（不立即加入 frozen scope）
        state.borrowed_agents.append(
            {
                "role": target_role,
                "verdict": "approve_temporary",
                "spoken": False,
                "request": payload,
            }
        )
    state.injected_messages.append(
        {
            "signal": "loan",
            "request": payload,
            "at_stage": state.stage.value,
            "verdict": verdict,
            "reason": reason,
        }
    )
    return state


def _handle_reject_user(state: MeetingState, payload: dict[str, Any]) -> MeetingState:
    """reject_user: Agent 对用户注入消息提出证据驱动的拒绝投票

    约束：
    - 每个 Agent 必须提供证据（evidence_refs）才能拒绝
    - 至少 2 个 Agent 投票拒绝后，注入消息被标记为 rejected
    - 无证据的拒绝投票被忽略
    """
    target_message_id = str(payload.get("message_id", "")).strip()
    agent_role = str(payload.get("agent_role", "")).strip()
    evidence_refs = payload.get("evidence_refs", [])
    reason = str(payload.get("reason", "")).strip()

    if not target_message_id or not agent_role:
        return state

    # 证据约束：无证据的拒绝投票不记录
    if not evidence_refs or len(evidence_refs) == 0:
        state.injected_messages.append(
            {
                "signal": "reject_user",
                "message_id": target_message_id,
                "agent_role": agent_role,
                "verdict": "ignored",
                "reason": "拒绝投票缺少证据引用，已忽略",
                "at_stage": state.stage.value,
            }
        )
        return state

    # 初始化 user_rejections 字典
    if not hasattr(state, 'user_rejections') or state.user_rejections is None:
        state.user_rejections = {}

    if target_message_id not in state.user_rejections:
        state.user_rejections[target_message_id] = []

    # 防重复：同一 Agent 对同一消息只能投一次
    existing_roles = {r.get("agent_role") for r in state.user_rejections[target_message_id]}
    if agent_role in existing_roles:
        return state

    # 记录投票
    vote = {
        "agent_role": agent_role,
        "evidence_refs": evidence_refs,
        "reason": reason,
        "at_stage": state.stage.value,
    }
    state.user_rejections[target_message_id].append(vote)

    # 判断是否达到拒绝阈值（至少 2 个 Agent）
    rejection_count = len(state.user_rejections[target_message_id])
    is_rejected = rejection_count >= 2

    state.injected_messages.append(
        {
            "signal": "reject_user",
            "message_id": target_message_id,
            "agent_role": agent_role,
            "verdict": "rejected" if is_rejected else "voting",
            "reason": reason,
            "rejection_count": rejection_count,
            "at_stage": state.stage.value,
        }
    )

    # 如果达到阈值，标记对应注入消息为 rejected
    if is_rejected:
        for inj in state.injected_messages:
            if inj.get("message_id") == target_message_id:
                inj["rejected"] = True
                inj["rejection_reason"] = "；".join(
                    r.get("reason", "") for r in state.user_rejections[target_message_id]
                )
                break

    return state


def _handle_approve_borrow(state: MeetingState, payload: dict[str, Any]) -> MeetingState:
    """approve_borrow: 用户批准待审批的借调申请"""
    request_id = str(payload.get("request_id", "")).strip()
    pending = state.pending_borrow_request
    if pending is None:
        raise ControlError("没有待审批的借调申请")
    if request_id and pending.get("id") != request_id:
        raise ControlError(f"待审批申请 ID 不匹配: {request_id}")

    target_role = pending.get("target_role", "")
    # 检查宪章和重复借调
    charter = state.charter
    if charter is None:
        raise ControlError("会议宪章尚未建立，无法借调")
    if charter.is_already_borrowed(target_role):
        state.pending_borrow_request = None
        state.injected_messages.append({
            "signal": "approve_borrow",
            "request_id": pending.get("id"),
            "target_role": target_role,
            "verdict": "reject",
            "reason": f"角色 {target_role} 已借调过",
            "at_stage": state.stage.value,
        })
        return state
    if len(state.borrowed_agents) >= 2:
        state.pending_borrow_request = None
        state.injected_messages.append({
            "signal": "approve_borrow",
            "request_id": pending.get("id"),
            "target_role": target_role,
            "verdict": "reject",
            "reason": "借调数量已达上限（2）",
            "at_stage": state.stage.value,
        })
        return state

    # 批准借调
    charter.register_borrow(target_role, "approve_temporary")
    state.borrowed_agents.append({
        "role": target_role,
        "verdict": "approve_temporary",
        "spoken": False,
        "request": {
            "target_role": target_role,
            "goal": pending.get("goal", ""),
            "necessary": pending.get("necessary", ""),
            "no_loan_cost": pending.get("no_loan_cost", ""),
            "stance": payload.get("stance", ""),
        },
    })
    # 记录历史
    state.borrow_request_history.append({
        **pending,
        "verdict": "approved_by_user",
        "approved_at": datetime.now(timezone.utc).isoformat(),
    })
    state.pending_borrow_request = None
    state.injected_messages.append({
        "signal": "approve_borrow",
        "request_id": pending.get("id"),
        "target_role": target_role,
        "verdict": "approve_temporary",
        "reason": "用户批准借调",
        "at_stage": state.stage.value,
    })
    return state


def _handle_reject_borrow(state: MeetingState, payload: dict[str, Any]) -> MeetingState:
    """reject_borrow: 用户拒绝待审批的借调申请"""
    request_id = str(payload.get("request_id", "")).strip()
    pending = state.pending_borrow_request
    if pending is None:
        raise ControlError("没有待审批的借调申请")
    if request_id and pending.get("id") != request_id:
        raise ControlError(f"待审批申请 ID 不匹配: {request_id}")

    target_role = pending.get("target_role", "")
    reason = str(payload.get("reason", "用户拒绝借调")).strip()
    state.borrow_request_history.append({
        **pending,
        "verdict": "rejected_by_user",
        "rejected_at": datetime.now(timezone.utc).isoformat(),
        "reject_reason": reason,
    })
    state.pending_borrow_request = None
    state.injected_messages.append({
        "signal": "reject_borrow",
        "request_id": pending.get("id"),
        "target_role": target_role,
        "verdict": "reject",
        "reason": reason,
        "at_stage": state.stage.value,
    })
    return state


def _handle_freeze_borrow(state: MeetingState, payload: dict[str, Any]) -> MeetingState:
    """freeze_borrow: 冻结借调 - 用户决定从此不再允许借调"""
    state.borrow_frozen = True
    pending = state.pending_borrow_request
    if pending is not None:
        state.borrow_request_history.append({
            **pending,
            "verdict": "frozen_by_user",
            "frozen_at": datetime.now(timezone.utc).isoformat(),
        })
        state.pending_borrow_request = None
    state.injected_messages.append({
        "signal": "freeze_borrow",
        "frozen": True,
        "at_stage": state.stage.value,
        "pending_request_id": pending.get("id") if pending else None,
    })
    return state


# 信号 → 处理器 注册表（命令模式 + Registry）
_SIGNAL_HANDLERS: dict[str, Callable[[MeetingState, dict[str, Any]], MeetingState]] = {
    "pause": _handle_pause,
    "resume": _handle_resume,
    "abort": _handle_abort,
    "inject": _handle_inject,
    "loan": _handle_loan,
    "reject_user": _handle_reject_user,
    "approve_borrow": _handle_approve_borrow,
    "reject_borrow": _handle_reject_borrow,
    "freeze_borrow": _handle_freeze_borrow,
}


def apply_signal(state: MeetingState, signal: str, payload: dict[str, Any] | None = None) -> MeetingState:
    """处理控制信号，返回更新后的状态

    信号分派通过 _SIGNAL_HANDLERS 注册表完成（命令模式），
    新增信号只需实现 handler 并注册，无需改本函数（开闭原则）。
    """
    payload = payload or {}
    signal = signal.lower().strip()

    if signal not in VALID_SIGNALS:
        raise ControlError(f"未知控制信号: {signal}")

    handler = _SIGNAL_HANDLERS.get(signal)
    if handler is None:
        raise ControlError(f"信号 {signal} 已注册但无处理器")
    return handler(state, payload)


# ---------- 状态机阶段流转 ----------

# 六阶段顺序
STAGE_ORDER: list[Stage] = [
    Stage.CLARIFY,
    Stage.INTRA_TEAM,
    Stage.CROSS_TEAM,
    Stage.EVIDENCE_CHECK,
    Stage.ARBITRATE,
    Stage.PRODUCE,
]

# 议题路由：各复杂度对应的阶段裁剪规则
# simple：跳过 cross_team + evidence_check + arbitrate，intra_team 后直接 produce
# standard：无条件跳过的阶段为空；evidence_check 由 cross_team_node 动态跳过（无冲突时）
# full：完整六阶段
_FLOW_SKIP_MAP: dict[str, set[Stage]] = {
    "simple": {Stage.CROSS_TEAM, Stage.EVIDENCE_CHECK, Stage.ARBITRATE},
    "standard": set(),
    "full": set(),
}


def get_skipped_stages(flow_plan: str) -> set[Stage]:
    """根据议题路由计划返回应跳过的阶段集合"""
    return _FLOW_SKIP_MAP.get(flow_plan, set())


def next_stage(current: Stage, flow_plan: str = "full") -> Stage | None:
    """返回下一阶段（跳过 flow_plan 标记的阶段），末尾返回 None"""
    skip = get_skipped_stages(flow_plan)
    idx = STAGE_ORDER.index(current)
    for i in range(idx + 1, len(STAGE_ORDER)):
        if STAGE_ORDER[i] not in skip:
            return STAGE_ORDER[i]
    return None


def is_terminal(state: MeetingState) -> bool:
    """是否处于终态（done / aborted / failed）"""
    return state.status in (MeetingStatus.DONE, MeetingStatus.ABORTED, MeetingStatus.FAILED)


def should_pause(state: MeetingState) -> bool:
    """是否应阻塞下一节点（paused 时阻塞）"""
    return state.status == MeetingStatus.PAUSED
