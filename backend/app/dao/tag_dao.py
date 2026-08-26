"""会议标签（meeting_tags）CRUD。

提供标签聚合列表、按会议增删查标签。
已迁移到 SQLAlchemy ORM：显式 select / pg_insert upsert / delete，
不使用手写 SQL 字符串和 relationship（见 docs/sql-development-rules.md）。

多租户：list_all_tags 按租户聚合；写入时自动填充 tenant_id。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast

from sqlalchemy import CursorResult, delete, desc, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.base import utcnow
from app.db.engine import async_session_factory
from app.db.models import MeetingTagModel
from app.tenants import current_tenant_id
from app.tenants.dao import tenant_filter_expr


def _iso(v: Any) -> Any:
    """datetime → ISO 字符串（保持历史 TEXT 返回契约）。"""
    return v.isoformat() if isinstance(v, datetime) else v


async def list_all_tags() -> list[dict[str, Any]]:
    """列出当前租户所有标签及其使用次数，按使用次数降序排列。"""
    cond = tenant_filter_expr(MeetingTagModel.tenant_id)
    async with async_session_factory() as session:
        result = await session.execute(
            select(
                MeetingTagModel.tag,
                func.count().label("cnt"),
                func.max(MeetingTagModel.created_at).label("last_used"),
            )
            .where(cond)
            .group_by(MeetingTagModel.tag)
            .order_by(desc(func.count()), MeetingTagModel.tag.asc())
        )
        rows = result.mappings().all()
        return [{"tag": r["tag"], "count": r["cnt"], "last_used": _iso(r["last_used"])} for r in rows]


async def get_meeting_tags(meeting_id: str) -> list[str]:
    """取某会议的全部标签。meeting_id 来自已租户隔离的会议查询。"""
    async with async_session_factory() as session:
        result = await session.execute(
            select(MeetingTagModel.tag)
            .where(MeetingTagModel.meeting_id == meeting_id)
            .order_by(MeetingTagModel.tag.asc())
        )
        return list(result.scalars().all())


async def add_meeting_tag(meeting_id: str, tag: str) -> bool:
    """为会议添加标签。已存在则忽略（UNIQUE 约束）。返回是否新增。自动填充 tenant_id。"""
    tid = current_tenant_id()
    values: dict[str, Any] = {
        "meeting_id": meeting_id,
        "tag": tag,
        "created_at": utcnow(),
    }
    if tid is not None:
        values["tenant_id"] = tid
    stmt = pg_insert(MeetingTagModel).values(**values).on_conflict_do_nothing(index_elements=["meeting_id", "tag"])
    async with async_session_factory() as session:
        result = await session.execute(stmt)
        await session.commit()
        return (cast(CursorResult, result).rowcount or 0) > 0


async def remove_meeting_tag(meeting_id: str, tag: str) -> bool:
    """移除会议的某个标签。返回是否删除了记录。"""
    stmt = delete(MeetingTagModel).where(
        MeetingTagModel.meeting_id == meeting_id,
        MeetingTagModel.tag == tag,
    )
    async with async_session_factory() as session:
        result = await session.execute(stmt)
        await session.commit()
        return (cast(CursorResult, result).rowcount or 0) > 0
