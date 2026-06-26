# 会议 CRUD + 运行 + 控场信号
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.db import get_meeting, list_messages, list_meetings, save_meeting
from app.events import bus, make_event
from app.models import MeetingStatus, Stage
from app.orchestrator.runner import (
    Runner,
    get_state,
    load_or_create,
    set_state,
)
from app.orchestrator.state import apply_signal

router = APIRouter(prefix="/meetings", tags=["meetings"])

# 进程级后台任务注册表：meeting_id -> asyncio.Task
# 维护引用防止被 GC 回收，并用于 409 冲突检测
_running_tasks: dict[str, asyncio.Task] = {}


# ---------- 请求/响应模型 ----------

class CreateMeetingRequest(BaseModel):
    """创建会议请求"""
    topic: str = Field(..., description="会议议题")


class CreateMeetingResponse(BaseModel):
    """创建会议响应"""
    meeting_id: str
    topic: str
    stage: str
    status: str


class ControlRequest(BaseModel):
    """控场信号请求"""
    signal: str = Field(..., description="控制信号: pause|resume|abort|inject|loan")
    payload: dict[str, Any] = Field(default_factory=dict)


class RunResponse(BaseModel):
    """运行结果响应"""
    meeting_id: str
    stage: str
    status: str
    artifact: dict[str, Any] | None = None
    messages_count: int = 0


# ---------- 端点 ----------

@router.post("", response_model=CreateMeetingResponse)
async def create_meeting(req: CreateMeetingRequest) -> CreateMeetingResponse:
    """创建会议"""
    meeting_id = f"mtg-{uuid.uuid4().hex[:12]}"
    # 初始化运行态
    state = load_or_create(meeting_id, req.topic)
    # 持久化
    save_meeting(
        meeting_id=meeting_id,
        topic=req.topic,
        status=state.status.value,
        stage=state.stage.value,
        created_at=state.created_at,
        payload=state.snapshot(),
    )
    # 发布创建事件
    await bus.publish(
        make_event("meeting.created", meeting_id, {"meeting_id": meeting_id, "topic": req.topic})
    )
    return CreateMeetingResponse(
        meeting_id=meeting_id,
        topic=req.topic,
        stage=state.stage.value,
        status=state.status.value,
    )


@router.get("/{meeting_id}")
async def get_meeting_detail(meeting_id: str) -> dict[str, Any]:
    """取会议详情（含状态、产物、发言）"""
    state = get_state(meeting_id)
    if state is None:
        record = get_meeting(meeting_id)
        if record is None:
            raise HTTPException(status_code=404, detail="会议不存在")
        payload = record["payload"]
        return {
            "meeting_id": meeting_id,
            "topic": record["topic"],
            "stage": record["stage"],
            "status": record["status"],
            "artifact": payload.get("artifact"),
            "messages": list_messages(meeting_id),
            "confidence_flags": payload.get("confidence_flags", {}),
        }
    return {
        "meeting_id": meeting_id,
        "topic": state.topic,
        "stage": state.stage.value,
        "status": state.status.value,
        "clarified_topic": state.clarified_topic,
        "key_questions": state.key_questions,
        "team_config": state.team_config,
        "conflicts": state.conflicts,
        "evidence_set": state.evidence_set,
        "decision_record": state.decision_record,
        "artifact": state.artifact,
        "messages": state.messages,
        "confidence_flags": state.confidence_flags,
    }


@router.get("", response_model=list[dict[str, Any]])
async def list_all_meetings() -> list[dict[str, Any]]:
    """列出全部会议"""
    return list_meetings()


@router.post("/{meeting_id}/run")
async def run_meeting(meeting_id: str) -> dict[str, Any]:
    """触发会议完整流程（异步后台执行）

    立即返回 running 状态，通过 WebSocket 观看实时进度。
    - 会议不存在：404
    - 已有后台任务在运行：409
    - 已完成：返回 done
    - 已终止：400
    """
    state = get_state(meeting_id)
    if state is None:
        raise HTTPException(status_code=404, detail="会议不存在，请先创建")

    # 409：已有后台任务在运行（防止重复启动）
    existing_task = _running_tasks.get(meeting_id)
    if existing_task is not None and not existing_task.done():
        raise HTTPException(status_code=409, detail="会议正在运行中，请勿重复启动")

    if state.status == MeetingStatus.DONE:
        return {
            "meeting_id": meeting_id,
            "status": "done",
            "stage": state.stage.value,
            "message": "会议已完成，可通过 trace / charter 端点查看审计信息",
        }
    if state.status == MeetingStatus.ABORTED:
        raise HTTPException(status_code=400, detail="会议已终止")

    # resume：从暂停态恢复
    if state.status == MeetingStatus.PAUSED:
        state.status = MeetingStatus.RUNNING
        state.paused_snapshot = None

    # 启动后台任务执行完整六阶段流程
    task = asyncio.create_task(_run_meeting_bg(meeting_id))
    _running_tasks[meeting_id] = task
    return {
        "meeting_id": meeting_id,
        "status": "running",
        "message": "会议已启动，通过 WS 观看实时进度",
    }


async def _run_meeting_bg(meeting_id: str) -> None:
    """后台执行会议完整流程

    - runner.run 内部会在开始时设置 status=running，结束时由 produce_node 设置 done
    - 异常时回滚状态避免卡死，并清理任务引用
    """
    try:
        state = get_state(meeting_id)
        if state is None:
            return
        runner = Runner()
        state = await runner.run(state)
        set_state(state)
    except Exception as e:  # noqa: BLE001 后台任务异常不应崩溃事件循环
        state = get_state(meeting_id)
        if state is not None:
            state.status = MeetingStatus.ABORTED
            set_state(state)
        # 记录异常到事件总线便于排查
        await bus.publish(
            make_event(
                "meeting.error",
                meeting_id,
                {"meeting_id": meeting_id, "error": str(e)},
            )
        )
    finally:
        _running_tasks.pop(meeting_id, None)


@router.post("/{meeting_id}/control")
async def control_meeting(meeting_id: str, req: ControlRequest) -> dict[str, Any]:
    """控场信号：pause / resume / abort / inject / loan"""
    state = get_state(meeting_id)
    if state is None:
        raise HTTPException(status_code=404, detail="会议不存在")
    try:
        state = apply_signal(state, req.signal, req.payload)
        set_state(state)
        # 持久化
        save_meeting(
            meeting_id=meeting_id,
            topic=state.topic,
            status=state.status.value,
            stage=state.stage.value,
            created_at=state.created_at,
            payload=state.snapshot(),
        )
        # 发布 control.signal 回执事件
        await bus.publish(
            make_event(
                "control.signal",
                meeting_id,
                {"signal": req.signal, "status": state.status.value, "payload": req.payload},
            )
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {
        "meeting_id": meeting_id,
        "signal": req.signal,
        "status": state.status.value,
        "stage": state.stage.value,
    }


# ---------- 审计端点 ----------

@router.get("/{meeting_id}/trace")
async def get_trace(meeting_id: str) -> dict[str, Any]:
    """LLM 调用追踪审计：从 MeetingState.llm_trace 取调用记录

    返回 {meeting_id, summary{...}, calls[]}
    - 会议不存在返回 404
    - stub 模式下 calls 为空（StubLLM 不记录调用），仅 RealLLM 有记录
    """
    state = get_state(meeting_id)
    if state is None:
        raise HTTPException(status_code=404, detail="会议不存在")

    trace = state.llm_trace
    calls = [c.model_dump(mode="json") for c in trace.calls]
    total = len(trace.calls)
    successful = sum(1 for c in trace.calls if c.validation_status == "valid")
    fallback = sum(1 for c in trace.calls if c.validation_status == "fallback_stub")
    inconsistent = sum(1 for c in trace.calls if c.consistency_status != "consistent")
    latencies = [c.latency_ms for c in trace.calls if c.latency_ms > 0]
    avg_latency = sum(latencies) / len(latencies) if latencies else 0
    return {
        "meeting_id": meeting_id,
        "summary": {
            "total_calls": total,
            "successful": successful,
            "fallback": fallback,
            "inconsistent": inconsistent,
            "avg_latency_ms": avg_latency,
        },
        "calls": calls,
    }


@router.get("/{meeting_id}/charter")
async def get_charter_detail(meeting_id: str) -> dict[str, Any]:
    """会议宪章审计：取 charter + conclusion_chain + confidence_flags + drift_log

    - charter 为 None（clarify 未完成）时返回提示信息
    - 会议不存在返回 404
    """
    state = get_state(meeting_id)
    if state is None:
        raise HTTPException(status_code=404, detail="会议不存在")

    if state.charter is None:
        return {
            "charter": None,
            "message": "宪章尚未建立（clarify 阶段未完成）",
        }

    return {
        "charter": state.charter.model_dump(mode="json"),
        "conclusion_chain": {
            "conclusions": [c.model_dump(mode="json") for c in state.conclusion_chain.conclusions],
        },
        "confidence_flags": state.confidence_flags,
        "drift_log": state.drift_log,
    }


@router.get("/{meeting_id}/events")
async def get_events(meeting_id: str, from_seq: int = 0) -> dict[str, Any]:
    """导出会议事件历史（审计/回放用）

    - from_seq > 0 时返回增量事件（seq > from_seq）
    - from_seq = 0 时返回全部事件
    - 会议不存在返回 404
    """
    state = get_state(meeting_id)
    if state is None:
        raise HTTPException(status_code=404, detail="会议不存在")

    events = bus.replay(meeting_id, from_seq)
    return {
        "meeting_id": meeting_id,
        "from_seq": from_seq,
        "last_seq": bus.last_seq(meeting_id),
        "count": len(events),
        "events": [e.model_dump(mode="json") for e in events],
    }
