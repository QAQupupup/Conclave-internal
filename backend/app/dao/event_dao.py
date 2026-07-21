"""事件（events）持久化。

提供事件保存、增量/全量回放加载以及最新 seq 查询。
原迁移自 app/db_legacy.py，逻辑未做任何修改。

多租户：写入时自动填充 tenant_id；读取通过 meeting_id 间接隔离。
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text

from app.db.engine import async_session_factory
from app.tenants import current_tenant_id


async def save_event(
    meeting_id: str,
    event_type: str,
    payload: dict[str, Any],
    ts: str,
    trace_id: str | None = None,
) -> int:
    """持久化事件到 PostgreSQL，返回自增 seq（对外 0 起始）。自动填充 tenant_id。"""
    tid = current_tenant_id()
    async with async_session_factory() as session:
        if tid is not None:
            result = await session.execute(
                text(
                    """INSERT INTO events (meeting_id, type, payload, ts, trace_id, tenant_id)
                    VALUES (:meeting_id, :event_type, :payload, :ts, :trace_id, :tenant_id)
                    RETURNING seq"""
                ),
                {
                    "meeting_id": meeting_id,
                    "event_type": event_type,
                    "payload": json.dumps(payload, ensure_ascii=False, default=str),
                    "ts": ts,
                    "trace_id": trace_id,
                    "tenant_id": tid,
                },
            )
        else:
            result = await session.execute(
                text(
                    """INSERT INTO events (meeting_id, type, payload, ts, trace_id)
                    VALUES (:meeting_id, :event_type, :payload, :ts, :trace_id)
                    RETURNING seq"""
                ),
                {
                    "meeting_id": meeting_id,
                    "event_type": event_type,
                    "payload": json.dumps(payload, ensure_ascii=False, default=str),
                    "ts": ts,
                    "trace_id": trace_id,
                },
            )
        seq = result.scalars().first()
        await session.commit()
        if seq is None:
            seq = 1
        return seq - 1  # type: ignore[no-any-return]


async def load_events(meeting_id: str, from_seq: int = 0, limit: int = 0) -> list[dict[str, Any]]:
    """从 PostgreSQL 加载事件，支持增量回放。
    limit=0 表示不限制（增量回放场景）；全量恢复时应传 limit 防止内存暴涨。
    meeting_id 来自已租户隔离的会议查询。
    """
    async with async_session_factory() as session:
        if limit > 0 and from_seq == 0:
            result = await session.execute(
                text(
                    """SELECT seq, meeting_id, type, payload, ts, trace_id FROM (
                        SELECT seq, meeting_id, type, payload, ts, trace_id
                        FROM events WHERE meeting_id = :meeting_id AND seq > :from_seq
                        ORDER BY seq DESC LIMIT CAST(:limit AS INTEGER)
                    ) t ORDER BY seq ASC"""
                ),
                {"meeting_id": meeting_id, "from_seq": from_seq, "limit": limit},
            )
        else:
            result = await session.execute(
                text(
                    """SELECT seq, meeting_id, type, payload, ts, trace_id
                    FROM events WHERE meeting_id = :meeting_id AND seq > :from_seq
                    ORDER BY seq ASC"""
                ),
                {"meeting_id": meeting_id, "from_seq": from_seq},
            )
        rows = result.mappings().all()
        out = []
        for row in rows:
            out.append(
                {
                    "seq": row["seq"] - 1,
                    "meeting_id": row["meeting_id"],
                    "type": row["type"],
                    "payload": json.loads(row["payload"]),
                    "ts": row["ts"],
                    "trace_id": row["trace_id"],
                }
            )
        return out


async def last_event_seq(meeting_id: str) -> int:
    """取某会议最后一条事件的 seq（对外 0 起始），无事件返回 0"""
    async with async_session_factory() as session:
        result = await session.execute(
            text("SELECT MAX(seq) as max_seq FROM events WHERE meeting_id = :meeting_id"),
            {"meeting_id": meeting_id},
        )
        row = result.mappings().first()
        return (row["max_seq"] - 1) if row and row["max_seq"] else 0
