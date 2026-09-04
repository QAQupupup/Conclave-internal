"""产物 CRUD 与幂等发布（ADR-017 Phase 1）。

产物是会议产出的一等公民实体。本 DAO 提供：
- publish_artifact：幂等写入（UNIQUE (meeting_id, type, version) 冲突时更新）
- next_version：查询同会议同类型的下一版本号与上一版本 id（版本链）
- get_artifact / get_artifacts_by_ids / list_artifacts：租户隔离查询

多租户：所有查询自动附加 tenant_id 过滤；写入时自动填充当前租户 ID
（对齐 meeting_dao.py 模式，见 docs/pitfalls.md P8）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import async_session_factory
from app.db.models import ArtifactModel
from app.tenants import current_tenant_id
from app.tenants.dao import tenant_filter_expr


def _iso(v: Any) -> Any:
    """datetime → ISO 字符串（保持与 meeting_dao 相同的返回契约）。"""
    return v.isoformat() if isinstance(v, datetime) else v


def _artifact_to_dict(row: ArtifactModel) -> dict[str, Any]:
    """ORM 行 → dict（created_at 转 ISO 字符串）。"""
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "meeting_id": row.meeting_id,
        "project_id": row.project_id,
        "type": row.type,
        "title": row.title,
        "summary": row.summary,
        "content": row.content,
        "content_ref": row.content_ref,
        "version": row.version,
        "parent_id": row.parent_id,
        "source_artifact_ids": row.source_artifact_ids or [],
        "created_by": row.created_by,
        "created_at": _iso(row.created_at),
    }


async def next_version(meeting_id: str, artifact_type: str) -> tuple[int, str | None]:
    """查询同会议同类型产物的下一版本号与当前最新版本的 id。

    Returns:
        (next_version_number, latest_artifact_id)：
        无历史产物时为 (1, None)；有则为 (max+1, 最新版 id)（供 parent_id）。
    """
    async with async_session_factory() as session:
        result = await session.execute(
            select(ArtifactModel.id, ArtifactModel.version)
            .where(ArtifactModel.meeting_id == meeting_id, ArtifactModel.type == artifact_type)
            .order_by(ArtifactModel.version.desc())
            .limit(1)
        )
        row = result.first()
        if row is None:
            return 1, None
        return int(row.version) + 1, str(row.id)


async def publish_artifact(
    meeting_id: str,
    artifact_type: str,
    version: int,
    title: str | None = None,
    summary: str | None = None,
    content: dict[str, Any] | None = None,
    content_ref: str | None = None,
    parent_id: str | None = None,
    source_artifact_ids: list[str] | None = None,
    project_id: str | None = None,
    created_by: str | None = None,
    session: AsyncSession | None = None,
) -> dict[str, Any]:
    """幂等发布一条产物（ADR-017 D2）。

    冲突键 (meeting_id, type, version) 已存在时执行更新（重放安全）。
    自动填充当前 tenant_id。

    Args:
        session: 可选外部 session。传入时仅执行 SQL 不 commit（由调用方控制事务）。

    Returns:
        发布后的产物 dict（含最终 id）。
    """
    tid = current_tenant_id()
    values: dict[str, Any] = {
        "meeting_id": meeting_id,
        "type": artifact_type,
        "version": version,
        "title": title,
        "summary": summary,
        "content": content,
        "content_ref": content_ref,
        "parent_id": parent_id,
        "source_artifact_ids": source_artifact_ids or [],
        "project_id": project_id,
        "created_by": created_by,
    }
    if tid is not None:
        values["tenant_id"] = tid

    insert_stmt = pg_insert(ArtifactModel).values(**values)
    # 冲突重放：刷新内容字段（幂等可重试）；tenant_id 用 COALESCE 保留已有值
    set_: dict[str, Any] = {
        "title": insert_stmt.excluded.title,
        "summary": insert_stmt.excluded.summary,
        "content": insert_stmt.excluded.content,
        "content_ref": insert_stmt.excluded.content_ref,
        "parent_id": insert_stmt.excluded.parent_id,
        "source_artifact_ids": insert_stmt.excluded.source_artifact_ids,
        "project_id": insert_stmt.excluded.project_id,
        "created_by": insert_stmt.excluded.created_by,
    }
    if tid is not None:
        set_["tenant_id"] = func.coalesce(ArtifactModel.tenant_id, insert_stmt.excluded.tenant_id)
    stmt = insert_stmt.on_conflict_do_update(
        index_elements=["meeting_id", "type", "version"],
        set_=set_,
    ).returning(ArtifactModel)

    if session is not None:
        result = await session.execute(stmt)
    else:
        async with async_session_factory() as session:
            result = await session.execute(stmt)
            await session.commit()
    row = result.scalars().first()
    if row is None:
        # ON CONFLICT DO UPDATE ... RETURNING 保证返回行，此处仅防御性收窄
        raise RuntimeError("artifact upsert did not return a row")
    return _artifact_to_dict(row)


async def get_artifact(artifact_id: str) -> dict[str, Any] | None:
    """取单条产物（自动租户过滤；跨租户访问返回 None）。"""
    cond = tenant_filter_expr(ArtifactModel.tenant_id)
    async with async_session_factory() as session:
        result = await session.execute(select(ArtifactModel).where(ArtifactModel.id == artifact_id, cond))
        row = result.scalars().first()
        if row is None:
            return None
        return _artifact_to_dict(row)


async def get_artifacts_by_ids(artifact_ids: list[str]) -> list[dict[str, Any]]:
    """批量获取产物（自动租户过滤）。

    不存在或跨租户的 id 会被静默剔除——调用方据此实现
    「跨租户产物引用拒绝」（复用 produce.py:734 的校验模式）。
    """
    if not artifact_ids:
        return []
    cond = tenant_filter_expr(ArtifactModel.tenant_id)
    async with async_session_factory() as session:
        result = await session.execute(
            select(ArtifactModel)
            .where(ArtifactModel.id.in_(artifact_ids), cond)
            .order_by(ArtifactModel.created_at.desc())
        )
        rows = result.scalars().all()
        return [_artifact_to_dict(row) for row in rows]


async def list_artifacts(
    meeting_id: str | None = None,
    artifact_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """分页查询产物（自动租户过滤，最新在上）。

    Returns:
        {items: [...], total: int}
    """
    cond = tenant_filter_expr(ArtifactModel.tenant_id)
    conds: list[Any] = [cond]
    if meeting_id:
        conds.append(ArtifactModel.meeting_id == meeting_id)
    if artifact_type:
        conds.append(ArtifactModel.type == artifact_type)

    async with async_session_factory() as session:
        total = (await session.execute(select(func.count()).select_from(ArtifactModel).where(*conds))).scalar_one()
        result = await session.execute(
            select(ArtifactModel).where(*conds).order_by(ArtifactModel.created_at.desc()).limit(limit).offset(offset)
        )
        rows = result.scalars().all()
        return {"items": [_artifact_to_dict(row) for row in rows], "total": int(total)}
