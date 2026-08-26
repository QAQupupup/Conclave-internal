"""发言记录（messages）持久化。

提供保存与按会议列出发言记录的能力。
已迁移到 SQLAlchemy ORM：显式 select / pg_insert upsert，
不使用手写 SQL 字符串和 relationship（见 docs/sql-development-rules.md）。

多租户：写入时自动填充 tenant_id；读取通过 meeting_id 间接隔离。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import exists, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import utcnow
from app.db.engine import async_session_factory
from app.db.models import MeetingModel, MessageModel
from app.tenants import current_tenant_id


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


async def save_message(
    msg: dict[str, Any],
    session: AsyncSession | None = None,
) -> None:
    """保存发言记录。自动填充当前 tenant_id。

    Args:
        session: 可选外部 session。传入时仅执行 SQL 不 commit（由调用方控制事务）；
                 不传时创建独立 session 并 commit（向后兼容）。
    """
    tid = current_tenant_id()
    values: dict[str, Any] = {
        "id": msg["id"],
        "meeting_id": msg["meeting_id"],
        "agent_role": msg["agent_role"],
        "stage": msg["stage"],
        "content": msg["content"],
        "claim_refs": json.dumps(msg.get("claim_refs", []), ensure_ascii=False),
        "evidence_refs": json.dumps(msg.get("evidence_refs", []), ensure_ascii=False),
        "created_at": _parse_dt(msg["created_at"]),
    }
    if tid is not None:
        values["tenant_id"] = tid

    insert_stmt = pg_insert(MessageModel).values(**values)
    stmt = insert_stmt.on_conflict_do_update(
        index_elements=["id"],
        set_={
            "meeting_id": insert_stmt.excluded.meeting_id,
            "agent_role": insert_stmt.excluded.agent_role,
            "stage": insert_stmt.excluded.stage,
            "content": insert_stmt.excluded.content,
            "claim_refs": insert_stmt.excluded.claim_refs,
            "evidence_refs": insert_stmt.excluded.evidence_refs,
            "created_at": insert_stmt.excluded.created_at,
        },
    )

    if session is not None:
        await session.execute(stmt)
    else:
        async with async_session_factory() as session:
            await session.execute(stmt)
            await session.commit()


async def list_messages(meeting_id: str) -> list[dict[str, Any]]:
    """取某会议的全部发言。

    防御性租户隔离：通过 EXISTS 子查询验证 meeting_id 属于当前租户，
    即使调用方传入了跨租户的 meeting_id，也不会返回数据。
    """
    tid = current_tenant_id()
    conds: list[Any] = [MessageModel.meeting_id == meeting_id]
    if tid is not None:
        conds.append(
            exists(
                select(MeetingModel.id).where(
                    MeetingModel.id == MessageModel.meeting_id,
                    MeetingModel.tenant_id == tid,
                )
            )
        )

    async with async_session_factory() as session:
        result = await session.execute(select(MessageModel).where(*conds).order_by(MessageModel.created_at.asc()))
        rows = result.scalars().all()
        out = []
        for row in rows:
            out.append(
                {
                    "id": row.id,
                    "meeting_id": row.meeting_id,
                    "agent_role": row.agent_role,
                    "stage": row.stage,
                    "content": row.content,
                    "claim_refs": json.loads(row.claim_refs or "[]"),
                    "evidence_refs": json.loads(row.evidence_refs or "[]"),
                    "created_at": _iso(row.created_at),
                    "tenant_id": row.tenant_id,
                }
            )
        return out
