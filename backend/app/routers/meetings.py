# 会议 CRUD + 运行 + 控场信号
from __future__ import annotations

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
        return {
            "meeting_id": meeting_id,
            "topic": record["topic"],
            "stage": record["stage"],
            "status": record["status"],
            "artifact": record["payload"].get("artifact"),
            "messages": list_messages(meeting_id),
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
    }


@router.get("", response_model=list[dict[str, Any]])
async def list_all_meetings() -> list[dict[str, Any]]:
    """列出全部会议"""
    return list_meetings()


@router.post("/{meeting_id}/run", response_model=RunResponse)
async def run_meeting(meeting_id: str) -> RunResponse:
    """触发会议完整流程

    同步执行六阶段，返回最终状态与产物。
    """
    state = get_state(meeting_id)
    if state is None:
        raise HTTPException(status_code=404, detail="会议不存在，请先创建")
    if state.status == MeetingStatus.DONE:
        return RunResponse(
            meeting_id=meeting_id,
            stage=state.stage.value,
            status=state.status.value,
            artifact=state.artifact,
            messages_count=len(state.messages),
        )
    if state.status == MeetingStatus.ABORTED:
        raise HTTPException(status_code=400, detail="会议已终止")
    # 恢复后重新设为 running
    if state.status == MeetingStatus.PAUSED:
        state.status = MeetingStatus.RUNNING
        state.paused_snapshot = None

    runner = Runner()
    state = await runner.run(state)
    set_state(state)
    return RunResponse(
        meeting_id=meeting_id,
        stage=state.stage.value,
        status=state.status.value,
        artifact=state.artifact,
        messages_count=len(state.messages),
    )


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
