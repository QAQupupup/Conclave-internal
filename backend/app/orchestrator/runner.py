# 编排运行器：按序跑节点，每步 publish 阶段切换事件
from __future__ import annotations

import time
from typing import Any

from app.db import list_messages, save_meeting, save_message
from app.events import bus, make_event
from app.logging_config import get_logger
from app.models import MeetingState, MeetingStatus, Stage
from app.orchestrator.nodes import NODES
from app.orchestrator.state import STAGE_ORDER, is_terminal, should_pause

logger = get_logger("orchestrator.runner")


class Runner:
    """会议编排运行器

    按状态机六阶段顺序执行节点，每步前后 publish stage.changed 事件，
    每个节点内部自行 publish agent.spoke / evidence.attached / artifact.generated。
    """

    async def run(self, state: MeetingState) -> MeetingState:
        """从当前阶段跑到底（或被 pause / abort 打断）"""
        # 设置追踪上下文（后续所有日志/事件/LLM 调用自动关联）
        from app.context import (
            set_meeting_id, reset_meeting_id,
            get_request_id, set_request_id, reset_request_id, new_request_id,
            set_runner_session_id, reset_runner_session_id, new_runner_session_id,
        )
        from app.observability.log_bus import log_bus

        mid_token = set_meeting_id(state.meeting_id)
        # 分配 runner 执行会话 ID（关联一次 run 期间的所有操作）
        rsid = new_runner_session_id()
        rsid_token = set_runner_session_id(rsid)
        # 如果不在 HTTP 请求上下文中（request_id 为默认值），生成一个用于会议运行期间
        rid_token = None
        if get_request_id() == "-":
            rid_token = set_request_id(new_request_id())

        # 旁路日志：记录 runner session 开始（因果链起点）
        log_bus.info(
            f"Runner session 开始: meeting={state.meeting_id}, start_stage={state.stage.value}",
            logger="orchestrator.runner",
            extra={
                "meeting_id": state.meeting_id,
                "runner_session_id": rsid,
                "start_stage": state.stage.value,
                "start_status": state.status.value,
                "trigger": "http_api" if rid_token is None else "internal",
            },
        )
        logger.info("会议 %s 开始运行，起始阶段: %s (session=%s)", state.meeting_id, state.stage.value, rsid)
        # 进入运行态（resume / 首次执行统一标记为 running）
        state.status = MeetingStatus.RUNNING
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
                logger.info("会议 %s 已暂停，等待 resume", state.meeting_id)
                # 等待 resume：迭代一同步实现里直接退出，由 control 接口恢复后再调 run
                self._persist(state)
                return state

            current_stage = state.stage
            node = NODES.get(current_stage)
            if node is None:
                logger.warning("会议 %s 阶段 %s 无对应节点，终止", state.meeting_id, current_stage.value)
                break

            # 执行节点
            t0 = time.monotonic()
            logger.debug("会议 %s 执行阶段: %s", state.meeting_id, current_stage.value)
            state = await node(state)
            elapsed = time.monotonic() - t0
            conf = state.confidence_flags.get(current_stage.value, "unknown")
            logger.info("会议 %s 阶段 %s 完成 (%.2fs, confidence=%s)", state.meeting_id, current_stage.value, elapsed, conf)

            # 诊断日志：节点返回后、_persist 前
            log_bus.info(
                f"节点返回: stage={current_stage.value}, status={state.status.value}, elapsed={elapsed:.2f}s",
                logger="orchestrator.runner",
                extra={"stage": current_stage.value, "status": state.status.value, "elapsed_s": round(elapsed, 2)},
            )

            # 持久化中间态
            self._persist(state)

            # 诊断日志：_persist 完成
            log_bus.info(
                f"持久化完成: stage={current_stage.value}, messages={len(state.messages)}",
                logger="orchestrator.runner",
                extra={"stage": current_stage.value, "messages_count": len(state.messages)},
            )

            # 终止判断
            if is_terminal(state):
                log_bus.info(
                    f"检测到终态: stage={state.stage.value}, status={state.status.value}",
                    logger="orchestrator.runner",
                )
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

        logger.info("会议 %s 运行结束: stage=%s, status=%s", state.meeting_id, state.stage.value, state.status.value)
        # 旁路日志：记录 runner session 结束（因果链终点）
        log_bus.info(
            f"Runner session 结束: meeting={state.meeting_id}, end_stage={state.stage.value}, status={state.status.value}",
            logger="orchestrator.runner",
            extra={
                "meeting_id": state.meeting_id,
                "runner_session_id": rsid,
                "end_stage": state.stage.value,
                "end_status": state.status.value,
            },
        )
        # 恢复追踪上下文
        reset_meeting_id(mid_token)
        reset_runner_session_id(rsid_token)
        if rid_token is not None:
            reset_request_id(rid_token)
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
    """从内存取或新建运行态；内存未命中时从 SQLite 恢复"""
    existing = get_state(meeting_id)
    if existing is not None:
        return existing
    # 尝试从 SQLite 恢复
    from app.db import get_meeting
    record = get_meeting(meeting_id)
    if record is not None:
        payload = record["payload"]
        try:
            state = MeetingState(**payload)
            set_state(state)
            logger.info("会议 %s 从 SQLite 恢复运行态", meeting_id)
            return state
        except Exception as e:
            logger.warning("会议 %s 从 SQLite 恢复失败: %s，创建新状态", meeting_id, e)
    return new_state(meeting_id, topic, doc_summaries)
