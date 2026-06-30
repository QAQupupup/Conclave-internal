# 状态机 + 控制信号处理
from __future__ import annotations

from typing import Any, Callable

from app.models import MeetingState, MeetingStatus, Stage


# ---------- 控制信号 ----------

VALID_SIGNALS = {"pause", "resume", "abort", "inject", "loan"}


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
    msg = payload.get("message", payload.get("content", ""))
    if msg:
        state.injected_messages.append(
            {
                "signal": "inject",
                "content": msg,
                "at_stage": state.stage.value,
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


# 信号 → 处理器 注册表（命令模式 + Registry）
_SIGNAL_HANDLERS: dict[str, Callable[[MeetingState, dict[str, Any]], MeetingState]] = {
    "pause": _handle_pause,
    "resume": _handle_resume,
    "abort": _handle_abort,
    "inject": _handle_inject,
    "loan": _handle_loan,
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
# standard：跳过 evidence_check（无冲突时自动跳过）
# full：完整六阶段
_FLOW_SKIP_MAP: dict[str, set[Stage]] = {
    "simple": {Stage.CROSS_TEAM, Stage.EVIDENCE_CHECK, Stage.ARBITRATE},
    "standard": {Stage.EVIDENCE_CHECK},
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
    """是否处于终态（done / aborted）"""
    return state.status in (MeetingStatus.DONE, MeetingStatus.ABORTED)


def should_pause(state: MeetingState) -> bool:
    """是否应阻塞下一节点（paused 时阻塞）"""
    return state.status == MeetingStatus.PAUSED
