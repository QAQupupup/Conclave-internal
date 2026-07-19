"""会议辅助大字段（meeting_aux）持久化。

将 llm_trace、evidence_set 等大字段从 payload 中分离单独存储，
并提供 payload 精简工具函数。
原迁移自 app/db_legacy.py，逻辑未做任何修改。
"""

from __future__ import annotations

import contextlib
import json
from datetime import datetime
from typing import Any

from sqlalchemy import text

from app.db.engine import async_session_factory

# 需要从 payload 中分离的 aux 字段名列表
_AUX_KEYS = ("llm_trace", "evidence_set", "conclusion_chain", "borrowed_agents")


async def save_meeting_aux(meeting_id: str, aux: dict[str, Any]) -> None:
    """将 aux 大字段单独持久化到 meeting_aux 表。

    每个 aux key 对应一行，value_json 存 JSON 序列化后的值。
    使用 INSERT ... ON CONFLICT DO UPDATE 实现 upsert。

    Args:
        meeting_id: 会议 ID
        aux: extract_aux() 返回的 dict，key 为字段名，value 为可 JSON 序列化的值
    """
    if not aux:
        return
    now = datetime.now().isoformat()
    async with async_session_factory() as session:
        for key, value in aux.items():
            await session.execute(
                text(
                    """
                    INSERT INTO meeting_aux (meeting_id, key, value_json, updated_at)
                    VALUES (:meeting_id, :key, :value_json, :updated_at)
                    ON CONFLICT(meeting_id, key) DO UPDATE SET
                        value_json=excluded.value_json,
                        updated_at=excluded.updated_at
                    """
                ),
                {
                    "meeting_id": meeting_id,
                    "key": key,
                    "value_json": json.dumps(value, ensure_ascii=False, default=str),
                    "updated_at": now,
                },
            )
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
                text("SELECT key, value_json FROM meeting_aux WHERE meeting_id = :meeting_id"),
                {"meeting_id": meeting_id},
            )
            rows = result.mappings().all()
            for row in rows:
                with contextlib.suppress(json.JSONDecodeError, KeyError):
                    aux[row["key"]] = json.loads(row["value_json"])
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
