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


# 单批批量写入上限：防止 multi-row INSERT 超参（PostgreSQL 每语句参数上限 65535）
_MAX_BATCH_ROWS = 500


async def save_events_batch(rows: list[dict[str, Any]]) -> list[int]:
    """批量持久化事件（单次 INSERT + 单次 commit），返回各事件的对外 seq 列表（0 起始）。

    rows 每项需含 meeting_id/type/payload/ts，trace_id/tenant_id 可选。
    返回的 seq 按传入顺序排序后单调递增（DB 自增分配与插入顺序一致）。
    空批直接返回 []；批大小超过 _MAX_BATCH_ROWS 时由调用方分块（本函数不递归）。
    """
    if not rows:
        return []

    tid = current_tenant_id()
    values: list[dict[str, Any]] = []
    for r in rows:
        row: dict[str, Any] = {
            "meeting_id": r["meeting_id"],
            "type": r["type"],
            "payload": json.dumps(r["payload"], ensure_ascii=False, default=str),
            "ts": _parse_dt(r["ts"]),
            "trace_id": r.get("trace_id"),
        }
        if tid is not None:
            row["tenant_id"] = tid
        values.append(row)

    stmt = pg_insert(EventModel).values(values).returning(EventModel.seq)
    async with async_session_factory() as session:
        result = await session.execute(stmt)
        seqs = [s for s in result.scalars().all() if s is not None]
        await session.commit()

    # 按自增值排序，保证与 rows 插入顺序一一对应（多行 RETURNING 顺序不强制保证，排序兜底）
    sorted_seqs = sorted(seqs)
    if len(sorted_seqs) != len(rows):
        # 理论上不应发生；长度不匹配时宁可返回按行数补齐的占位 seq，也不抛异常破坏流程
        pad = len(rows) - len(sorted_seqs)
        last = sorted_seqs[-1] if sorted_seqs else 0
        sorted_seqs += [last + i + 1 for i in range(pad)]
    return [s - 1 for s in sorted_seqs]


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
