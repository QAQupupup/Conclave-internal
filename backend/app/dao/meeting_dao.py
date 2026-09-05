"""会议 CRUD 与批量删除。

包含会议的增删改查、批量删除（软/硬删除）、崩溃恢复以及产出摘要提取。
batch_delete_meetings 内部调用本文件内的 soft_delete_meeting / hard_delete_meeting，
无需跨文件 import。

已迁移到 SQLAlchemy ORM：显式 select / pg_insert upsert / update / delete，
不使用手写 SQL 字符串和 relationship（见 docs/sql-development-rules.md）。

多租户：所有查询自动附加 tenant_id 过滤；写入时自动填充当前租户 ID。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import utcnow
from app.db.engine import async_session_factory
from app.db.models import EventModel, MeetingModel, MeetingTagModel, MessageModel
from app.tenants import current_tenant_id
from app.tenants.dao import tenant_filter_expr


def _iso(v: Any) -> Any:
    """datetime → ISO 字符串（保持历史 TEXT 返回契约）。"""
    return v.isoformat() if isinstance(v, datetime) else v


def _parse_dt(v: Any) -> datetime:
    """ISO 字符串 / datetime → tz-aware datetime；非法或空值回退 utcnow。"""
    if isinstance(v, datetime):
        return v if v.tzinfo is not None else v.replace(tzinfo=timezone.utc)
    if isinstance(v, str) and v:
        try:
            dt = datetime.fromisoformat(v)
            return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return utcnow()


def _meeting_to_dict(row: MeetingModel) -> dict[str, Any]:
    """ORM 行 → dict，保持历史返回契约（created_at 转 ISO 字符串，payload 反序列化）。"""
    return {
        "id": row.id,
        "topic": row.topic,
        "owner_username": row.owner_username,
        "status": row.status,
        "stage": row.stage,
        "created_at": _iso(row.created_at),
        "payload": json.loads(row.payload or "{}"),
        "schema_version": row.schema_version,
        "tenant_id": row.tenant_id,
        # ADR-017 Phase 2：归属项目/议题（删除挂钩据此释放议题；前端据此展示归属）
        "project_id": row.project_id,
        "issue_id": row.issue_id,
    }


async def save_meeting(
    meeting_id: str,
    topic: str,
    status: str,
    stage: str,
    created_at: datetime,
    payload: dict[str, Any],
    owner_username: str | None = None,
    project_id: str | None = None,
    issue_id: str | None = None,
    session: AsyncSession | None = None,
) -> None:
    """upsert 会议记录，payload 存 JSON。自动填充当前 tenant_id。

    Args:
        project_id: ADR-017 Phase 2 归属项目（仅创建时传入；None 时不触碰已有值）。
        issue_id: ADR-017 Phase 2 归属议题（同上）。
        session: 可选外部 session。传入时仅执行 SQL 不 commit（由调用方控制事务）；
                 不传时创建独立 session 并 commit（向后兼容）。
    """
    tid = current_tenant_id()  # None 表示系统租户

    values: dict[str, Any] = {
        "id": meeting_id,
        "topic": topic,
        "status": status,
        "stage": stage,
        "created_at": _parse_dt(created_at),
        "payload": json.dumps(payload, ensure_ascii=False, default=str),
    }
    if owner_username is not None:
        values["owner_username"] = owner_username
    if project_id is not None:
        values["project_id"] = project_id
    if issue_id is not None:
        values["issue_id"] = issue_id
    if tid is not None:
        values["tenant_id"] = tid

    insert_stmt = pg_insert(MeetingModel).values(**values)
    set_: dict[str, Any] = {
        "topic": insert_stmt.excluded.topic,
        "status": insert_stmt.excluded.status,
        "stage": insert_stmt.excluded.stage,
        "payload": insert_stmt.excluded.payload,
    }
    if owner_username is not None:
        set_["owner_username"] = insert_stmt.excluded.owner_username
    if project_id is not None:
        set_["project_id"] = insert_stmt.excluded.project_id
    if issue_id is not None:
        set_["issue_id"] = insert_stmt.excluded.issue_id
    if tid is not None:
        # COALESCE: 已有值保留，无值则回填
        set_["tenant_id"] = func.coalesce(MeetingModel.tenant_id, insert_stmt.excluded.tenant_id)

    stmt = insert_stmt.on_conflict_do_update(index_elements=["id"], set_=set_)

    if session is not None:
        await session.execute(stmt)
    else:
        async with async_session_factory() as session:
            await session.execute(stmt)
            await session.commit()


async def get_meeting(meeting_id: str) -> dict[str, Any] | None:
    """取单条会议记录（自动租户过滤）"""
    cond = tenant_filter_expr(MeetingModel.tenant_id)
    async with async_session_factory() as session:
        result = await session.execute(select(MeetingModel).where(MeetingModel.id == meeting_id, cond))
        row = result.scalars().first()
        if row is None:
            return None
        return _meeting_to_dict(row)


async def list_meetings(include_deleted: bool = False) -> list[dict[str, Any]]:
    """列出全部会议。默认排除软删除（status='deleted'）的记录。自动租户过滤。"""
    cond = tenant_filter_expr(MeetingModel.tenant_id)
    conds: list[Any] = [cond]
    if not include_deleted:
        conds.append(MeetingModel.status != "deleted")
    async with async_session_factory() as session:
        result = await session.execute(select(MeetingModel).where(*conds).order_by(MeetingModel.created_at.desc()))
        rows = result.scalars().all()
        return [_meeting_to_dict(row) for row in rows]


async def query_meetings(
    q: str | None = None,
    limit: int = 20,
    offset: int = 0,
    tags: list[str] | None = None,
    include_deleted: bool = False,
    statuses: list[str] | None = None,
) -> dict[str, Any]:
    """搜索+分页+标签+状态过滤查询会议。

    返回 {items, total}：
    - items：当前页的会议列表（含 tags 字段）
    - total：满足条件的总记录数（用于分页计算）

    statuses：状态白名单（如 ["running", "paused"]），命中其一即匹配；
    None/空列表表示不过滤。
    """
    cond = tenant_filter_expr(MeetingModel.tenant_id)
    conds: list[Any] = [cond]

    if not include_deleted:
        conds.append(MeetingModel.status != "deleted")

    if q:
        conds.append(MeetingModel.topic.like(f"%{q}%"))

    if statuses:
        conds.append(MeetingModel.status.in_(statuses))

    if tags:
        # 交集过滤：会议需同时拥有所有指定标签
        conds.append(
            MeetingModel.id.in_(
                select(MeetingTagModel.meeting_id)
                .where(MeetingTagModel.tag.in_(tags))
                .group_by(MeetingTagModel.meeting_id)
                .having(func.count(func.distinct(MeetingTagModel.tag)) == len(tags))
            )
        )

    async with async_session_factory() as session:
        # 总数
        total = (await session.execute(select(func.count()).select_from(MeetingModel).where(*conds))).scalar_one()

        # 分页查询
        result = await session.execute(
            select(MeetingModel).where(*conds).order_by(MeetingModel.created_at.desc()).limit(limit).offset(offset)
        )
        rows = result.scalars().all()

        items: list[dict[str, Any]] = []
        for row in rows:
            d = _meeting_to_dict(row)
            # 查询该会议的标签（meeting_id 已受外层租户过滤保护）
            tag_result = await session.execute(
                select(MeetingTagModel.tag)
                .where(MeetingTagModel.meeting_id == d["id"])
                .order_by(MeetingTagModel.tag.asc())
            )
            d["tags"] = list(tag_result.scalars().all())
            items.append(d)

        return {"items": items, "total": total}


async def get_meetings_by_ids(meeting_ids: list[str]) -> list[dict[str, Any]]:
    """批量获取会议记录（用于历史会议引用）。

    返回已完成的会议摘要列表，包含 topic、stage、status、artifact 摘要。
    不包含运行中的会议（status='running'），也不包含已删除的会议。
    """
    if not meeting_ids:
        return []
    cond = tenant_filter_expr(MeetingModel.tenant_id)
    async with async_session_factory() as session:
        result = await session.execute(
            select(MeetingModel)
            .where(
                MeetingModel.id.in_(meeting_ids),
                cond,
                MeetingModel.status.notin_(["deleted", "running"]),
            )
            .order_by(MeetingModel.created_at.desc())
        )
        rows = result.scalars().all()
        out: list[dict[str, Any]] = []
        for row in rows:
            d = _meeting_to_dict(row)
            payload = d["payload"]
            d["clarified_topic"] = payload.get("clarified_topic", d["topic"])
            d["key_questions"] = payload.get("key_questions", [])
            d["artifact"] = payload.get("artifact")
            d["decision_record"] = payload.get("decision_record")
            d["flow_plan"] = payload.get("flow_plan", "full")
            # 提取产出摘要
            art = d["artifact"]
            if art:
                d["artifact_summary"] = _extract_artifact_summary(art)
            out.append(d)
        return out


def _extract_artifact_summary(artifact: dict[str, Any] | None) -> str:
    """从 artifact 中提取简洁摘要文本"""
    if not artifact:
        return "（无产出）"
    parts = []
    if artifact.get("title"):
        parts.append(artifact["title"])
    if artifact.get("overview"):
        parts.append(artifact["overview"])
    if artifact.get("summary"):
        parts.append(artifact["summary"])
    if artifact.get("executive_summary"):
        parts.append(artifact["executive_summary"])
    if artifact.get("verdict"):
        parts.append(artifact["verdict"])
    if not parts:
        # 尝试从 design_doc 等嵌套结构中提取
        for key in ("design_doc", "comprehensive", "research_report", "business_report"):
            inner = artifact.get(key, {})
            if isinstance(inner, dict):
                if inner.get("title"):
                    parts.append(inner["title"])
                if inner.get("overview"):
                    parts.append(inner["overview"])
                if inner.get("summary"):
                    parts.append(inner["summary"])
                if parts:
                    break
    return " | ".join(parts) if parts else "（无产出摘要）"


async def recover_running_meetings() -> list[dict[str, Any]]:
    """查找状态为 running 的会议（用于崩溃恢复）。
    调用方应使用 create_system_tenant_ctx() 包裹以跨租户恢复。"""
    cond = tenant_filter_expr(MeetingModel.tenant_id)
    async with async_session_factory() as session:
        result = await session.execute(select(MeetingModel).where(MeetingModel.status == "running", cond))
        rows = result.scalars().all()
        return [_meeting_to_dict(row) for row in rows]


async def soft_delete_meeting(meeting_id: str) -> bool:
    """软删除会议：将 status 标记为 'deleted'，保留全部数据用于回归。
    返回是否找到了记录并更新。自动租户过滤。"""
    cond = tenant_filter_expr(MeetingModel.tenant_id)
    async with async_session_factory() as session:
        # 先读取当前 payload
        result = await session.execute(select(MeetingModel.payload).where(MeetingModel.id == meeting_id, cond))
        row = result.scalars().first()
        if row is None:
            return False
        payload = json.loads(row or "{}")
        payload["_deleted_at"] = datetime.now().isoformat()
        await session.execute(
            update(MeetingModel)
            .where(MeetingModel.id == meeting_id, cond)
            .values(status="deleted", payload=json.dumps(payload, ensure_ascii=False, default=str))
        )
        await session.commit()
        return True


async def hard_delete_meeting(meeting_id: str) -> bool:
    """硬删除会议：永久删除 meetings、messages、events 表中该会议的全部记录。
    不可恢复，用于彻底清理。返回是否删除了主记录。自动租户过滤。"""
    cond = tenant_filter_expr(MeetingModel.tenant_id)
    async with async_session_factory() as session:
        # 先检查主记录是否存在（带租户过滤）
        result = await session.execute(select(MeetingModel.id).where(MeetingModel.id == meeting_id, cond))
        row = result.scalars().first()
        if row is None:
            return False
        # 子表通过 meeting_id 关联，天然受限于当前会议（已通过租户校验）
        await session.execute(delete(MeetingTagModel).where(MeetingTagModel.meeting_id == meeting_id))
        await session.execute(delete(MessageModel).where(MessageModel.meeting_id == meeting_id))
        await session.execute(delete(EventModel).where(EventModel.meeting_id == meeting_id))
        await session.execute(delete(MeetingModel).where(MeetingModel.id == meeting_id, cond))
        await session.commit()
        return True


async def restore_meeting(meeting_id: str) -> bool:
    """恢复软删除的会议：将 status 从 'deleted' 恢复为 'aborted'。
    返回是否找到了记录并恢复。自动租户过滤。"""
    cond = tenant_filter_expr(MeetingModel.tenant_id)
    async with async_session_factory() as session:
        result = await session.execute(
            select(MeetingModel.payload).where(
                MeetingModel.id == meeting_id,
                MeetingModel.status == "deleted",
                cond,
            )
        )
        row = result.scalars().first()
        if row is None:
            return False
        payload = json.loads(row or "{}")
        payload.pop("_deleted_at", None)
        await session.execute(
            update(MeetingModel)
            .where(MeetingModel.id == meeting_id, cond)
            .values(status="aborted", payload=json.dumps(payload, ensure_ascii=False, default=str))
        )
        await session.commit()
        return True


async def batch_delete_meetings(meeting_ids: list[str], mode: str = "soft") -> dict[str, list[str]]:
    """批量删除会议。

    - mode=soft：软删除，保留数据
    - mode=hard：硬删除，永久删除

    返回 {deleted: [...], failed: [...]}。
    running 状态的会议会被跳过并记入 failed。
    """
    deleted: list[str] = []
    failed: list[str] = []
    for mid in meeting_ids:
        if mode == "soft":
            ok = await soft_delete_meeting(mid)
        elif mode == "hard":
            ok = await hard_delete_meeting(mid)
        else:
            failed.append(mid)
            continue
        if ok:
            deleted.append(mid)
        else:
            failed.append(mid)
    return {"deleted": deleted, "failed": failed}
