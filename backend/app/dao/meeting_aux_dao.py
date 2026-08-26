"""会议辅助大字段（meeting_aux）持久化。

将 llm_trace、evidence_set 等大字段从 payload 中分离单独存储，
并提供 payload 精简工具函数。

统一 ORM 访问：读写走 MeetingAuxModel + 显式 select / pg_insert upsert，
不使用 relationship，不使用手写 SQL 字符串（见 docs/sql-development-rules.md）。

多租户：写入时自动填充 tenant_id；读取通过 meeting_id 间接隔离。
"""

from __future__ import annotations

import contextlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import utcnow
from app.db.engine import async_session_factory
from app.db.models import MeetingAuxModel
from app.tenants import current_tenant_id

# 需要从 payload 中分离的 aux 字段名列表
_AUX_KEYS = ("llm_trace", "evidence_set", "conclusion_chain", "borrowed_agents")


async def save_meeting_aux(
    meeting_id: str,
    aux: dict[str, Any],
    session: AsyncSession | None = None,
) -> None:
    """将 aux 大字段单独持久化到 meeting_aux 表。

    每个 aux key 对应一行，value_json 存 JSON 序列化后的值。
    使用 INSERT ... ON CONFLICT (meeting_id, key) DO UPDATE 实现原子 upsert。

    Args:
        meeting_id: 会议 ID
        aux: extract_aux() 返回的 dict，key 为字段名，value 为可 JSON 序列化的值
        session: 可选外部 session。传入时仅执行 SQL 不 commit（由调用方控制事务）；
                 不传时创建独立 session 并 commit（向后兼容）。
    """
    if not aux:
        return
    now = utcnow()
    tid = current_tenant_id()

    async def _execute_in_session(sess: AsyncSession) -> None:
        for key, value in aux.items():
            stmt = pg_insert(MeetingAuxModel).values(
                meeting_id=meeting_id,
                key=key,
                value_json=json.dumps(value, ensure_ascii=False, default=str),
                updated_at=now,
                tenant_id=tid,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["meeting_id", "key"],
                set_={
                    "value_json": stmt.excluded.value_json,
                    "updated_at": stmt.excluded.updated_at,
                },
            )
            await sess.execute(stmt)

    if session is not None:
        await _execute_in_session(session)
    else:
        async with async_session_factory() as session:
            await _execute_in_session(session)
            await session.commit()


async def get_meeting_aux(meeting_id: str) -> dict[str, Any]:
    """从 meeting_aux 表加载某会议的全部辅助大字段。

    向后兼容：如果 meeting_aux 表不存在或该会议无 aux 数据，返回空 dict。

    Args:
        meeting_id: 会议 ID

    Returns:
        dict，key 为字段名，value 为反序列化后的值。可能为空 dict。
    """
    aux: dict[str, Any] = {}
    try:
        async with async_session_factory() as session:
            result = await session.execute(
                select(MeetingAuxModel.key, MeetingAuxModel.value_json).where(MeetingAuxModel.meeting_id == meeting_id)
            )
            rows = result.all()
            for key, value_json in rows:
                with contextlib.suppress(json.JSONDecodeError, KeyError):
                    aux[key] = json.loads(value_json)
    except Exception:
        # 表可能不存在（旧数据库），静默返回空 dict
        pass
    return aux


def strip_aux_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """从 payload dict 中移除 aux 大字段，返回清理后的副本。

    用于在 save_meeting 之前精简 payload，配合 save_meeting_aux 使用。
    返回新的 dict，不修改原始输入。

    Args:
        payload: MeetingState.snapshot() 返回的 dict

    Returns:
        移除了 aux 字段的 payload 副本
    """
    cleaned = dict(payload)
    for key in _AUX_KEYS:
        if key in cleaned:
            cleaned[key] = {"_aux": True}
    return cleaned
