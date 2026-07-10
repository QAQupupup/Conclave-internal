"""异步数据库访问包装器：把同步 SQLite 操作丢到线程池执行，避免阻塞事件循环。

[CON-01 修复] 旧版 router/orchestrator 直接 await 同步 SQLite 函数，阻塞 FastAPI 事件循环。
本模块提供同名 async 函数，签名兼容，内部用 asyncio.to_thread 把同步操作交给线程池。
"""
from __future__ import annotations

import asyncio
import functools
import json
import sqlite3
import threading
from typing import Any, Callable, TypeVar

from app.config import settings
from app.db_legacy import _connect, _lock  # 复用连接工厂与锁

T = TypeVar("T")


async def to_thread(func: Callable[..., T], *args, **kwargs) -> T:
    """把同步函数丢到默认线程池执行。"""
    return await asyncio.to_thread(func, *args, **kwargs)


# ---- meetings 表 ----


async def save_meeting_async(
    meeting_id: str,
    topic: str,
    status: str,
    stage: str,
    created_at: str,
    payload: dict,
) -> None:
    """异步保存/更新会议元信息。"""
    from app.db_legacy import save_meeting  # 复用原函数，复用 _lock

    return await to_thread(save_meeting, meeting_id, topic, status, stage, created_at, payload)


async def get_meeting_async(meeting_id: str) -> dict | None:
    """异步读取会议记录。"""
    from app.db_legacy import get_meeting

    return await to_thread(get_meeting, meeting_id)


async def get_meetings_by_ids_async(ids: list[str]) -> list[dict]:
    """异步批量读取会议。"""
    from app.db_legacy import get_meetings_by_ids

    return await to_thread(get_meetings_by_ids, ids)


async def list_meetings_async(*, include_deleted: bool = False, limit: int = 100, offset: int = 0) -> list[dict]:
    """异步列出会议。"""
    from app.db_legacy import list_meetings

    return await to_thread(list_meetings, include_deleted=include_deleted, limit=limit, offset=offset)


async def search_meetings_async(
    query: str,
    *,
    include_deleted: bool = False,
    limit: int = 50,
) -> list[dict]:
    """异步搜索会议。"""
    from app.db_legacy import search_meetings

    return await to_thread(search_meetings, query, include_deleted=include_deleted, limit=limit)


async def soft_delete_meeting_async(meeting_id: str) -> bool:
    from app.db_legacy import soft_delete_meeting
    return await to_thread(soft_delete_meeting, meeting_id)


async def hard_delete_meeting_async(meeting_id: str) -> bool:
    from app.db_legacy import hard_delete_meeting
    return await to_thread(hard_delete_meeting, meeting_id)


async def batch_delete_meetings_async(meeting_ids: list[str], mode: str = "soft") -> dict:
    from app.db_legacy import batch_delete_meetings
    return await to_thread(batch_delete_meetings, meeting_ids, mode=mode)


async def recover_running_meetings_async() -> list[str]:
    from app.db_legacy import recover_running_meetings
    return await to_thread(recover_running_meetings)


# ---- messages 表 ----


async def save_message_async(
    message_id: str,
    meeting_id: str,
    agent_role: str,
    stage: str,
    content: str,
    claim_refs: list[str] | None = None,
    evidence_refs: list[str] | None = None,
    created_at: str | None = None,
) -> None:
    from app.db_legacy import save_message
    return await to_thread(
        save_message,
        message_id,
        meeting_id,
        agent_role,
        stage,
        content,
        claim_refs,
        evidence_refs,
        created_at,
    )


async def list_messages_async(meeting_id: str, limit: int = 100, offset: int = 0) -> list[dict]:
    from app.db_legacy import list_messages
    return await to_thread(list_messages, meeting_id, limit=limit, offset=offset)


# ---- 元数据表 ----


async def add_meeting_tag_async(meeting_id: str, tag: str) -> bool:
    from app.db_legacy import add_meeting_tag
    return await to_thread(add_meeting_tag, meeting_id, tag)


async def remove_meeting_tag_async(meeting_id: str, tag: str) -> bool:
    from app.db_legacy import remove_meeting_tag
    return await to_thread(remove_meeting_tag, meeting_id, tag)


async def list_all_tags_async() -> list[dict]:
    from app.db_legacy import list_all_tags
    return await to_thread(list_all_tags)


# ---- 公共入口：替换高层调用 ----


async def check_db_health_async() -> bool:
    """异步检查 DB 是否可用。"""
    def _check() -> bool:
        conn = _connect()
        try:
            conn.execute("SELECT 1").fetchone()
            return True
        except sqlite3.Error:
            return False
        finally:
            conn.close()

    return await to_thread(_check)
