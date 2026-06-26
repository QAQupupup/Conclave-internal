# 编排运行器：按序跑节点，每步 publish 阶段切换事件
from __future__ import annotations

from typing import Any

from app.db import list_messages, save_meeting, save_message
from app.events import bus, make_event
from app.models import MeetingState, MeetingStatus, Stage
from app.orchestrator.nodes import NODES
from app.orchestrator.state import STAGE_ORDER, is_terminal, should_pause


class Runner:
    """会议编排运行器

    按状态机六阶段顺序执行节点，每步前后 publish stage.changed 事件，
    每个节点内部自行 publish agent.spoke / evidence.attached / artifact.generated。
    """

    async def run(self, state: MeetingState) -> MeetingState:
        """从当前阶段跑到底（或被 pause / abort 打断）"""
        # 起始事件：进入首个阶段
        await bus.publish(
            make_event(
                "stage.changed",
                state.meeting_id,
                {"meeting_id": state.meeting_id, "from": None, "to": state.stage.value},
            )
        )

        while not is_terminal(state):
            # 暂停时阻塞下一节点
            if should_pause(state):
                # 等待 resume：迭代一同步实现里直接退出，由 control 接口恢复后再调 run
                self._persist(state)
                return state

            current_stage = state.stage
            node = NODES.get(current_stage)
            if node is None:
                break

            # 执行节点
            state = await node(state)

            # 持久化中间态
            self._persist(state)

            # 终止判断
            if is_terminal(state):
                break

            # 发布阶段切换事件
            from_stage = current_stage.value
            to_stage = state.stage.value
            await bus.publish(
                make_event(
                    "stage.changed",
                    state.meeting_id,
                    {"meeting_id": state.meeting_id, "from": from_stage, "to": to_stage},
                )
            )

        return state

    def _persist(self, state: MeetingState) -> None:
        """持久化会议状态与发言到 SQLite"""
        save_meeting(
            meeting_id=state.meeting_id,
            topic=state.topic,
            status=state.status.value,
            stage=state.stage.value,
            created_at=state.created_at,
            payload=state.snapshot(),
        )
        # 持久化尚未入库的发言（按 id 去重 upsert）
        for msg in state.messages:
            save_message(msg)


# 进程级运行态注册表：meeting_id -> MeetingState
_states: dict[str, MeetingState] = {}


def get_state(meeting_id: str) -> MeetingState | None:
    """取某会议的运行态"""
    return _states.get(meeting_id)


def set_state(state: MeetingState) -> None:
    """更新运行态"""
    _states[state.meeting_id] = state


def new_state(meeting_id: str, topic: str, doc_summaries: list[str] | None = None) -> MeetingState:
    """创建新的会议运行态"""
    state = MeetingState(
        meeting_id=meeting_id,
        topic=topic,
        doc_summaries=doc_summaries or [],
    )
    set_state(state)
    return state


def load_or_create(meeting_id: str, topic: str, doc_summaries: list[str] | None = None) -> MeetingState:
    """从内存取或新建运行态"""
    existing = get_state(meeting_id)
    if existing is not None:
        return existing
    return new_state(meeting_id, topic, doc_summaries)
