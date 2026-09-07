# 会议 CRUD + 运行 + 控场信号
from __future__ import annotations

import asyncio
import contextlib
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.dao.agent_role_dao import get_agent_roles_by_ids, list_agent_roles
from app.dao.artifact_dao import get_artifacts_by_ids
from app.dao.meeting_dao import (
    batch_delete_meetings,
    get_meeting,
    get_meetings_by_ids,
    hard_delete_meeting,
    query_meetings,
    restore_meeting,
    save_meeting,
    soft_delete_meeting,
)
from app.dao.tag_dao import (
    add_meeting_tag,
    get_meeting_tags,
    list_all_tags,
    remove_meeting_tag,
)
from app.db.engine import async_session_factory
from app.db.models import CostRecordModel
from app.events import bus, make_event
from app.lazy_asyncio import LazyLock, LazySemaphore
from app.models import MeetingStatus
from app.orchestrator.runner import (
    Runner,
    _process_interventions,
    clear_state,
    get_state,
    load_or_create,
    set_state,
)
from app.schemas.meeting import (
    AddTagRequest,
    BatchDeleteRequest,
    ControlRequest,
    CreateMeetingRequest,
    CreateMeetingResponse,
    InjectReferenceRequest,
    InterventionRequest,
    QueryBalanceRequest,
    QueryModelsRequest,
    SaveApiKeyRequest,
    SetModelRequest,
)
from app.utils.tasks import create_supervised_task
from conclave_core.state import apply_signal

router = APIRouter(prefix="/meetings", tags=["meetings"])

# 进程级后台任务注册表：meeting_id -> asyncio.Task
# 维护引用防止被 GC 回收，并用于 409 冲突检测
_running_tasks: dict[str, asyncio.Task] = {}
# [SECURITY-FIX] 每会议一把锁，防止 run 端点的 TOCTOU 竞态（双重启动）
_run_locks: dict[str, LazyLock] = {}

# 最大并行会议数（防止资源耗尽），可通过环境变量 CONCLAVE_MAX_CONCURRENT 配置
MAX_CONCURRENT_MEETINGS = int(os.environ.get("CONCLAVE_MAX_CONCURRENT", "5"))
# 信号量控制并发：限制同时运行的会议数量，超出上限的会议排队等待
_meeting_semaphore = LazySemaphore(MAX_CONCURRENT_MEETINGS)


# ---------- 端点 ----------


def _build_reference_context(ref_meetings: list[dict[str, Any]]) -> str:
    """将引用的历史会议构建为注入 prompt 的上下文文本"""
    if not ref_meetings:
        return ""
    lines = ["【历史会议参考】以下是你参与过的历史会议，请参考其结论、经验和产出："]
    for i, m in enumerate(ref_meetings, 1):
        topic = m.get("clarified_topic", m.get("topic", ""))
        artifact_summary = m.get("artifact_summary", "无产出")
        m.get("flow_plan", "full")
        decisions = m.get("decision_record", {})
        decisions_text = ""
        if isinstance(decisions, dict) and decisions.get("decisions"):
            decisions_text = "；".join(
                d.get("rationale", "")[:80] for d in decisions["decisions"] if isinstance(d, dict)
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


def _build_artifact_reference_context(artifacts: list[dict[str, Any]]) -> str:
    """将引用的上游产物构建为注入 prompt 的上下文文本（ADR-017 Phase 1 / I2）。

    与会议级引用（_build_reference_context）共享 reference_context 注入通道，
    但使用独立分节标题「[上游产物引用]」，血缘数据独立存 source_artifact_ids。
    """
    if not artifacts:
        return ""
    lines = ["[上游产物引用] 以下是本次会议引用的上游产物，请消费其结论并保持衔接："]
    for i, a in enumerate(artifacts, 1):
        title = a.get("title") or "（无标题）"
        summary = a.get("summary") or "（无摘要）"
        lines.append(
            f"\n{i}. 产物「{title}」（id={a.get('id', '')}，类型={a.get('type', '')}，v{a.get('version', 1)}）\n"
            f"   摘要：{summary}"
        )
    lines.append("\n请基于以上上游产物的结论展开本次会议的讨论与产出，避免重复已完成的工作。")
    return "\n".join(lines)


async def _maybe_ingest_project_repo(meeting_id: str, project_id: str) -> None:
    """ADR-017 Phase 2 第 3 条：议题会议创建后，项目绑定仓库后台摄入会议 workspace。

    fire-and-forget 语义：
    - 项目不存在/跨租户/未绑定仓库（纯文档型项目）→ 跳过；
    - clone 在受监督后台任务中执行，失败仅记日志，不阻断会议创建；
    - 项目信息在请求上下文内读取（租户 contextvar 可用），后台任务只做 git 操作不访问 DB。
    """
    from app.dao import project_dao
    from app.observability.log_bus import log_bus
    from app.routers.code import WORKSPACE_ROOT, _ingest_git

    try:
        project = await project_dao.get_project(project_id)
    except Exception as e:
        log_bus.warning(f"项目读取失败，跳过仓库后台摄入: {str(e)[:150]}", logger="routers.meetings")
        return
    if project is None:
        log_bus.warning(
            "项目不存在或跨租户，跳过仓库后台摄入",
            logger="routers.meetings",
            extra={"meeting_id": meeting_id, "project_id": project_id},
        )
        return
    repo_url = project.get("repo_url")
    if not repo_url:
        return

    meeting_dir = WORKSPACE_ROOT / meeting_id
    meeting_dir.mkdir(parents=True, exist_ok=True)
    branch = str(project.get("default_branch") or "main")

    async def _clone_repo() -> None:
        try:
            result = await _ingest_git(meeting_dir, meeting_id, str(repo_url), branch, None, None)
        except Exception as e:
            log_bus.warning(
                f"项目仓库后台摄入失败（不影响会议）: {str(e)[:200]}",
                logger="routers.meetings",
                extra={"meeting_id": meeting_id, "project_id": project_id},
            )
            return
        log_bus.info(
            f"项目仓库后台摄入完成: target={result.get('target_name', '')}, files={result.get('file_count', 0)}",
            logger="routers.meetings",
            extra={"meeting_id": meeting_id, "project_id": project_id},
        )

    create_supervised_task(_clone_repo(), name=f"project-repo-ingest-{meeting_id}")


@router.post("", response_model=CreateMeetingResponse)
async def create_meeting(req: CreateMeetingRequest, request: Request) -> CreateMeetingResponse:
    """创建会议"""
    from app.auth_guard import get_current_user
    from app.context import get_request_id
    from app.observability.log_bus import log_bus

    uid, username, _role = get_current_user(request)

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
            "owner": username,
        },
    )
    # 初始化运行态
    state = await load_or_create(meeting_id, req.topic)
    # [SECURITY-FIX] 设置会议所有者
    state.owner_username = username
    state.owner_uid = uid
    state.deliverable_type = req.deliverable_type
    # 标准化 flow_plan（兼容旧名称 fast/fast_path/deep_think/full）
    from app.orchestrator.instant import normalize_mode

    state.flow_plan = normalize_mode(req.flow_plan)
    state.debate_depth = req.debate_depth if req.debate_depth in ("light", "standard", "deep") else "standard"
    # 会议级模型覆盖（空=继承 ENV 默认，runner 启动时 resolve 为快照）
    if req.model:
        state.model_override = req.model
    # === 断点续传 & 自我迭代配置 ===
    state.auto_iterate = req.auto_iterate
    if req.max_iterations is not None:
        state.max_iterations = req.max_iterations
    if req.max_stage_retries is not None:
        state.max_stage_retries = req.max_stage_retries

    # 加载角色配置：优先使用传入的 role_ids，否则从库中取所有活跃角色
    if req.role_ids:
        from app.routers.agent_roles import _init_builtin_roles

        await _init_builtin_roles()
        role_rows = await get_agent_roles_by_ids(req.role_ids)
    else:
        from app.routers.agent_roles import _init_builtin_roles

        await _init_builtin_roles()
        role_rows = await list_agent_roles(active_only=True)
    state.role_configs = role_rows

    # team_config 兼容：从 role_configs 构建
    state.team_config = [{"role": r["id"], "stance": r.get("default_stance", "")} for r in role_rows]

    # 历史会议引用：存储 ID 并构建参考上下文
    state.reference_meeting_ids = [mid for mid in req.reference_meeting_ids if mid != meeting_id]
    if state.reference_meeting_ids:
        ref_meetings = await get_meetings_by_ids(state.reference_meeting_ids)
        state.reference_context = _build_reference_context(ref_meetings)
        log_bus.info(
            f"历史会议引用: count={len(ref_meetings)}",
            logger="routers.meetings",
            extra={"meeting_id": meeting_id, "ref_count": len(ref_meetings)},
        )

    # ADR-017 Phase 1（T1.9）：上游产物引用——校验租户归属后写入。
    # 不存在/跨租户的 id 静默剔除并记告警日志（不阻断创建，复用 produce.py 的拒绝模式）；
    # 有效产物的摘要拼入 reference_context（I2），血缘 id 记录到 source_artifact_ids。
    if req.source_artifact_ids:
        found_artifacts = await get_artifacts_by_ids(req.source_artifact_ids)
        found_ids = {a["id"] for a in found_artifacts}
        # 保持请求顺序去重，只保留当前租户可见的产物
        valid_ids = list(dict.fromkeys(aid for aid in req.source_artifact_ids if aid in found_ids))
        dropped = [aid for aid in req.source_artifact_ids if aid not in found_ids]
        if dropped:
            log_bus.warning(
                f"上游产物引用无效（不存在或跨租户），已剔除: count={len(dropped)}",
                logger="routers.meetings",
                extra={"meeting_id": meeting_id, "dropped_artifact_ids": dropped[:20]},
            )
        state.source_artifact_ids = valid_ids
        if valid_ids:
            # 按 valid_ids 顺序取产物摘要（found_artifacts 按 created_at 倒序，需重排）
            by_id = {a["id"]: a for a in found_artifacts}
            ordered = [by_id[aid] for aid in valid_ids]
            artifact_context = _build_artifact_reference_context(ordered)
            state.reference_context = (
                f"{state.reference_context}\n\n{artifact_context}" if state.reference_context else artifact_context
            )
        log_bus.info(
            f"上游产物引用: valid={len(valid_ids)}, dropped={len(dropped)}",
            logger="routers.meetings",
            extra={
                "meeting_id": meeting_id,
                "valid_count": len(valid_ids),
                "dropped_count": len(dropped),
            },
        )

    # ADR-017 Phase 2：从议题发起会议——校验议题 → 持久化会议 → 绑定（状态机）→ 回填归属。
    # 顺序约束：issues.assigned_meeting_id FK 指向 meetings.id，必须先落库会议再绑定，
    # 否则 FK 违规。绑定失败（状态并发变更）则硬删已落库会议，避免孤儿会议。
    # conflict 态允许重新绑会（D11：合入冲突后开新会议重做）。
    bound_issue: dict[str, Any] | None = None
    issue_row: dict[str, Any] | None = None
    if req.issue_id:
        from app.dao import issue_dao

        issue_row = await issue_dao.get_issue(req.issue_id)
        if issue_row is None:
            raise HTTPException(status_code=404, detail="议题不存在")
        if issue_row["status"] not in ("open", "scheduled", "conflict"):
            raise HTTPException(status_code=409, detail=f"议题当前状态不可绑定会议: {issue_row['status']}")

    # 持久化（先于议题绑定，见上方顺序约束）
    await save_meeting(
        meeting_id=meeting_id,
        topic=req.topic,
        status=state.status.value,
        stage=state.stage.value,
        created_at=state.created_at,
        payload=state.snapshot(),
        owner_username=username,
        project_id=state.project_id,
        issue_id=state.issue_id,
    )

    if issue_row is not None:
        from app.services.issue_service import bind_meeting

        bound_issue = await bind_meeting(issue_row["id"], meeting_id)
        if bound_issue is None:
            await hard_delete_meeting(meeting_id)
            raise HTTPException(status_code=409, detail="议题绑定失败（状态已并发变更），请刷新后重试")
        state.project_id = str(bound_issue["project_id"])
        state.issue_id = str(bound_issue["id"])
        # 回填项目归属/议题关联（upsert 第二次保存；首次保存时 FK 未就绪不能携带）
        await save_meeting(
            meeting_id=meeting_id,
            topic=req.topic,
            status=state.status.value,
            stage=state.stage.value,
            created_at=state.created_at,
            payload=state.snapshot(),
            owner_username=username,
            project_id=state.project_id,
            issue_id=state.issue_id,
        )
    # ADR-017 Phase 2 第 3 条：议题会议创建后，项目绑定仓库后台摄入会议 workspace。
    # fire-and-forget：摄入失败仅记日志，不阻断会议创建。
    if bound_issue is not None:
        await _maybe_ingest_project_repo(meeting_id, str(bound_issue["project_id"]))
    # [临近话题] 议题向量落库（创建时即写入，供其他会议创建时推荐 / 完成后聚类）
    try:
        from app.rag.topic_index import get_topic_index
        from app.tenants.context import get_tenant_id

        tid = get_tenant_id()
        await get_topic_index().upsert(
            meeting_id=meeting_id,
            tenant_id=tid,
            topic=req.topic,
            status="running",
            deliverable_type=state.deliverable_type,
            summary="",
            tags=getattr(req, "tags", None) or [],
        )
    except Exception as e:
        log_bus.warning("议题向量写入失败（忽略，不阻塞创建）: %s", str(e)[:150])
    # 发布创建事件
    # 创建会议工作区目录（确保在工作区立即可见）
    try:
        from pathlib import Path as _Path

        from app.config import settings as _settings

        _ws_dir = _Path(_settings.workspace_root) / meeting_id
        _ws_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass  # 目录创建失败不影响会议创建
    await bus.publish(make_event("meeting.created", meeting_id, {"meeting_id": meeting_id, "topic": req.topic}))
    # [CON-20 修复] 同步广播 system 事件，通知前端 TaskBoard/Dashboard/Sidebar 立即刷新
    # 旧版依赖 5-10s 轮询，造成用户操作反馈延迟。系统级事件 meeting_id="*"
    await bus.publish(
        make_event("system.meetings.changed", "*", {"action": "created", "meeting_id": meeting_id, "topic": req.topic})
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
    tags = await list_all_tags()
    return {"tags": tags, "count": len(tags)}


@router.get("/related")
async def suggest_related_meetings(
    request: Request,
    topic: str = Query(default="", description="当前输入的议题文本，用于检索相似历史会议"),
    limit: int = Query(default=5, ge=1, le=20),
) -> dict[str, Any]:
    """创建会议时的临近话题推荐：根据议题文本检索语义相似的历史会议。

    返回的会议可被勾选后填充 reference_meeting_ids（复用现有参考上下文全链路）。
    """
    from app.rag.topic_index import get_topic_index
    from app.tenants.context import get_tenant_id

    if not topic.strip():
        return {"meetings": []}
    tid = get_tenant_id()
    try:
        results = await get_topic_index().search(topic, tid, top_k=limit)
    except Exception:
        results = []
    # 只返回已完成（done）的会议作为可信参考
    results = [r for r in results if r.get("status") == "done"]
    return {"meetings": results}


@router.get("/{meeting_id}/related")
async def related_meetings_for(
    meeting_id: str,
    request: Request,
    limit: int = Query(default=5, ge=1, le=20),
) -> dict[str, Any]:
    """某会议完成后的相似历史会议（基于议题向量，排除自身）。"""
    from app.tenants.context import get_tenant_id

    tid = get_tenant_id()
    try:
        from app.services.knowledge_graph import get_related_meetings

        results = await get_related_meetings(meeting_id, tid, top_k=limit)
    except Exception:
        results = []
    return {"meetings": results}


@router.post("/batch-delete")
async def batch_delete(req: BatchDeleteRequest, request: Request) -> dict[str, Any]:
    """批量删除会议

    - mode=soft：软删除，保留数据用于回归
    - mode=hard：永久删除，不可恢复
    - 运行中的会议会跳过并记入 failed
    - 无删除权限的会议会跳过并记入 failed

    权限要求：system admin / 会议创建者 / team owner / maintainer 可删除。
    返回 {deleted: [...], failed: [...], mode}
    """
    from app.auth_guard import assert_can_delete_meeting, get_current_user, is_admin
    from app.context import get_request_id
    from app.observability.log_bus import log_bus

    # 系统管理员可批量删除任意会议，无需逐条校验
    _uid, _username, role = get_current_user(request)
    admin_mode = is_admin(role)

    # 逐条校验权限 + 过滤运行中的会议
    safe_ids: list[str] = []
    skipped: list[str] = []
    for mid in req.meeting_ids:
        # 运行中的会议跳过
        if mid in _running_tasks and not _running_tasks[mid].done():
            skipped.append(mid)
            continue
        # 非管理员逐条校验删除权限
        if not admin_mode:
            meeting = await get_meeting(mid)
            if meeting is None:
                skipped.append(mid)
                continue
            try:
                await assert_can_delete_meeting(request, meeting)
            except HTTPException:
                skipped.append(mid)
                continue
        safe_ids.append(mid)

    result = await batch_delete_meetings(safe_ids, mode=req.mode)
    # 运行中/无权限的会议也记入 failed
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

    # 硬删除：同步清理各会议的语义索引工作区（ADR-018 Phase C，失败仅告警）
    if req.mode == "hard":
        for mid in result["deleted"]:
            await _cleanup_semantic_index_quiet(mid)

    # [CON-20] system 广播：让前端 TaskBoard/Dashboard/Sidebar 立即感知
    if result["deleted"]:
        await bus.publish(
            make_event("system.meetings.changed", "*", {"action": req.mode, "meeting_ids": result["deleted"]})
        )

    return {
        "deleted": result["deleted"],
        "failed": result["failed"],
        "mode": req.mode,
    }


@router.get("/{meeting_id}")
async def get_meeting_detail(meeting_id: str, request: Request) -> dict[str, Any]:
    """取会议详情（含状态、产物、发言）"""
    from app.auth_guard import assert_meeting_access

    state = get_state(meeting_id)
    if state is None:
        # 尝试从 SQLite 恢复到内存
        state = await load_or_create(meeting_id, "")
        if state.topic == "":
            # 恢复失败，返回 404
            raise HTTPException(status_code=404, detail="会议不存在")
    # [SECURITY-FIX] 校验访问权限
    assert_meeting_access(request, state, require_owner=False, require_write=False)
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


@router.get("/{meeting_id}/report-layout")
async def get_report_layout(meeting_id: str, type: str | None = None) -> dict[str, Any]:
    """获取报告布局 spec。

    后端根据 deliverable_type 和 artifact 生成 layout spec，
    前端按 spec 通用渲染，不再硬编码任何模板。

    参数:
        meeting_id: 会议 ID
        type: 可选，指定产出类型。不传则使用会议自身的 deliverable_type。
    """
    state = get_state(meeting_id)
    if state is None:
        state = await load_or_create(meeting_id, "")
        if state.topic == "":
            raise HTTPException(status_code=404, detail="会议不存在")

    # 优先从 artifact 中读取已生成的 layout spec
    artifact = state.artifact or {}
    layout_spec = artifact.get("report_layout")

    if layout_spec is None:
        # layout spec 未生成，实时构建
        from datetime import datetime, timezone

        from app.report_layout import build_report_layout

        deliverable_type = type or state.deliverable_type
        decisions = []
        if state.decision_record:
            decisions = state.decision_record.get("decisions", []) if isinstance(state.decision_record, dict) else []
        adopted_claims = [
            c.get("claim") or c.get("text") or "" if isinstance(c, dict) else c
            for c in state.claims
            if (c.get("adopted", True) if isinstance(c, dict) else True)
        ]
        llm_trace_data = {}
        if state.llm_trace:
            llm_trace_data = {
                "total_calls": getattr(state.llm_trace, "total_calls", 0),
                "success_rate": f"{getattr(state.llm_trace, 'success_count', 0)}/{max(getattr(state.llm_trace, 'total_calls', 1), 1)}",
                "total_tokens": getattr(state.llm_trace, "total_tokens", 0),
                "input_tokens": getattr(state.llm_trace, "input_tokens", 0),
                "output_tokens": getattr(state.llm_trace, "output_tokens", 0),
            }
        layout_spec = build_report_layout(
            deliverable_type=deliverable_type,
            artifact=artifact,
            meeting_meta={
                "meeting_id": meeting_id,
                "topic": state.clarified_topic or state.topic,
                "status": state.status.value if hasattr(state.status, "value") else str(state.status),
                "generated_at": datetime.now(timezone.utc).isoformat(),
            },
            confidence=state.confidence_flags,
            decisions=decisions,
            adopted_claims=adopted_claims,
            key_questions=state.key_questions,
            team_config=state.team_config,
            conflicts=state.conflicts,
            llm_trace=llm_trace_data,
        )

    return layout_spec


@router.get("/{meeting_id}/summary")
async def get_meeting_summary(meeting_id: str) -> dict[str, Any]:
    """获取会议摘要（用于历史会议引用下拉选择器）。

    返回简洁的会议摘要，包含 topic、产出、关键问题和仲裁结论。
    不包含原始 LLM trace 和完整消息列表。
    """
    meeting = await get_meeting(meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="会议不存在")
    payload = meeting.get("payload", {})
    artifact = payload.get("artifact")
    from app.dao.meeting_dao import _extract_artifact_summary

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


@router.post("/{meeting_id}/intervene")
async def intervene_meeting(meeting_id: str, req: InterventionRequest, request: Request) -> dict[str, Any]:
    """用户介入对话：向主持人发送私密消息。

    主持人会收到该消息，处理后回复到 intervention_messages 中。
    对话历史独立于 Agent 之间的聊天流，仅用户和主持人可见。
    """
    from app.auth_guard import assert_meeting_access
    from app.observability.log_bus import log_bus

    state = get_state(meeting_id)
    if state is None:
        raise HTTPException(status_code=404, detail="会议不存在")
    # [SECURITY-FIX] 校验写权限（owner 或参与者可以介入）
    assert_meeting_access(request, state, require_owner=False, require_write=True)

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
    state.injected_messages.append(
        {
            "signal": "intervene",
            "message_id": msg_id,
            "content": req.content,
            "reply_to_id": req.reply_to_id,
            "at_stage": state.stage.value,
            "rejected": False,
        }
    )

    # 持久化
    await save_meeting(
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
    create_supervised_task(_process_interventions(state), name=f"interventions-{state.meeting_id[:8]}")

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

    state = get_state(meeting_id)
    if state is None:
        raise HTTPException(status_code=404, detail="会议不存在")

    if state.status == MeetingStatus.DONE:
        raise HTTPException(status_code=400, detail="会议已结束，无法注入引用")

    new_ids = [mid for mid in req.reference_meeting_ids if mid not in state.reference_meeting_ids and mid != meeting_id]
    if not new_ids:
        return {"meeting_id": meeting_id, "injected": 0, "message": "无新增引用会议"}

    ref_meetings = await get_meetings_by_ids(new_ids)
    new_context = _build_reference_context(ref_meetings)

    # 追加到 reference_meeting_ids 和 reference_context
    state.reference_meeting_ids.extend(new_ids)
    if state.reference_context:
        state.reference_context += "\n\n" + new_context
    else:
        state.reference_context = new_context

    # 同时追加为 injected_message，让当前阶段正在运行的 LLM 也能感知
    import uuid as _uuid

    state.injected_messages.append(
        {
            "signal": "inject_reference",
            "message_id": f"ref-{_uuid.uuid4().hex[:8]}",
            "content": new_context,
            "at_stage": state.stage.value,
            "rejected": False,
        }
    )

    # 持久化
    await save_meeting(
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


@router.get("/{meeting_id}/messages")
async def get_meeting_messages(meeting_id: str, limit: int = 500, before: int | None = None) -> dict[str, Any]:
    """获取会议历史发言（REST 兜底）

    前端历史消息恢复的唯一可靠途径：WebSocket 建连失败或页面刷新后，
    通过本接口拉取已持久化的发言记录，避免"会议页只剩空态"。

    - limit：返回条数上限（默认 500，按创建时间升序取前 N 条）
    - before：预留分页参数（暂不支持，占位兼容前端调用）
    """
    from app.dao.message_dao import list_messages

    rows = await list_messages(meeting_id)
    if limit and len(rows) > limit:
        rows = rows[:limit]
    return {"messages": rows, "count": len(rows)}


@router.get("")
async def list_meetings_with_status(
    q: str | None = None,
    limit: int = 20,
    offset: int = 0,
    tags: str | None = None,
    status: str | None = None,
    include_deleted: bool = False,
) -> dict[str, Any]:
    """列出会议（支持搜索、分页、标签过滤、状态过滤）

    查询参数：
    - q：按议题关键词搜索（模糊匹配）
    - limit：每页数量（默认 20）
    - offset：偏移量（默认 0）
    - tags：逗号分隔的标签列表，会议需同时拥有所有标签才匹配
    - status：逗号分隔的状态白名单（如 "running,paused"），命中其一即匹配
    - include_deleted：是否包含已软删除的会议（默认 false，仅管理员建议使用）

    返回 {meetings[], total, concurrent_limit, running_count}：
    - meetings：当前页的会议列表，每个含 meeting_id/topic/stage/status/created_at/is_running/tags
    - total：满足条件的总记录数
    - concurrent_limit：最大并发会议数
    - running_count：当前正在运行的会议数
    """
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
    status_list = [s.strip() for s in status.split(",") if s.strip()] if status else None
    result = await query_meetings(
        q=q, limit=limit, offset=offset, tags=tag_list, include_deleted=include_deleted, statuses=status_list
    )
    from app.orchestrator.instant import FLOW_STANDARD, normalize_mode

    items = []
    for m in result["items"]:
        mid = m["id"]
        is_running = mid in _running_tasks and not _running_tasks[mid].done()
        raw_flow = m.get("payload", {}).get("flow_plan", FLOW_STANDARD)
        # 从 payload 中提取消息数和 Agent 列表
        payload = m.get("payload", {}) or {}
        messages_list = payload.get("messages", [])
        role_configs = payload.get("role_configs", [])
        agents_summary = [
            {"id": rc.get("id", ""), "name": rc.get("name", ""), "role": rc.get("role", "")}
            for rc in role_configs
            if isinstance(rc, dict)
        ]
        items.append(
            {
                "meeting_id": mid,
                "topic": m["topic"],
                "stage": m["stage"],
                "status": m["status"],
                "created_at": m.get("created_at"),
                "is_running": is_running,
                "tags": m.get("tags", []),
                "flow_plan": normalize_mode(raw_flow),
                "message_count": len(messages_list) if isinstance(messages_list, list) else 0,
                "agents": agents_summary,
            }
        )
    return {
        "meetings": items,
        "total": result["total"],
        "concurrent_limit": MAX_CONCURRENT_MEETINGS,
        "running_count": sum(1 for t in _running_tasks.values() if not t.done()),
    }


async def _cleanup_semantic_index_quiet(meeting_id: str) -> None:
    """硬删除时清理会议级语义索引工作区（ADR-018 Phase C，D10/D7）。

    清理语义层（LightRAG 文档 + Qdrant 点位 + 文件目录）。失败只告警不阻断：
    数据库记录已删除，残留索引可由后续运维清理，不应让删除请求失败。
    语义层不可用（配置缺失）时 cleanup 内部即 no-op。
    """
    from app.observability.log_bus import log_bus
    from app.rag.lightrag_adapter import resolve_semantic_tenant_id
    from app.rag.semantic_ingest import cleanup_semantic_workspace

    try:
        await cleanup_semantic_workspace(resolve_semantic_tenant_id(), meeting_id=meeting_id)
    except Exception as e:
        log_bus.warning(
            f"语义索引清理失败（不阻断会议删除）: {meeting_id}",
            logger="routers.meetings",
            extra={"meeting_id": meeting_id, "error": f"{type(e).__name__}: {e}"},
        )


@router.delete("/{meeting_id}")
async def delete_meeting(meeting_id: str, request: Request, mode: str = "soft") -> dict[str, Any]:
    """删除会议

    - mode=soft（默认）：软删除，标记 status='deleted'，保留全部数据用于回归测试
    - mode=hard：硬删除，永久删除 meetings/messages/events 表记录，不可恢复
    - mode=restore：恢复软删除的会议

    运行中的会议不允许删除（返回 409）。
    """
    from app.auth_guard import assert_can_delete_meeting
    from app.context import get_request_id
    from app.observability.log_bus import log_bus

    # 检查会议是否存在
    meeting = await get_meeting(meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="会议不存在")

    # [SECURITY-FIX] 校验删除权限（支持 system admin / 创建者 / team owner / maintainer）
    await assert_can_delete_meeting(request, meeting)

    # 运行中的会议：先停止后台任务再删除（而非直接拒绝 409）
    # 旧版返回 409 导致卡在 running 的会议永远无法清理，用户无处下手。
    if meeting_id in _running_tasks and not _running_tasks[meeting_id].done():
        task = _running_tasks.pop(meeting_id, None)
        if task and not task.done():
            task.cancel()
            # 超时/取消后强制继续删除流程
            with contextlib.suppress(asyncio.TimeoutError, asyncio.CancelledError, Exception):
                await asyncio.wait_for(task, timeout=3.0)
        _run_locks.pop(meeting_id, None)

    # ADR-017 Phase 2 第 4 条：会议删除（软/硬）→ 释放绑定议题回池，
    # 避免议题永久卡在 in_progress。restore 不触发。失败仅记日志，不阻断删除。
    if meeting.get("issue_id"):
        from app.services.issue_service import release_issue

        try:
            await release_issue(str(meeting["issue_id"]))
        except Exception as e:
            log_bus.warning(
                f"删除会议释放议题失败（不影响删除）: {str(e)[:150]}",
                logger="routers.meetings",
                extra={"meeting_id": meeting_id, "issue_id": meeting["issue_id"]},
            )

    if mode == "soft":
        ok = await soft_delete_meeting(meeting_id)
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
        _run_locks.pop(meeting_id, None)
        return {"meeting_id": meeting_id, "deleted": True, "mode": "soft"}

    elif mode == "hard":
        ok = await hard_delete_meeting(meeting_id)
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
        # 清理操作回放录制文件（落盘截图）
        from app.services.recording_store import delete_meeting_recordings

        delete_meeting_recordings(meeting_id)
        # 清理语义索引工作区（ADR-018 Phase C：LightRAG 文档 + 文件目录）
        await _cleanup_semantic_index_quiet(meeting_id)
        _run_locks.pop(meeting_id, None)
        return {"meeting_id": meeting_id, "deleted": True, "mode": "hard"}

    elif mode == "restore":
        ok = await restore_meeting(meeting_id)
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
    meeting = await get_meeting(meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="会议不存在")
    tags = await get_meeting_tags(meeting_id)
    return {"meeting_id": meeting_id, "tags": tags}


@router.post("/{meeting_id}/tags")
async def add_tag(meeting_id: str, req: AddTagRequest) -> dict[str, Any]:
    """为会议添加标签"""
    meeting = await get_meeting(meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="会议不存在")
    tag = req.tag.strip()
    if not tag:
        raise HTTPException(status_code=400, detail="标签不能为空")
    added = await add_meeting_tag(meeting_id, tag)
    return {"meeting_id": meeting_id, "tag": tag, "added": added}


@router.delete("/{meeting_id}/tags/{tag}")
async def remove_tag(meeting_id: str, tag: str) -> dict[str, Any]:
    """移除会议的某个标签"""
    meeting = await get_meeting(meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="会议不存在")
    removed = await remove_meeting_tag(meeting_id, tag)
    if not removed:
        raise HTTPException(status_code=404, detail="标签不存在")
    return {"meeting_id": meeting_id, "tag": tag, "removed": True}


@router.post("/{meeting_id}/run", status_code=202)
async def run_meeting(meeting_id: str, request: Request) -> dict[str, Any]:
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
    from app.auth_guard import assert_meeting_access

    state = get_state(meeting_id)
    if state is None:
        raise HTTPException(status_code=404, detail="会议不存在，请先创建")

    # [SECURITY-FIX] 校验所有权（启动会议需要 owner 权限）
    assert_meeting_access(request, state, require_owner=True)

    # 409：已有后台任务在运行（防止重复启动）
    # [SECURITY-FIX] 使用锁防止 TOCTOU 竞态：锁覆盖"检查→创建任务→注册"整个临界区
    run_lock = _run_locks.setdefault(meeting_id, LazyLock())
    async with run_lock:
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

        # resume：从暂停态/失败态恢复（统一走 apply_signal，确保 _handle_resume 的一致逻辑）
        if state.status in (MeetingStatus.PAUSED, MeetingStatus.FAILED):
            state = apply_signal(state, "resume")
            set_state(state)

        # 启动后台任务执行完整六阶段流程
        from app.context import get_request_id
        from app.observability.log_bus import log_bus

        # [CON-07 修复] 立即推一个 run.started 事件，前端可立即看到反馈
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
        task = create_supervised_task(_run_meeting_bg(meeting_id), name=f"meeting-{meeting_id[:8]}")
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
        except Exception as e:
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
            # [P1-17 修复] 清理 _run_locks 防止内存泄漏。
            # 必须在第一个 await 之前同步执行，避免与新请求的 setdefault 竞态。
            _run_locks.pop(meeting_id, None)
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
                from app.tools.browser_tool import get_browser_pool

                await get_browser_pool().release_context(meeting_id)
            except Exception:
                pass
            # 保留沙箱服务容器，会议结束后用户仍可访问已部署服务
            # （服务生命周期由删除会议或 cleanup_all_services 管理）


@router.post("/{meeting_id}/control")
async def control_meeting(meeting_id: str, req: ControlRequest, request: Request) -> dict[str, Any]:
    """控场信号：pause / resume / abort / inject / loan"""
    from app.auth_guard import assert_meeting_access

    state = get_state(meeting_id)
    if state is None:
        raise HTTPException(status_code=404, detail="会议不存在")
    # [SECURITY-FIX] 校验所有权（控制会议需要 owner 权限）
    assert_meeting_access(request, state, require_owner=True)
    try:
        state = apply_signal(state, req.signal, req.payload)
        set_state(state)
        # 持久化
        await save_meeting(
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
            await bus.publish(
                make_event(
                    "borrow.approved_by_user",
                    meeting_id,
                    {
                        "meeting_id": meeting_id,
                        "request_id": req.payload.get("request_id", ""),
                        "pending_borrow_request": None,
                        "borrow_frozen": state.borrow_frozen,
                    },
                )
            )
        elif req.signal == "reject_borrow":
            await bus.publish(
                make_event(
                    "borrow.rejected_by_user",
                    meeting_id,
                    {
                        "meeting_id": meeting_id,
                        "request_id": req.payload.get("request_id", ""),
                        "pending_borrow_request": None,
                        "reason": req.payload.get("reason", ""),
                        "borrow_frozen": state.borrow_frozen,
                    },
                )
            )
        elif req.signal == "freeze_borrow":
            await bus.publish(
                make_event(
                    "borrow.frozen",
                    meeting_id,
                    {
                        "meeting_id": meeting_id,
                        "pending_borrow_request": None,
                        "borrow_frozen": True,
                    },
                )
            )
        elif req.signal == "abort":
            # [SECURITY-FIX] abort 时立即清理沙箱长期服务容器（正常 DONE 保留，abort 不留）
            try:
                from app.sandbox import stop_service

                await stop_service(meeting_id)
            except Exception:
                pass
            # ADR-017 Phase 2 第 4 条：会议中止 → 释放议题回池（in_progress → open）。
            # 失败仅记日志，不阻断 abort 信号本身。
            if state.issue_id:
                from app.observability.log_bus import log_bus as _log_bus
                from app.services.issue_service import release_issue

                try:
                    await release_issue(state.issue_id)
                except Exception as e:
                    _log_bus.warning(
                        f"中止会议释放议题失败（不影响 abort）: {str(e)[:150]}",
                        logger="routers.meetings",
                        extra={"meeting_id": meeting_id, "issue_id": state.issue_id},
                    )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
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
        state = await load_or_create(meeting_id, "")
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
        state = await load_or_create(meeting_id, "")
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
        "degradation_warnings_count": len(state.degradation_warnings) if state.degradation_warnings else 0,
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
        state = await load_or_create(meeting_id, "")
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
        state = await load_or_create(meeting_id, "")
        if state.topic == "":
            # 恢复失败，返回 404
            raise HTTPException(status_code=404, detail="会议不存在")

    events = await bus.replay(meeting_id, from_seq)
    return {
        "meeting_id": meeting_id,
        "from_seq": from_seq,
        "last_seq": await bus.last_seq(meeting_id),
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
    state = await load_or_create(meeting_id, "")
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
    state = await load_or_create(meeting_id, "")
    if state.topic == "":
        raise HTTPException(status_code=404, detail="会议不存在")

    # 1. LLM trace
    trace_calls = [c.model_dump(mode="json") for c in state.llm_trace.calls]
    trace_events = [e.model_dump(mode="json") for e in state.llm_trace.trace_events]

    # 2. 事件历史
    events = await bus.replay(meeting_id, from_seq=0)
    event_dicts = [e.model_dump(mode="json") for e in events]
    degradation_events = [
        e
        for e in event_dicts
        if e.get("type") in ("produce.degradation", "meeting.fallback_warning", "intermediate.degradation")
    ]

    # 3. 成本记录（从数据库查）
    cost_records: list[dict[str, Any]] = []
    try:
        async with async_session_factory() as session:
            result = await session.execute(
                select(CostRecordModel)
                .where(CostRecordModel.meeting_id == meeting_id)
                .order_by(CostRecordModel.created_at.asc())
            )
            for row in result.scalars().all():
                cost_records.append(
                    {
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
                    }
                )
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
        "borrowed_agents_detail": list(state.borrowed_agents) if state.borrowed_agents else [],
        "conclusion_chain_length": len(state.conclusion_chain.conclusions),
        "quality_score": state.quality_score,
        "quality_feedback": state.quality_feedback,
        "quality_evaluation": state.quality_evaluation,
        "iteration_history": list(state.iteration_history),
        "degradation_warnings": list(state.degradation_warnings) if state.degradation_warnings else [],
        "auto_iterate": state.auto_iterate,
        "max_iterations": state.max_iterations,
        "iteration_count": state.iteration_count,
        "drift": {
            "total_checks": len(state.drift_log),
            "drift_detected": drift_count,
        },
    }

    return {
        "meeting_id": meeting_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "meeting": state_snapshot,
        "sections": state.snapshot_sections() if hasattr(state, "snapshot_sections") else None,
        "trace": {
            "summary": trace_summary,
            "calls": trace_calls,
            "trace_events": trace_events,
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
            # 质量门禁摘要
            "quality_score": state.quality_score,
            "quality_should_iterate": (state.quality_evaluation or {}).get("should_iterate", False),
            "quality_hard_failures": (state.quality_evaluation or {}).get("hard_failures", []),
            "iteration_count": state.iteration_count,
            "borrowed_agents_count": len(state.borrowed_agents) if state.borrowed_agents else 0,
        },
    }


@router.get("/{meeting_id}/attachments")
async def list_attachments(meeting_id: str) -> dict[str, Any]:
    """列出会议产出的附件文件（沙箱执行产出的 PNG/CSV/MD 等）"""
    state = get_state(meeting_id)
    if state is None:
        state = await load_or_create(meeting_id, "")
        if state.topic == "":
            raise HTTPException(status_code=404, detail="会议不存在")
    attachments = (state.artifact or {}).get("attachments", [])
    return {"meeting_id": meeting_id, "attachments": attachments, "count": len(attachments)}


@router.get("/{meeting_id}/attachments/{filename}")
async def download_attachment(meeting_id: str, filename: str):
    """下载附件文件"""
    from pathlib import Path

    from fastapi.responses import FileResponse

    from app.config import settings

    state = get_state(meeting_id)
    if state is None:
        state = await load_or_create(meeting_id, "")
        if state.topic == "":
            raise HTTPException(status_code=404, detail="会议不存在")
    attachments = (state.artifact or {}).get("attachments", [])
    target = next((a for a in attachments if a.get("filename") == filename), None)
    if target is None:
        raise HTTPException(status_code=404, detail="附件不存在")
    # path 可能是相对于 workspace_root 的路径（如 "mtg-xxx/app.py"）或绝对路径
    raw_path = Path(target["path"])
    file_path = raw_path if raw_path.is_absolute() else Path(settings.workspace_root) / raw_path
    # 安全检查：防止路径遍历
    try:
        file_path = file_path.resolve()
        ws_root = Path(settings.workspace_root).resolve()
        if not str(file_path).startswith(str(ws_root)):
            raise HTTPException(status_code=403, detail="非法路径")
    except (OSError, ValueError):
        raise HTTPException(status_code=404, detail="附件路径无效") from None
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="附件文件已丢失")
    return FileResponse(
        str(file_path),
        filename=filename,
        media_type="application/octet-stream",
    )


@router.get("/{meeting_id}/recordings/{filename}")
async def download_recording(meeting_id: str, filename: str):
    """下载会议操作回放截图（PNG）。

    操作截图已落盘到录制存储，events 只存 filename 引用（screenshot_ref），
    前端通过本端点拉取图片（带鉴权），避免大 base64 进 events/PostgreSQL。
    """
    from fastapi.responses import FileResponse

    from app.services.recording_store import resolve_path

    # 会议存在性校验（与 events/attachments 端点一致的恢复逻辑）
    state = get_state(meeting_id)
    if state is None:
        state = await load_or_create(meeting_id, "")
        if state.topic == "":
            raise HTTPException(status_code=404, detail="会议不存在")

    path = resolve_path(meeting_id, filename)
    if path is None:
        raise HTTPException(status_code=404, detail="录制文件不存在")
    return FileResponse(str(path), media_type="image/png")


@router.get("/skills/list")
async def list_skills():
    """列出所有已加载的Agent Skills（供调试/前端展示）"""
    from app.agents.skills import list_skills as _list_skills

    return {"skills": _list_skills()}


# ---------- LLM 模型管理端点 ----------


@router.get("/llm/providers")
async def get_llm_providers():
    """列出所有已注册的LLM厂商及其能力"""
    from app.llm_providers import list_providers

    return {"providers": list_providers()}


@router.post("/llm/models")
async def query_llm_models(req: QueryModelsRequest):
    """查询可用模型列表（POST body 传递敏感参数，避免 API Key 泄露到 URL/日志/Referer）

    - provider: 厂商ID，为空则使用默认
    - api_key: 自定义API Key（BYOK），为空则使用环境变量配置
    - base_url: 自定义Base URL（custom厂商时使用）
    - refresh: 是否强制刷新缓存
    """
    from app.llm_providers import RECOMMENDED_MODELS, _is_qwen_llm, categorize_models, fetch_models

    models = await fetch_models(
        provider_id=req.provider,
        api_key=req.api_key,
        base_url=req.base_url,
        use_cache=not req.refresh,
    )
    # 过滤 Qwen LLM（不支持 response_format: json_object，保留向量模型）
    filtered_models = [m for m in models if not _is_qwen_llm(m.get("id", ""))]
    categories = categorize_models(filtered_models)
    return {
        "models": filtered_models,
        "categories": categories,
        "recommended": RECOMMENDED_MODELS,
        "total": len(filtered_models),
    }


@router.post("/llm/balance")
async def query_llm_balance(req: QueryBalanceRequest):
    """查询LLM账户余额（POST body 传递敏感参数，避免 API Key 泄露到 URL/日志/Referer）

    - provider: 厂商ID
    - api_key: 自定义API Key，为空则使用环境变量
    """
    from app.llm_providers import fetch_balance

    result = await fetch_balance(provider_id=req.provider, api_key=req.api_key, base_url=req.base_url)
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
        state = await load_or_create(meeting_id, "")
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

            create_supervised_task(
                save_api_key(
                    provider=req.provider_id,
                    api_key=req.api_key,
                    base_url=req.base_url or "",
                    is_default=True,
                ),
                name=f"save-key-{req.provider_id}",
            )
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
        "has_custom_key": bool(api_key)
        and api_key != __import__("app.config", fromlist=["settings"]).settings.llm_api_key,
        "is_running": state.status not in (MeetingStatus.DONE,),
    }


# ---------- API Key 持久化管理 ----------


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


# ---- 议题润色 ----


class PolishRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)


@router.post("/polish-topic")
async def polish_topic(req: PolishRequest, request: Request) -> dict[str, str]:
    """使用 LLM 润色议题描述，使其更清晰、更结构化。"""
    from app.agents.llm import get_llm
    from app.auth_guard import get_current_user

    _uid, _username, _role = get_current_user(request)

    text = req.text.strip()
    if len(text) < 3:
        return {"polished": text}

    prompt = (
        "你是一个议题优化助手。请将用户输入的讨论议题/问题润色得更加清晰、结构化、便于多 Agent 团队讨论。\n"
        "要求：\n"
        "1. 保留用户原意，不要添加用户没提到的内容\n"
        "2. 如果议题模糊，将其明确化为具体可讨论的问题\n"
        "3. 如果涉及多个方面，用简洁的分点形式表达（用数字序号）\n"
        "4. 语言简洁，控制在 200 字以内\n"
        "5. 直接输出润色后的内容，不要加任何前缀或解释\n\n"
        f"用户输入：\n{text}\n\n润色后："
    )

    try:
        llm = get_llm()
        polished = await llm.complete_text(prompt, temperature=0.3)
        polished = polished.strip().strip('"').strip("'").strip()
        if not polished or len(polished) < 2:
            polished = text
        return {"polished": polished}
    except Exception:
        # 如果 LLM 调用失败，返回原文（不阻塞用户）
        return {"polished": text}
