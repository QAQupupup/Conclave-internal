# 状态机 + 控制信号处理
from __future__ import annotations

from typing import Any

from app.models import MeetingState, MeetingStatus, Stage


# ---------- 控制信号 ----------

VALID_SIGNALS = {"pause", "resume", "abort", "inject", "loan"}


class ControlError(Exception):
    """控制信号处理异常"""


def apply_signal(state: MeetingState, signal: str, payload: dict[str, Any] | None = None) -> MeetingState:
    """处理控制信号，返回更新后的状态

    - pause: 保存快照，标记 paused
    - resume: 恢复快照，标记 running
    - abort: 标记 aborted，进入归档
    - inject: 追加注入消息，下一轮可见
    - loan: 记录借调请求（迭代一仅记录，不触发流程）
    """
    payload = payload or {}
    signal = signal.lower().strip()

    if signal not in VALID_SIGNALS:
        raise ControlError(f"未知控制信号: {signal}")

    if signal == "pause":
        if state.status != MeetingStatus.RUNNING:
            raise ControlError(f"当前状态 {state.status} 不可暂停")
        # 保存快照后阻塞下一节点
        state.paused_snapshot = state.snapshot()
        state.status = MeetingStatus.PAUSED
        return state

    if signal == "resume":
        if state.status != MeetingStatus.PAUSED:
            raise ControlError(f"当前状态 {state.status} 不可恢复")
        # 从快照恢复，继续
        snapshot = state.paused_snapshot
        if snapshot:
            restored = MeetingState(**snapshot)
            restored.status = MeetingStatus.RUNNING
            restored.paused_snapshot = None
            return restored
        state.status = MeetingStatus.RUNNING
        return state

    if signal == "abort":
        # 标记 aborted，进入归档
        state.status = MeetingStatus.ABORTED
        return state

    if signal == "inject":
        # 主持人注入消息，追加到 injected_messages，下一轮可见
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

    if signal == "loan":
        # 借调三问：迭代一仅记录请求，不触发裁决流程
        state.injected_messages.append(
            {
                "signal": "loan",
                "request": payload,
                "at_stage": state.stage.value,
            }
        )
        return state

    return state


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


def next_stage(current: Stage) -> Stage | None:
    """返回下一阶段，末尾返回 None"""
    idx = STAGE_ORDER.index(current)
    if idx + 1 < len(STAGE_ORDER):
        return STAGE_ORDER[idx + 1]
    return None


def is_terminal(state: MeetingState) -> bool:
    """是否处于终态（done / aborted）"""
    return state.status in (MeetingStatus.DONE, MeetingStatus.ABORTED)


def should_pause(state: MeetingState) -> bool:
    """是否应阻塞下一节点（paused 时阻塞）"""
    return state.status == MeetingStatus.PAUSED
