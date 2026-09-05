"""议题 CRUD（ADR-017 Phase 2）。

议题是项目下的迭代单元。两条入口（ADR-017 D7）：
- source=user：用户手动入池；
- source=meeting：会议候选议题经用户确认后入池。

状态机流转的合法性由服务层（services/issue_service.py）校验；
本 DAO 只做数据读写，``transition_status`` 提供条件更新原子性
（WHERE status IN expected，防并发竞争下的非法流转）。

多租户：所有查询自动附加 tenant_id 过滤；写入时自动填充当前租户 ID
（对齐 artifact_dao.py 模式，见 docs/pitfalls.md P8）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, select, update

from app.db.engine import async_session_factory
from app.db.models import IssueModel
from app.tenants import current_tenant_id
from app.tenants.dao import tenant_filter_expr

# 合法入口取值（ADR-017 D7）
ISSUE_SOURCES = ("user", "meeting")

# 可更新字段白名单（防越权改 id/tenant_id/project_id/created_at）
_UPDATABLE_FIELDS = (
    "title",
    "body",
    "status",
    "priority",
    "assigned_meeting_id",
    "resolution_artifact_id",
)


def _iso(v: Any) -> Any:
    """datetime → ISO 字符串（保持与 artifact_dao 相同的返回契约）。"""
    return v.isoformat() if isinstance(v, datetime) else v


def _issue_to_dict(row: IssueModel) -> dict[str, Any]:
    """ORM 行 → dict（时间戳转 ISO 字符串）。"""
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "project_id": row.project_id,
        "title": row.title,
        "body": row.body,
        "source": row.source,
        "source_meeting_id": row.source_meeting_id,
        "status": row.status,
        "priority": row.priority,
        "assigned_meeting_id": row.assigned_meeting_id,
        "resolution_artifact_id": row.resolution_artifact_id,
        "created_by": row.created_by,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


async def create_issue(
    project_id: str,
    title: str,
    source: str,
    body: str | None = None,
    source_meeting_id: str | None = None,
    priority: int = 50,
    created_by: str | None = None,
) -> dict[str, Any]:
    """创建一条议题。自动填充当前 tenant_id。

    Args:
        source: 入口，必须属于 ``ISSUE_SOURCES``（user|meeting）。

    Raises:
        ValueError: source 非法。
    """
    if source not in ISSUE_SOURCES:
        raise ValueError(f"非法议题入口: {source}（合法值: {ISSUE_SOURCES}）")
    tid = current_tenant_id()
    row = IssueModel(
        project_id=project_id,
        title=title,
        body=body,
        source=source,
        source_meeting_id=source_meeting_id,
        priority=priority,
        created_by=created_by,
    )
    if tid is not None:
        row.tenant_id = tid
    async with async_session_factory() as session:
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return _issue_to_dict(row)


async def get_issue(issue_id: str) -> dict[str, Any] | None:
    """取单条议题（自动租户过滤；跨租户访问返回 None）。"""
    cond = tenant_filter_expr(IssueModel.tenant_id)
    async with async_session_factory() as session:
        result = await session.execute(select(IssueModel).where(IssueModel.id == issue_id, cond))
        row = result.scalars().first()
        if row is None:
            return None
        return _issue_to_dict(row)


async def list_issues(
    project_id: str | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """分页查询议题（租户过滤，最新在上——UI 红线）。

    Args:
        project_id: 按项目过滤（None=全部可见议题）。
        status: 按状态过滤（None=全部状态）。
    """
    cond = tenant_filter_expr(IssueModel.tenant_id)
    conds: list[Any] = [cond]
    if project_id is not None:
        conds.append(IssueModel.project_id == project_id)
    if status is not None:
        conds.append(IssueModel.status == status)
    async with async_session_factory() as session:
        total = (await session.execute(select(func.count()).select_from(IssueModel).where(*conds))).scalar_one()
        result = await session.execute(
            select(IssueModel).where(*conds).order_by(IssueModel.created_at.desc()).limit(limit).offset(offset)
        )
        rows = result.scalars().all()
        return {"items": [_issue_to_dict(r) for r in rows], "total": int(total)}


async def update_issue_fields(issue_id: str, fields: dict[str, Any]) -> dict[str, Any] | None:
    """更新议题字段（白名单过滤 + 租户过滤）。

    不做状态机校验（服务层职责）。

    Returns:
        更新后的议题 dict；议题不存在/跨租户返回 None。
    """
    updates = {k: v for k, v in fields.items() if k in _UPDATABLE_FIELDS}
    cond = tenant_filter_expr(IssueModel.tenant_id)
    async with async_session_factory() as session:
        result = await session.execute(select(IssueModel).where(IssueModel.id == issue_id, cond))
        row = result.scalars().first()
        if row is None:
            return None
        for key, value in updates.items():
            setattr(row, key, value)
        await session.commit()
        await session.refresh(row)
        return _issue_to_dict(row)


async def transition_status(
    issue_id: str,
    expected_statuses: tuple[str, ...],
    new_status: str,
    extra_fields: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """条件状态流转（原子）：仅当当前状态属于 expected_statuses 时更新。

    用 UPDATE ... WHERE status IN (...) 的条件更新防并发竞争：
    两个并发流转只有一个能命中。

    Args:
        extra_fields: 随流转一并更新的白名单字段（如 assigned_meeting_id）。

    Returns:
        流转后的议题 dict；议题不存在/跨租户/当前状态不在期望集合返回 None。
    """
    updates: dict[str, Any] = {"status": new_status}
    if extra_fields:
        updates.update({k: v for k, v in extra_fields.items() if k in _UPDATABLE_FIELDS})
    cond = tenant_filter_expr(IssueModel.tenant_id)
    stmt = (
        update(IssueModel)
        .where(
            IssueModel.id == issue_id,
            IssueModel.status.in_(list(expected_statuses)),
            cond,
        )
        .values(**updates)
        .returning(IssueModel)
    )
    async with async_session_factory() as session:
        result = await session.execute(stmt)
        row = result.scalars().first()
        await session.commit()
        if row is None:
            return None
        return _issue_to_dict(row)


async def delete_issue(issue_id: str) -> bool:
    """删除议题（租户过滤）。

    会议侧的 issue_id 外键为 SET NULL（历史会议保留，关联置空）。

    Returns:
        是否实际删除了记录（不存在/跨租户返回 False）。
    """
    cond = tenant_filter_expr(IssueModel.tenant_id)
    async with async_session_factory() as session:
        result = await session.execute(select(IssueModel).where(IssueModel.id == issue_id, cond))
        row = result.scalars().first()
        if row is None:
            return False
        await session.delete(row)
        await session.commit()
        return True


async def unbind_meeting(meeting_id: str) -> None:
    """会议删除/失效时解绑：assigned_meeting_id 指向该会议的议题置 NULL。

    不改议题状态（状态流转是服务层语义；此处仅维护外键一致性）。
    """
    cond = tenant_filter_expr(IssueModel.tenant_id)
    async with async_session_factory() as session:
        await session.execute(
            update(IssueModel)
            .where(IssueModel.assigned_meeting_id == meeting_id, cond)
            .values(assigned_meeting_id=None)
        )
        await session.commit()


async def bulk_get_by_project(project_ids: list[str]) -> dict[str, int]:
    """统计多个项目的议题总数（项目列表页展示用）。"""
    cond = tenant_filter_expr(IssueModel.tenant_id)
    if not project_ids:
        return {}
    async with async_session_factory() as session:
        rows = (
            await session.execute(
                select(IssueModel.project_id, func.count())
                .where(IssueModel.project_id.in_(project_ids), cond)
                .group_by(IssueModel.project_id)
            )
        ).all()
    return {pid: int(cnt) for pid, cnt in rows}


__all__ = [
    "ISSUE_SOURCES",
    "bulk_get_by_project",
    "create_issue",
    "delete_issue",
    "get_issue",
    "list_issues",
    "transition_status",
    "unbind_meeting",
    "update_issue_fields",
]
