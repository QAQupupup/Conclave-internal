# 会议 CRUD + 运行 + 控场信号
from __future__ import annotations

import asyncio
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.db.engine import async_session_factory
from app.db.models import CostRecordModel
from app.db_legacy import (
    add_meeting_tag,
    batch_delete_meetings,
    get_agent_roles_by_ids,
    get_meeting,
    get_meeting_tags,
    get_meetings_by_ids,
    hard_delete_meeting,
    list_all_tags,
    list_agent_roles,
    list_messages,
    list_meetings,
    query_meetings,
    remove_meeting_tag,
    restore_meeting,
    save_meeting,
    soft_delete_meeting,
)
from app.events import bus, make_event
from app.models import MeetingStatus, Stage
from app.orchestrator.runner import (
    Runner,
    clear_state,
    get_state,
    load_or_create,
    set_state,
    _process_interventions,
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
    role_ids: list[str] = Field(default_factory=list, description="预选角色 ID 列表，为空则自动生成")
    reference_meeting_ids: list[str] = Field(default_factory=list, description="引用的历史会议 ID 列表")
    model: str = Field("", description="会议级模型覆盖（格式: provider_id:model_id 或纯 model_id），空=继承 ENV 默认")


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


class BatchDeleteRequest(BaseModel):
    """批量删除请求"""
    meeting_ids: list[str] = Field(..., description="待删除的会议 ID 列表")
    mode: str = Field("soft", description="删除模式: soft|hard")


class AddTagRequest(BaseModel):
    """添加标签请求"""
    tag: str = Field(..., min_length=1, max_length=32, description="标签名称")


# ---------- 端点 ----------

def _build_reference_context(ref_meetings: list[dict[str, Any]]) -> str:
    """将引用的历史会议构建为注入 prompt 的上下文文本"""
    if not ref_meetings:
        return ""
    lines = ["【历史会议参考】以下是你参与过的历史会议，请参考其结论、经验和产出："]
    for i, m in enumerate(ref_meetings, 1):
        topic = m.get("clarified_topic", m.get("topic", ""))
        artifact_summary = m.get("artifact_summary", "无产出")
        flow = m.get("flow_plan", "full")
        decisions = m.get("decision_record", {})
        decisions_text = ""
        if isinstance(decisions, dict) and decisions.get("decisions"):
            decisions_text = "；".join(
                d.get("rationale", "")[:80] for d in decisions["decisions"]
                if isinstance(d, dict)
            )
        key_qs = m.get("key_questions", [])
        key_qs_text = "；".join(key_qs[:3]) if key_qs else "无"
        lines.append(
            f"\n{i}. 会议「{topic}」\n"
            f"   关键问题：{key_qs_text}\n"
            f"   产出摘要：{artifact_summary}\n"
            f"   仲裁结论：{decisions_text or '无'}"
        )
    lines.append("\n请在本次会议中参考以上历史会议的结论，避免重复错误，并在此基础上深入讨论。")
    return "\n".join(lines)


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
    # 会议级模型覆盖（空=继承 ENV 默认，runner 启动时 resolve 为快照）
    if req.model:
        state.model_override = req.model

    # 加载角色配置：优先使用传入的 role_ids，否则从库中取所有活跃角色
    if req.role_ids:
        from app.routers.agent_roles import _init_builtin_roles
        _init_builtin_roles()
        role_rows = get_agent_roles_by_ids(req.role_ids)
    else:
        from app.routers.agent_roles import _init_builtin_roles
        _init_builtin_roles()
        role_rows = list_agent_roles(active_only=True)
    state.role_configs = role_rows

    # team_config 兼容：从 role_configs 构建
    state.team_config = [
        {"role": r["id"], "stance": r.get("default_stance", "")}
        for r in role_rows
    ]

    # 历史会议引用：存储 ID 并构建参考上下文
    state.reference_meeting_ids = [mid for mid in req.reference_meeting_ids if mid != meeting_id]
    if state.reference_meeting_ids:
        ref_meetings = get_meetings_by_ids(state.reference_meeting_ids)
        state.reference_context = _build_reference_context(ref_meetings)
        log_bus.info(
            f"历史会议引用: count={len(ref_meetings)}",
            logger="routers.meetings",
            extra={"meeting_id": meeting_id, "ref_count": len(ref_meetings)},
        )

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
    # [CON-20 修复] 同步广播 system 事件，通知前端 TaskBoard/Dashboard/Sidebar 立即刷新
    # 旧版依赖 5-10s 轮询，造成用户操作反馈延迟。系统级事件 meeting_id="*"
    await bus.publish(
        make_event("system.meetings.changed", "*",
                   {"action": "created", "meeting_id": meeting_id, "topic": req.topic})
    )
    return CreateMeetingResponse(
        meeting_id=meeting_id,
        topic=req.topic,
        stage=state.stage.value,
        status=state.status.value,
    )


@router.get("/tags")
async def list_tags() -> dict[str, Any]:
    """列出所有标签及其使用次数"""
    tags = list_all_tags()
    return {"tags": tags, "count": len(tags)}


@router.post("/batch-delete")
async def batch_delete(req: BatchDeleteRequest) -> dict[str, Any]:
    """批量删除会议

    - mode=soft：软删除，保留数据用于回归
    - mode=hard：永久删除，不可恢复
    - 运行中的会议会跳过并记入 failed

    返回 {deleted: [...], failed: [...], mode}
    """
    from app.observability.log_bus import log_bus
    from app.context import get_request_id

    # 过滤掉运行中的会议
    safe_ids: list[str] = []
    skipped: list[str] = []
    for mid in req.meeting_ids:
        if mid in _running_tasks and not _running_tasks[mid].done():
            skipped.append(mid)
        else:
            safe_ids.append(mid)

    result = batch_delete_meetings(safe_ids, mode=req.mode)
    # 运行中的会议也记入 failed
    result["failed"].extend(skipped)

    log_bus.info(
        f"批量删除会议: deleted={len(result['deleted'])}, failed={len(result['failed'])}",
        logger="routers.meetings",
        extra={
            "action": "batch_delete",
            "mode": req.mode,
            "deleted_ids": result["deleted"],
            "failed_ids": result["failed"],
            "request_id": get_request_id(),
        },
    )
    # 清理已删除会议的内存态
    # [CON-17 修复] set_state(mid, None) 会因签名不匹配触发 TypeError，
    # 改为 clear_state(mid) 以正确清理内存态。
    for mid in result["deleted"]:
        clear_state(mid)

    # [CON-20] system 广播：让前端 TaskBoard/Dashboard/Sidebar 立即感知
    if result["deleted"]:
        await bus.publish(
            make_event("system.meetings.changed", "*",
                       {"action": req.mode, "meeting_ids": result["deleted"]})
        )

    return {
        "deleted": result["deleted"],
        "failed": result["failed"],
        "mode": req.mode,
    }


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
        "role_configs": state.role_configs,
        "claims": state.claims,
        "conflicts": state.conflicts,
        "evidence_set": state.evidence_set,
        "decision_record": state.decision_record,
        "artifact": state.artifact,
        "messages": state.messages,
        "intervention_messages": state.intervention_messages,
        "llm_trace": state.llm_trace.summary(),
        "confidence_flags": state.confidence_flags,
    }


@router.get("/{meeting_id}/summary")
async def get_meeting_summary(meeting_id: str) -> dict[str, Any]:
    """获取会议摘要（用于历史会议引用下拉选择器）。

    返回简洁的会议摘要，包含 topic、产出、关键问题和仲裁结论。
    不包含原始 LLM trace 和完整消息列表。
    """
    meeting = get_meeting(meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="会议不存在")
    payload = meeting.get("payload", {})
    artifact = payload.get("artifact")
    from app.db_legacy import _extract_artifact_summary
    return {
        "meeting_id": meeting_id,
        "topic": meeting.get("topic", ""),
        "clarified_topic": payload.get("clarified_topic", meeting.get("topic", "")),
        "status": meeting.get("status", ""),
        "stage": meeting.get("stage", ""),
        "created_at": meeting.get("created_at", ""),
        "key_questions": payload.get("key_questions", [])[:5],
        "artifact_summary": _extract_artifact_summary(artifact) if artifact else "（无产出）",
        "flow_plan": payload.get("flow_plan", "full"),
        "decision_record": payload.get("decision_record"),
    }


class InjectReferenceRequest(BaseModel):
    """会议中注入历史会议引用请求"""
    reference_meeting_ids: list[str] = Field(..., description="要引用的历史会议 ID 列表")


class InterventionRequest(BaseModel):
    """用户介入对话请求"""
    content: str = Field(..., description="用户输入内容")
    reply_to_id: str | None = Field(None, description="回复的消息 ID")


@router.post("/{meeting_id}/intervene")
async def intervene_meeting(meeting_id: str, req: InterventionRequest) -> dict[str, Any]:
    """用户介入对话：向主持人发送私密消息。

    主持人会收到该消息，处理后回复到 intervention_messages 中。
    对话历史独立于 Agent 之间的聊天流，仅用户和主持人可见。
    """
    from app.observability.log_bus import log_bus
    from app.context import get_request_id

    state = get_state(meeting_id)
    if state is None:
        raise HTTPException(status_code=404, detail="会议不存在")

    if state.status == MeetingStatus.DONE:
        raise HTTPException(status_code=400, detail="会议已结束，无法介入")

    import uuid as _uuid
    msg_id = f"iv-{_uuid.uuid4().hex[:8]}"
    timestamp = datetime.now().isoformat()

    intervention_msg = {
        "id": msg_id,
        "sender": "user",
        "content": req.content,
        "reply_to_id": req.reply_to_id,
        "timestamp": timestamp,
        "processed": False,
    }

    state.intervention_messages.append(intervention_msg)

    # 同时作为 injected_message 通知主持人
    state.injected_messages.append({
        "signal": "intervene",
        "message_id": msg_id,
        "content": req.content,
        "reply_to_id": req.reply_to_id,
        "at_stage": state.stage.value,
        "rejected": False,
    })

    # 持久化
    save_meeting(
        meeting_id=meeting_id,
        topic=state.topic,
        status=state.status.value,
        stage=state.stage.value,
        created_at=state.created_at,
        payload=state.snapshot(),
    )

    log_bus.info(
        f"用户介入对话: {req.content[:50]}...",
        logger="routers.meetings",
        extra={"meeting_id": meeting_id, "msg_id": msg_id},
    )

    # 立即触发主持人回复（后台任务），不等待 runner 循环中当前节点完成
    import asyncio
    asyncio.create_task(_process_interventions(state))

    return {
        "meeting_id": meeting_id,
        "message_id": msg_id,
        "intervention_messages": state.intervention_messages,
    }


@router.post("/{meeting_id}/reference")
async def inject_meeting_reference(meeting_id: str, req: InjectReferenceRequest) -> dict[str, Any]:
    """在会议运行中注入历史会议引用（通过 @ 唤起或控制信号）。

    会将引用上下文追加到 state.reference_context 和 state.injected_messages，
    使下一轮 LLM 调用能感知到新引用的历史会议。
    """
    from app.observability.log_bus import log_bus
    from app.context import get_request_id

    state = get_state(meeting_id)
    if state is None:
        raise HTTPException(status_code=404, detail="会议不存在")

    if state.status == MeetingStatus.DONE:
        raise HTTPException(status_code=400, detail="会议已结束，无法注入引用")

    new_ids = [mid for mid in req.reference_meeting_ids if mid not in state.reference_meeting_ids and mid != meeting_id]
    if not new_ids:
        return {"meeting_id": meeting_id, "injected": 0, "message": "无新增引用会议"}

    ref_meetings = get_meetings_by_ids(new_ids)
    new_context = _build_reference_context(ref_meetings)

    # 追加到 reference_meeting_ids 和 reference_context
    state.reference_meeting_ids.extend(new_ids)
    if state.reference_context:
        state.reference_context += "\n\n" + new_context
    else:
        state.reference_context = new_context

    # 同时追加为 injected_message，让当前阶段正在运行的 LLM 也能感知
    import uuid as _uuid
    state.injected_messages.append({
        "signal": "inject_reference",
        "message_id": f"ref-{_uuid.uuid4().hex[:8]}",
        "content": new_context,
        "at_stage": state.stage.value,
        "rejected": False,
    })

    # 持久化
    save_meeting(
        meeting_id=meeting_id,
        topic=state.topic,
        status=state.status.value,
        stage=state.stage.value,
        created_at=state.created_at,
        payload=state.snapshot(),
    )

    log_bus.info(
        f"会议中注入历史会议引用: count={len(new_ids)}",
        logger="routers.meetings",
        extra={"meeting_id": meeting_id, "ref_ids": new_ids},
    )

    return {
        "meeting_id": meeting_id,
        "injected": len(new_ids),
        "total_references": len(state.reference_meeting_ids),
        "message": f"已注入 {len(new_ids)} 个历史会议引用",
    }


@router.get("")
async def list_meetings_with_status(
    q: str | None = None,
    limit: int = 20,
    offset: int = 0,
    tags: str | None = None,
) -> dict[str, Any]:
    """列出会议（支持搜索、分页、标签过滤）

    查询参数：
    - q：按议题关键词搜索（模糊匹配）
    - limit：每页数量（默认 20）
    - offset：偏移量（默认 0）
    - tags：逗号分隔的标签列表，会议需同时拥有所有标签才匹配

    返回 {meetings[], total, concurrent_limit, running_count}：
    - meetings：当前页的会议列表，每个含 meeting_id/topic/stage/status/created_at/is_running/tags
    - total：满足条件的总记录数
    - concurrent_limit：最大并发会议数
    - running_count：当前正在运行的会议数
    """
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
    result = query_meetings(q=q, limit=limit, offset=offset, tags=tag_list)
    items = []
    for m in result["items"]:
        mid = m["id"]
        is_running = mid in _running_tasks and not _running_tasks[mid].done()
        items.append({
            "meeting_id": mid,
            "topic": m["topic"],
            "stage": m["stage"],
            "status": m["status"],
            "created_at": m.get("created_at"),
            "is_running": is_running,
            "tags": m.get("tags", []),
        })
    return {
        "meetings": items,
        "total": result["total"],
        "concurrent_limit": MAX_CONCURRENT_MEETINGS,
        "running_count": sum(1 for t in _running_tasks.values() if not t.done()),
    }


@router.delete("/{meeting_id}")
async def delete_meeting(meeting_id: str, mode: str = "soft") -> dict[str, Any]:
    """删除会议

    - mode=soft（默认）：软删除，标记 status='deleted'，保留全部数据用于回归测试
    - mode=hard：硬删除，永久删除 meetings/messages/events 表记录，不可恢复
    - mode=restore：恢复软删除的会议

    运行中的会议不允许删除（返回 409）。
    """
    from app.observability.log_bus import log_bus
    from app.context import get_request_id

    # 检查会议是否存在
    meeting = get_meeting(meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="会议不存在")

    # 运行中的会议不允许删除
    if meeting_id in _running_tasks and not _running_tasks[meeting_id].done():
        raise HTTPException(status_code=409, detail="会议正在运行，无法删除")

    if mode == "soft":
        ok = soft_delete_meeting(meeting_id)
        if not ok:
            raise HTTPException(status_code=404, detail="会议不存在")
        log_bus.info(
            f"会议软删除: {meeting_id}",
            logger="routers.meetings",
            extra={"meeting_id": meeting_id, "action": "soft_delete", "request_id": get_request_id()},
        )
        # 清理内存态（统一清理函数：state、events、rag缓存、沙箱服务、浏览器上下文等）
        from app.orchestrator.runner import cleanup_meeting_resources
        cleanup_meeting_resources(meeting_id)
        return {"meeting_id": meeting_id, "deleted": True, "mode": "soft"}

    elif mode == "hard":
        ok = hard_delete_meeting(meeting_id)
        if not ok:
            raise HTTPException(status_code=404, detail="会议不存在")
        log_bus.info(
            f"会议硬删除: {meeting_id}",
            logger="routers.meetings",
            extra={"meeting_id": meeting_id, "action": "hard_delete", "request_id": get_request_id()},
        )
        # 清理内存态
        from app.orchestrator.runner import cleanup_meeting_resources
        cleanup_meeting_resources(meeting_id)
        return {"meeting_id": meeting_id, "deleted": True, "mode": "hard"}

    elif mode == "restore":
        ok = restore_meeting(meeting_id)
        if not ok:
            raise HTTPException(status_code=404, detail="会议不存在或未被软删除")
        log_bus.info(
            f"会议恢复: {meeting_id}",
            logger="routers.meetings",
            extra={"meeting_id": meeting_id, "action": "restore", "request_id": get_request_id()},
        )
        return {"meeting_id": meeting_id, "deleted": False, "mode": "restore"}

    else:
        raise HTTPException(status_code=400, detail="mode 必须是 soft/hard/restore")


@router.get("/{meeting_id}/tags")
async def get_tags(meeting_id: str) -> dict[str, Any]:
    """取会议的全部标签"""
    meeting = get_meeting(meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="会议不存在")
    tags = get_meeting_tags(meeting_id)
    return {"meeting_id": meeting_id, "tags": tags}


@router.post("/{meeting_id}/tags")
async def add_tag(meeting_id: str, req: AddTagRequest) -> dict[str, Any]:
    """为会议添加标签"""
    meeting = get_meeting(meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="会议不存在")
    tag = req.tag.strip()
    if not tag:
        raise HTTPException(status_code=400, detail="标签不能为空")
    added = add_meeting_tag(meeting_id, tag)
    return {"meeting_id": meeting_id, "tag": tag, "added": added}


@router.delete("/{meeting_id}/tags/{tag}")
async def remove_tag(meeting_id: str, tag: str) -> dict[str, Any]:
    """移除会议的某个标签"""
    meeting = get_meeting(meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="会议不存在")
    removed = remove_meeting_tag(meeting_id, tag)
    if not removed:
        raise HTTPException(status_code=404, detail="标签不存在")
    return {"meeting_id": meeting_id, "tag": tag, "removed": True}


@router.post("/{meeting_id}/run", status_code=202)
async def run_meeting(meeting_id: str) -> dict[str, Any]:
    """触发会议完整流程（异步后台执行）

    [CON-07 修复] 改为 202 Accepted + 提供 progress 端点 + 立即推 WS 进度事件。
    旧版返回 200 OK 但响应体是 {"status": "running"}，客户端无法区分"已处理" vs "运行中"。
    现在 202 Accepted 明确表示"已接受请求，开始处理"，配套提供：
    - WS 推送（前端订阅后立即收到 stage.changed 事件）
    - /meetings/{id}/progress 端点（轮询方式查进度）

    状态码：
    - 202：已接受，后台开始执行
    - 404：会议不存在
    - 409：会议正在运行中（防重入）
    - 200：会议已完成（直接返回）
    - 400：会议已终止
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

    # [CON-07 修复] 立即推一个 run.started 事件，前端可立即看到反馈
    # 旧版要等 runner.run 内部 stage.changed 才有事件，对前端来说有 100ms+ 延迟
    await bus.publish(
        make_event(
            "run.started",
            meeting_id,
            {
                "meeting_id": meeting_id,
                "stage": state.stage.value,
                "status": state.status.value,
                "ts": time.time(),
            },
        )
    )

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
        "stage": state.stage.value,
        "accepted_at": time.time(),
    }


@router.get("/{meeting_id}/progress")
async def get_meeting_progress(meeting_id: str) -> dict[str, Any]:
    """[CON-07 修复] 轮询式进度查询端点

    用途：前端无 WS 时也能查到运行进度。
    返回：status、stage、开始时间、消息数等。
    """
    state = get_state(meeting_id)
    if state is None:
        raise HTTPException(status_code=404, detail="会议不存在")

    task = _running_tasks.get(meeting_id)
    return {
        "meeting_id": meeting_id,
        "status": state.status.value,
        "stage": state.stage.value,
        "is_running": task is not None and not task.done(),
        "message_count": len(state.messages),
        "intervention_count": len(state.intervention_messages),
        "evidence_count": sum(len(m.get("evidence_refs") or []) for m in state.messages),
        "updated_at": time.time(),
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
            # 会议结束后立即清理资源密集型对象（不影响用户查看消息/报告）：
            # - RAG 向量缓存（chunks和向量占用大量内存）
            # - 浏览器上下文
            # 注意：保留沙箱服务容器，会议结束后用户仍可访问已部署服务
            try:
                from app.rag.store import clear_store
                clear_store(meeting_id)
            except Exception:
                pass
            try:
                from app.tools.browser_tool import browser_pool
                browser_pool.release_meeting(meeting_id)
            except Exception:
                pass
            # 保留沙箱服务容器，会议结束后用户仍可访问已部署服务
            # （服务生命周期由删除会议或 cleanup_all_services 管理）


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
        # 借调相关信号发布专门事件
        if req.signal == "approve_borrow":
            await bus.publish(make_event("borrow.approved_by_user", meeting_id, {
                "meeting_id": meeting_id,
                "request_id": req.payload.get("request_id", ""),
                "pending_borrow_request": None,
                "borrow_frozen": state.borrow_frozen,
            }))
        elif req.signal == "reject_borrow":
            await bus.publish(make_event("borrow.rejected_by_user", meeting_id, {
                "meeting_id": meeting_id,
                "request_id": req.payload.get("request_id", ""),
                "pending_borrow_request": None,
                "reason": req.payload.get("reason", ""),
                "borrow_frozen": state.borrow_frozen,
            }))
        elif req.signal == "freeze_borrow":
            await bus.publish(make_event("borrow.frozen", meeting_id, {
                "meeting_id": meeting_id,
                "pending_borrow_request": None,
                "borrow_frozen": True,
            }))
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


@router.get("/{meeting_id}/budget")
async def get_token_budget(meeting_id: str) -> dict[str, Any]:
    """token 预算状态：已消耗/剩余/百分比

    方案二（token 计量，不依赖厂商定价）：
    - 默认预算 500000 token
    - 超过 80% 标记 warning
    - 超过 100% 标记 exceeded
    """
    # 优先从 DB 重新加载，确保拿到持久化的 llm_trace / cost 等 aux 数据
    # （内存中的 state 在 persist 后 trace 已被清空）
    state = load_or_create(meeting_id, "")
    if state.topic == "":
        raise HTTPException(status_code=404, detail="会议不存在")

    summary = state.llm_trace.summary()
    used = summary.get("total_tokens", 0)
    budget = getattr(state, "token_budget", 500000) or 500000
    remaining = max(0, budget - used)
    pct = (used / budget * 100) if budget > 0 else 0

    status = "normal"
    if pct >= 100:
        status = "exceeded"
    elif pct >= 80:
        status = "warning"

    return {
        "meeting_id": meeting_id,
        "budget": budget,
        "used": used,
        "remaining": remaining,
        "percentage": round(pct, 1),
        "status": status,
        "input_tokens": summary.get("total_input_tokens", 0),
        "output_tokens": summary.get("total_output_tokens", 0),
        "total_calls": summary.get("total_calls", 0),
        "stage_breakdown": {
            stage: {
                "input_tokens": s.get("input_tokens", 0),
                "output_tokens": s.get("output_tokens", 0),
                "calls": s.get("calls", 0),
            }
            for stage, s in summary.get("stage_stats", {}).items()
        },
    }


@router.get("/{meeting_id}/audit")
async def get_full_audit(meeting_id: str) -> dict[str, Any]:
    """完整审计导出：聚合 trace、events、cost_records、stats、state snapshot

    用于重跑前的全链路回溯，包含：
    - 会议元数据和当前状态
    - 每次 LLM 调用的 prompt / raw_response / parsed_result
    - 所有事件（重点标注 produce.degradation）
    - 成本记录（来自 cost_records 表）
    - 统计摘要
    """
    # 优先从 DB 重新加载，确保拿到持久化的 llm_trace / cost 等 aux 数据
    # （内存中的 state 在 persist 后 trace 已被清空）
    state = load_or_create(meeting_id, "")
    if state.topic == "":
        raise HTTPException(status_code=404, detail="会议不存在")

    # 1. LLM trace
    trace_calls = [c.model_dump(mode="json") for c in state.llm_trace.calls]

    # 2. 事件历史
    events = bus.replay(meeting_id, from_seq=0)
    event_dicts = [e.model_dump(mode="json") for e in events]
    degradation_events = [
        e for e in event_dicts
        if e.get("type") in ("produce.degradation", "meeting.fallback_warning")
    ]

    # 3. 成本记录（从数据库查）
    cost_records: list[dict[str, Any]] = []
    try:
        async with async_session_factory() as session:
            result = await session.execute(
                select(CostRecordModel).where(CostRecordModel.meeting_id == meeting_id)
                .order_by(CostRecordModel.created_at.asc())
            )
            for row in result.scalars().all():
                cost_records.append({
                    "id": row.id,
                    "stage": row.stage,
                    "node": row.node,
                    "role": row.role,
                    "provider": row.provider,
                    "model": row.model,
                    "tool_name": row.tool_name,
                    "input_tokens": row.input_tokens,
                    "output_tokens": row.output_tokens,
                    "cost_usd": row.cost_usd,
                    "latency_ms": row.latency_ms,
                    "status": row.status,
                    "error": row.error,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                })
    except Exception as e:
        cost_records = [{"error": str(e)}]

    # 4. 统计摘要
    trace_summary = state.llm_trace.summary()
    drift_count = sum(1 for d in state.drift_log if d.get("is_drift"))

    # 5. 状态快照
    state_snapshot = {
        "meeting_id": state.meeting_id,
        "topic": state.topic,
        "stage": state.stage.value if state.stage else None,
        "status": state.status.value if state.status else None,
        "deliverable_type": state.deliverable_type,
        "confidence_flags": dict(state.confidence_flags) if state.confidence_flags else {},
        "token_budget": getattr(state, "token_budget", 500000),
        "message_count": len(state.messages),
        "claim_count": len(state.claims),
        "conflict_count": len(state.conflicts),
        "evidence_count": sum(len(es.get("assessments", [])) for es in state.evidence_set),
        "borrowed_agents": len(state.borrowed_agents) if state.borrowed_agents else 0,
        "conclusion_chain_length": len(state.conclusion_chain.conclusions),
        "drift": {
            "total_checks": len(state.drift_log),
            "drift_detected": drift_count,
        },
    }

    return {
        "meeting_id": meeting_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "meeting": state_snapshot,
        "trace": {
            "summary": trace_summary,
            "calls": trace_calls,
        },
        "events": {
            "total": len(event_dicts),
            "degradation_events": degradation_events,
            "all": event_dicts,
        },
        "cost_records": cost_records,
        "stats": {
            "total_tokens": trace_summary.get("total_tokens", 0),
            "total_calls": trace_summary.get("total_calls", 0),
            "fallback_calls": trace_summary.get("fallback_calls", 0),
            "inconsistent_calls": trace_summary.get("inconsistent_calls", 0),
            "avg_latency_ms": trace_summary.get("avg_latency_ms", 0),
            "total_cost_usd": round(sum(r.get("cost_usd", 0.0) for r in cost_records if "cost_usd" in r), 6),
        },
    }


@router.get("/{meeting_id}/attachments")
async def list_attachments(meeting_id: str) -> dict[str, Any]:
    """列出会议产出的附件文件（沙箱执行产出的 PNG/CSV/MD 等）"""
    state = get_state(meeting_id)
    if state is None:
        state = load_or_create(meeting_id, "")
        if state.topic == "":
            raise HTTPException(status_code=404, detail="会议不存在")
    attachments = (state.artifact or {}).get("attachments", [])
    return {"meeting_id": meeting_id, "attachments": attachments, "count": len(attachments)}


@router.get("/{meeting_id}/attachments/{filename}")
async def download_attachment(meeting_id: str, filename: str):
    """下载附件文件"""
    from fastapi.responses import FileResponse
    from pathlib import Path
    from app.config import settings

    state = get_state(meeting_id)
    if state is None:
        state = load_or_create(meeting_id, "")
        if state.topic == "":
            raise HTTPException(status_code=404, detail="会议不存在")
    attachments = (state.artifact or {}).get("attachments", [])
    target = next((a for a in attachments if a.get("filename") == filename), None)
    if target is None:
        raise HTTPException(status_code=404, detail="附件不存在")
    # path 可能是相对于 workspace_root 的路径（如 "mtg-xxx/app.py"）或绝对路径
    raw_path = Path(target["path"])
    if raw_path.is_absolute():
        file_path = raw_path
    else:
        file_path = Path(settings.workspace_root) / raw_path
    # 安全检查：防止路径遍历
    try:
        file_path = file_path.resolve()
        ws_root = Path(settings.workspace_root).resolve()
        if not str(file_path).startswith(str(ws_root)):
            raise HTTPException(status_code=403, detail="非法路径")
    except (OSError, ValueError):
        raise HTTPException(status_code=404, detail="附件路径无效")
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="附件文件已丢失")
    return FileResponse(
        str(file_path),
        filename=filename,
        media_type="application/octet-stream",
    )


@router.get("/skills/list")
async def list_skills():
    """列出所有已加载的Agent Skills（供调试/前端展示）"""
    from app.agents.skills import list_skills as _list_skills
    return {"skills": _list_skills()}


# ---------- LLM 模型管理端点 ----------

class SetModelRequest(BaseModel):
    """设置会议模型请求"""
    provider_id: str = Field("", description="厂商ID: siliconflow|deepseek|openai|openrouter|custom")
    model: str = Field("", description="模型ID，如 deepseek-ai/DeepSeek-V3.2")
    api_key: str = Field("", description="自定义API Key（BYOK），为空则使用默认")
    base_url: str = Field("", description="自定义Base URL（provider_id=custom时使用）")


@router.get("/llm/providers")
async def get_llm_providers():
    """列出所有已注册的LLM厂商及其能力"""
    from app.llm_providers import list_providers
    return {"providers": list_providers()}


@router.get("/llm/models")
async def get_llm_models(
    provider: str = "",
    api_key: str = "",
    base_url: str = "",
    refresh: bool = False,
):
    """查询可用模型列表
    
    - provider: 厂商ID，为空则使用默认
    - api_key: 自定义API Key（BYOK），为空则使用环境变量配置
    - base_url: 自定义Base URL（custom厂商时使用）
    - refresh: 是否强制刷新缓存
    """
    from app.llm_providers import fetch_models, categorize_models, RECOMMENDED_MODELS
    models = await fetch_models(
        provider_id=provider,
        api_key=api_key,
        base_url=base_url,
        use_cache=not refresh,
    )
    categories = categorize_models(models)
    return {
        "models": models,
        "categories": categories,
        "recommended": RECOMMENDED_MODELS,
        "total": len(models),
    }


@router.get("/llm/balance")
async def get_llm_balance(
    provider: str = "",
    api_key: str = "",
    base_url: str = "",
):
    """查询LLM账户余额
    
    - provider: 厂商ID
    - api_key: 自定义API Key，为空则使用环境变量
    """
    from app.llm_providers import fetch_balance
    result = await fetch_balance(provider_id=provider, api_key=api_key, base_url=base_url)
    return result


@router.get("/llm/pricing-status")
async def get_pricing_status():
    """获取定价数据源状态（动态抓取 vs 回退表）"""
    from app.pricing_fetcher import get_pricing_status
    return get_pricing_status()


@router.post("/llm/pricing/refresh")
async def refresh_pricing():
    """强制从硅基流动官网刷新定价数据"""
    from app.pricing_fetcher import refresh_pricing as _refresh
    result = await _refresh()
    return result


@router.post("/{meeting_id}/model")
async def set_meeting_model(meeting_id: str, req: SetModelRequest):
    """设置会议使用的模型和API Key（会议开始前调用）"""
    from app.llm_providers import set_meeting_model as _set_model
    # 校验会议存在
    state = get_state(meeting_id)
    if state is None:
        # 尝试恢复
        state = load_or_create(meeting_id, "")
        if state.topic == "":
            raise HTTPException(status_code=404, detail="会议不存在")
    # 不允许已结束的会议修改
    if state.status == MeetingStatus.DONE:
        raise HTTPException(status_code=400, detail="会议已结束，无法切换模型")
    # 不允许运行中的会议修改模型（模型快照已在启动时锁定）
    if state.status == MeetingStatus.RUNNING:
        raise HTTPException(status_code=403, detail="会议正在运行中，无法切换模型。请在创建会议时指定模型")
    cfg = _set_model(
        meeting_id=meeting_id,
        provider_id=req.provider_id,
        model=req.model,
        api_key=req.api_key,
        base_url=req.base_url,
    )

    # 如果用户提供了 API Key，自动持久化到数据库（加密存储）
    if req.api_key and req.provider_id:
        try:
            from app.services.key_store import save_api_key
            import asyncio
            asyncio.create_task(save_api_key(
                provider=req.provider_id,
                api_key=req.api_key,
                base_url=req.base_url or "",
                is_default=True,
            ))
        except Exception:
            pass  # 持久化失败不影响主流程
    from app.observability.log_bus import log_bus
    log_bus.info(
        f"会议模型切换: provider={cfg.provider_id}, model={cfg.model}",
        logger="routers.meetings",
        extra={"meeting_id": meeting_id, "provider": cfg.provider_id, "model": cfg.model},
    )
    return {
        "meeting_id": meeting_id,
        "provider_id": cfg.provider_id,
        "model": cfg.model,
        "has_custom_key": bool(cfg.api_key),
        "base_url": cfg.base_url,
    }


@router.get("/{meeting_id}/model")
async def get_meeting_model(meeting_id: str):
    """获取会议当前使用的模型配置"""
    from app.llm_providers import get_meeting_llm_config
    state = get_state(meeting_id)
    if state is None:
        raise HTTPException(status_code=404, detail="会议不存在")
    base_url, api_key, model, provider_id = get_meeting_llm_config(meeting_id)
    return {
        "meeting_id": meeting_id,
        "provider_id": provider_id,
        "model": model,
        "base_url": base_url,
        "has_custom_key": bool(api_key) and api_key != __import__("app.config", fromlist=["settings"]).settings.llm_api_key,
        "is_running": state.status not in (MeetingStatus.DONE,),
    }


# ---------- API Key 持久化管理 ----------

class SaveApiKeyRequest(BaseModel):
    """保存 API Key 请求"""
    provider: str = Field(..., description="厂商ID")
    api_key: str = Field(..., description="API Key 明文")
    name: str = Field(default="default", description="Key别名")
    base_url: str = Field(default="", description="自定义Base URL")
    is_default: bool = Field(default=True, description="是否设为默认")


@router.get("/llm/keys")
async def list_saved_keys():
    """列出所有已保存的 API Key（脱敏显示）"""
    from app.services.key_store import list_api_keys
    keys = await list_api_keys()
    return {"keys": keys}


@router.post("/llm/keys")
async def save_key(req: SaveApiKeyRequest):
    """保存 API Key（加密存储到数据库）"""
    from app.services.key_store import save_api_key
    result = await save_api_key(
        provider=req.provider,
        api_key=req.api_key,
        name=req.name,
        base_url=req.base_url,
        is_default=req.is_default,
    )
    return result


@router.delete("/llm/keys/{provider}/{name}")
async def delete_key(provider: str, name: str = "default"):
    """删除已保存的 API Key"""
    from app.services.key_store import delete_api_key
    ok = await delete_api_key(provider, name)
    if not ok:
        raise HTTPException(status_code=404, detail="Key不存在")
    return {"deleted": True, "provider": provider, "name": name}
