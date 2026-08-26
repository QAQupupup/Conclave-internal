"""事件（events）持久化。

提供事件保存、增量/全量回放加载以及最新 seq 查询。
已迁移到 SQLAlchemy ORM：显式 select / pg_insert，
不使用手写 SQL 字符串和 relationship（见 docs/sql-development-rules.md）。

多租户：写入时自动填充 tenant_id；读取通过 meeting_id 间接隔离。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import exists, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.base import utcnow
from app.db.engine import async_session_factory
from app.db.models import EventModel, MeetingModel
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


async def save_event(
    meeting_id: str,
    event_type: str,
    payload: dict[str, Any],
    ts: str,
    trace_id: str | None = None,
) -> int:
    """持久化事件到 PostgreSQL，返回自增 seq（对外 0 起始）。自动填充 tenant_id。"""
    tid = current_tenant_id()
    values: dict[str, Any] = {
        "meeting_id": meeting_id,
        "type": event_type,
        "payload": json.dumps(payload, ensure_ascii=False, default=str),
        "ts": _parse_dt(ts),
        "trace_id": trace_id,
    }
    if tid is not None:
        values["tenant_id"] = tid

    stmt = pg_insert(EventModel).values(**values).returning(EventModel.seq)
    async with async_session_factory() as session:
        result = await session.execute(stmt)
        seq = result.scalars().first()
        await session.commit()
        if seq is None:
            seq = 1
        return seq - 1


async def load_events(meeting_id: str, from_seq: int = 0, limit: int = 0) -> list[dict[str, Any]]:
    """从 PostgreSQL 加载事件，支持增量回放。

    防御性租户隔离：通过 EXISTS 子查询验证 meeting_id 属于当前租户。
    limit=0 表示不限制（增量回放场景）；全量恢复时应传 limit 防止内存暴涨。
    """
    tid = current_tenant_id()
    tenant_conds: list[Any] = []
    if tid is not None:
        tenant_conds.append(
            exists(
                select(MeetingModel.id).where(
                    MeetingModel.id == EventModel.meeting_id,
                    MeetingModel.tenant_id == tid,
                )
            )
        )
    base_conds = [EventModel.meeting_id == meeting_id, EventModel.seq > from_seq, *tenant_conds]

    async with async_session_factory() as session:
        if limit > 0 and from_seq == 0:
            inner = select(EventModel.seq).where(*base_conds).order_by(EventModel.seq.desc()).limit(limit).subquery()
            stmt = select(EventModel).where(EventModel.seq.in_(select(inner.c.seq))).order_by(EventModel.seq.asc())
        else:
            stmt = select(EventModel).where(*base_conds).order_by(EventModel.seq.asc())

        result = await session.execute(stmt)
        rows = result.scalars().all()
        out = []
        for row in rows:
            out.append(
                {
                    "seq": row.seq - 1,
                    "meeting_id": row.meeting_id,
                    "type": row.type,
                    "payload": json.loads(row.payload),
                    "ts": _iso(row.ts),
                    "trace_id": row.trace_id,
                }
            )
        return out


async def last_event_seq(meeting_id: str) -> int:
    """取某会议最后一条事件的 seq（对外 0 起始），无事件返回 0"""
    async with async_session_factory() as session:
        result = await session.execute(select(func.max(EventModel.seq)).where(EventModel.meeting_id == meeting_id))
        max_seq = result.scalar()
        return (max_seq - 1) if max_seq else 0
