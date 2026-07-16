"""会议标签（meeting_tags）CRUD。

提供标签聚合列表、按会议增删查标签。
原迁移自 app/db_legacy.py，逻辑未做任何修改。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import text

from app.db.engine import async_session_factory


async def list_all_tags() -> list[dict[str, Any]]:
    """列出所有标签及其使用次数，按使用次数降序排列"""
    async with async_session_factory() as session:
        result = await session.execute(
            text(
                """SELECT tag, COUNT(*) as cnt, MAX(created_at) as last_used
                FROM meeting_tags
                GROUP BY tag
                ORDER BY cnt DESC, tag ASC"""
            )
        )
        rows = result.mappings().all()
        return [{"tag": r["tag"], "count": r["cnt"], "last_used": r["last_used"]} for r in rows]


async def get_meeting_tags(meeting_id: str) -> list[str]:
    """取某会议的全部标签"""
    async with async_session_factory() as session:
        result = await session.execute(
            text("SELECT tag FROM meeting_tags WHERE meeting_id = :meeting_id ORDER BY tag"),
            {"meeting_id": meeting_id},
        )
        rows = result.mappings().all()
        return [r["tag"] for r in rows]


async def add_meeting_tag(meeting_id: str, tag: str) -> bool:
    """为会议添加标签。已存在则忽略（UNIQUE 约束）。返回是否新增。"""
    async with async_session_factory() as session:
        result = await session.execute(
            text(
                """INSERT INTO meeting_tags (meeting_id, tag, created_at)
                VALUES (:meeting_id, :tag, :created_at)
                ON CONFLICT(meeting_id, tag) DO NOTHING"""
            ),
            {
                "meeting_id": meeting_id,
                "tag": tag,
                "created_at": datetime.now().isoformat(),
            },
        )
        await session.commit()
        return result.rowcount > 0


async def remove_meeting_tag(meeting_id: str, tag: str) -> bool:
    """移除会议的某个标签。返回是否删除了记录。"""
    async with async_session_factory() as session:
        result = await session.execute(
            text("DELETE FROM meeting_tags WHERE meeting_id = :meeting_id AND tag = :tag"),
            {"meeting_id": meeting_id, "tag": tag},
        )
        await session.commit()
        return result.rowcount > 0
