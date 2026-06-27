# 会议 CRUD + 运行 + 控场信号
from __future__ import annotations

import asyncio
import os
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

# 最大并行会议数（防止资源耗尽），可通过环境变量 CONCLAVE_MAX_CONCURRENT 配置
MAX_CONCURRENT_MEETINGS = int(os.environ.get("CONCLAVE_MAX_CONCURRENT", "5"))
# 信号量控制并发：限制同时运行的会议数量，超出上限的会议排队等待
_meeting_semaphore = asyncio.Semaphore(MAX_CONCURRENT_MEETINGS)


# ---------- 请求/响应模型 ----------

class CreateMeetingRequest(BaseModel):
    """创建会议请求"""
    topic: str = Field(..., description="会议议题")
    deliverable_type: str = Field("prd_openapi", description="产出类型: prd_openapi|design_doc|comprehensive|research_report|business_report|code_analysis|tested_system")


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
    from app.observability.log_bus import log_bus
    from app.context import get_request_id

    meeting_id = f"mtg-{uuid.uuid4().hex[:12]}"
    # 旁路日志：记录会议创建（因果链起点 - 用户请求）
    log_bus.info(
        f"会议创建: topic={req.topic[:80]}",
        logger="routers.meetings",
        extra={
            "meeting_id": meeting_id,
            "topic": req.topic,
            "action": "create_meeting",
            "request_id": get_request_id(),
        },
    )
    # 初始化运行态
    state = load_or_create(meeting_id, req.topic)
    state.deliverable_type = req.deliverable_type
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
        # 尝试从 SQLite 恢复到内存
        state = load_or_create(meeting_id, "")
        if state.topic == "":
            # 恢复失败，返回 404
            raise HTTPException(status_code=404, detail="会议不存在")
    # 统一走内存分支返回完整数据
    return {
        "meeting_id": meeting_id,
        "topic": state.topic,
        "stage": state.stage.value,
        "status": state.status.value,
        "clarified_topic": state.clarified_topic,
        "key_questions": state.key_questions,
        "team_config": state.team_config,
        "claims": state.claims,
        "conflicts": state.conflicts,
        "evidence_set": state.evidence_set,
        "decision_record": state.decision_record,
        "artifact": state.artifact,
        "messages": state.messages,
        "llm_trace": state.llm_trace.summary(),
        "confidence_flags": state.confidence_flags,
    }


@router.get("")
async def list_meetings_with_status() -> dict[str, Any]:
    """列出所有会议及其运行状态

    返回 {meetings[], concurrent_limit, running_count}：
    - meetings：每个会议含 meeting_id/topic/stage/status/created_at/is_running
    - concurrent_limit：最大并发会议数
    - running_count：当前正在运行的会议数
    """
    meetings = list_meetings()
    result = []
    for m in meetings:
        mid = m["id"]
        is_running = mid in _running_tasks and not _running_tasks[mid].done()
        result.append({
            "meeting_id": mid,
            "topic": m["topic"],
            "stage": m["stage"],
            "status": m["status"],
            "created_at": m.get("created_at"),
            "is_running": is_running,
        })
    return {
        "meetings": result,
        "concurrent_limit": MAX_CONCURRENT_MEETINGS,
        "running_count": sum(1 for t in _running_tasks.values() if not t.done()),
    }


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
    from app.observability.log_bus import log_bus
    from app.context import get_request_id

    log_bus.info(
        f"触发会议运行: meeting={meeting_id}",
        logger="routers.meetings",
        extra={
            "meeting_id": meeting_id,
            "action": "run_meeting",
            "trigger": "http_api",
            "request_id": get_request_id(),
        },
    )
    task = asyncio.create_task(_run_meeting_bg(meeting_id))
    _running_tasks[meeting_id] = task
    return {
        "meeting_id": meeting_id,
        "status": "running",
        "message": "会议已启动，通过 WS 观看实时进度",
    }


async def _run_meeting_bg(meeting_id: str) -> None:
    """后台执行会议完整流程（受并发信号量保护）

    - 通过 _meeting_semaphore 限制同时运行的会议数量，防止资源耗尽
    - runner.run 内部会在开始时设置 status=running，结束时由 produce_node 设置 done
    - 异常时回滚状态避免卡死，并清理任务引用
    """
    async with _meeting_semaphore:
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
        # 尝试从 SQLite 恢复到内存
        state = load_or_create(meeting_id, "")
        if state.topic == "":
            # 恢复失败，返回 404
            raise HTTPException(status_code=404, detail="会议不存在")

    trace = state.llm_trace
    calls = [c.model_dump(mode="json") for c in trace.calls]
    # 使用增强的 summary（含阶段统计、错误列表、延迟分布）
    return {
        "meeting_id": meeting_id,
        "summary": trace.summary(),
        "calls": calls,
    }


@router.get("/{meeting_id}/stats")
async def get_stats(meeting_id: str) -> dict[str, Any]:
    """会议运行统计：阶段耗时、置信度、消息数、冲突数、降级率

    用于快速评估一次会议的运行质量和系统健康度。
    - 会议不存在返回 404
    """
    state = get_state(meeting_id)
    if state is None:
        # 尝试从 SQLite 恢复到内存
        state = load_or_create(meeting_id, "")
        if state.topic == "":
            # 恢复失败，返回 404
            raise HTTPException(status_code=404, detail="会议不存在")

    # LLM 调用统计
    trace_summary = state.llm_trace.summary()
    # 漂移统计
    drift_count = sum(1 for d in state.drift_log if d.get("is_drift"))
    # 证据来源分布
    evidence_sources: dict[str, int] = {}
    for es in state.evidence_set:
        for a in es.get("assessments", []):
            src = a.get("source", "unknown")
            # 归类：doc:* → doc, web:* → web, common_knowledge* → common_knowledge, 其他 → assumption
            category = src.split(":")[0] if ":" in src else src.split("_")[0] if "_" in src else "unknown"
            evidence_sources[category] = evidence_sources.get(category, 0) + 1

    return {
        "meeting_id": meeting_id,
        "topic": state.topic,
        "stage": state.stage.value,
        "status": state.status.value,
        "llm_trace": trace_summary,
        "confidence_flags": state.confidence_flags,
        "message_count": len(state.messages),
        "claim_count": len(state.claims),
        "conflict_count": len(state.conflicts),
        "evidence_count": sum(len(es.get("assessments", [])) for es in state.evidence_set),
        "evidence_source_distribution": evidence_sources,
        "drift": {
            "total_checks": len(state.drift_log),
            "drift_detected": drift_count,
        },
        "borrowed_agents": len(state.borrowed_agents) if state.borrowed_agents else 0,
        "conclusion_chain_length": len(state.conclusion_chain.conclusions),
    }


@router.get("/{meeting_id}/charter")
async def get_charter_detail(meeting_id: str) -> dict[str, Any]:
    """会议宪章审计：取 charter + conclusion_chain + confidence_flags + drift_log

    - charter 为 None（clarify 未完成）时返回提示信息
    - 会议不存在返回 404
    """
    state = get_state(meeting_id)
    if state is None:
        # 尝试从 SQLite 恢复到内存
        state = load_or_create(meeting_id, "")
        if state.topic == "":
            # 恢复失败，返回 404
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
        # 尝试从 SQLite 恢复到内存
        state = load_or_create(meeting_id, "")
        if state.topic == "":
            # 恢复失败，返回 404
            raise HTTPException(status_code=404, detail="会议不存在")

    events = bus.replay(meeting_id, from_seq)
    return {
        "meeting_id": meeting_id,
        "from_seq": from_seq,
        "last_seq": bus.last_seq(meeting_id),
        "count": len(events),
        "events": [e.model_dump(mode="json") for e in events],
    }
