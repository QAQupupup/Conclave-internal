"""Repository 工厂：返回 SQLAlchemy ORM Repository bundle。"""

Usage::

    from app.db.factory import get_repos

    async with get_repos() as repos:
        meeting = await repos.meetings.get(meeting_id)

- "legacy" → 包装 db_legacy 同步函数的 LegacyRepoBundle
- "orm"    → SQLAlchemy RepositoryFactory（需要 AsyncSession）
"""
from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, AsyncIterator


logger = logging.getLogger("db.factory")


# ============================================================
# Legacy 包装层：把 db_legacy 同步函数包成 async 接口
# ============================================================

class _LegacyMeetingRepo:
    """db_legacy 会议函数的 async 包装。"""

    async def save(self, meeting_id: str, topic: str, status: str,
                   stage: str, created_at: datetime, payload: dict[str, Any],
                   schema_version: int = 1) -> None:
        from app.db_legacy import save_meeting
        save_meeting(
            meeting_id=meeting_id, topic=topic, status=status,
            stage=stage, created_at=created_at,
            payload=json.dumps(payload, ensure_ascii=False, default=str),
        )

    async def get(self, meeting_id: str) -> dict[str, Any] | None:
        from app.db_legacy import get_meeting
        return get_meeting(meeting_id)

    async def list(self, include_deleted: bool = False) -> list[dict[str, Any]]:
        from app.db_legacy import list_meetings
        rows = list_meetings()
        if not include_deleted:
            rows = [r for r in rows if r.get("status") != "deleted"]
        return rows

    async def query(self, q: str | None = None, limit: int = 20,
                    offset: int = 0, tags: list[str] | None = None,
                    include_deleted: bool = False) -> dict[str, Any]:
        from app.db_legacy import query_meetings
        return query_meetings(q=q, limit=limit, offset=offset, tags=tags)

    async def get_by_ids(self, meeting_ids: list[str]) -> list[dict[str, Any]]:
        from app.db_legacy import get_meetings_by_ids
        return get_meetings_by_ids(meeting_ids)

    async def soft_delete(self, meeting_id: str) -> bool:
        from app.db_legacy import soft_delete_meeting
        return soft_delete_meeting(meeting_id)

    async def hard_delete(self, meeting_id: str) -> bool:
        from app.db_legacy import hard_delete_meeting
        return hard_delete_meeting(meeting_id)

    async def restore(self, meeting_id: str) -> bool:
        from app.db_legacy import restore_meeting
        return restore_meeting(meeting_id)

    async def recover_running(self) -> list[dict[str, Any]]:
        from app.db_legacy import recover_running_meetings
        return recover_running_meetings()


class _LegacyMessageRepo:
    """db_legacy 发言函数的 async 包装。"""

    async def save(self, msg: dict[str, Any]) -> None:
        from app.db_legacy import save_message
        save_message(msg)

    async def list_by_meeting(self, meeting_id: str) -> list[dict[str, Any]]:
        from app.db_legacy import list_messages
        return list_messages(meeting_id)


class _LegacyEventRepo:
    """db_legacy 事件函数的 async 包装。"""

    async def save(self, meeting_id: str, event_type: str,
                   payload: dict[str, Any], ts: str,
                   trace_id: str | None = None) -> int:
        from app.db_legacy import save_event
        return save_event(
            meeting_id=meeting_id, event_type=event_type,
            payload=payload, ts=ts, trace_id=trace_id,
        )

    async def load(self, meeting_id: str, from_seq: int = 0) -> list[dict[str, Any]]:
        from app.db_legacy import load_events
        return load_events(meeting_id, from_seq=from_seq)

    async def last_seq(self, meeting_id: str) -> int:
        from app.db_legacy import last_event_seq
        return last_event_seq(meeting_id)


class _LegacyTagRepo:
    """db_legacy 标签函数的 async 包装。"""

    async def list_all(self) -> list[dict[str, Any]]:
        from app.db_legacy import list_all_tags
        return list_all_tags()

    async def get_meeting_tags(self, meeting_id: str) -> list[str]:
        from app.db_legacy import get_meeting_tags
        return get_meeting_tags(meeting_id)

    async def add(self, meeting_id: str, tag: str) -> bool:
        from app.db_legacy import add_meeting_tag
        return add_meeting_tag(meeting_id, tag)

    async def remove(self, meeting_id: str, tag: str) -> bool:
        from app.db_legacy import remove_meeting_tag
        return remove_meeting_tag(meeting_id, tag)

    async def batch_delete(self, meeting_ids: list[str],
                           mode: str = "soft") -> dict[str, list[str]]:
        from app.db_legacy import batch_delete_meetings
        return batch_delete_meetings(meeting_ids, mode=mode)


class _LegacyPreferenceRepo:
    """db_legacy 偏好函数的 async 包装。"""

    async def get(self, user_id: str, key: str) -> str | None:
        from app.db_legacy import get_preference
        return get_preference(key, user_id=user_id)

    async def set(self, user_id: str, key: str, value: str) -> str:
        from app.db_legacy import set_preference
        return set_preference(key, value, user_id=user_id)

    async def get_all(self, user_id: str) -> dict[str, str]:
        from app.db_legacy import get_all_preferences
        return get_all_preferences(user_id=user_id)

    async def delete(self, user_id: str, key: str) -> bool:
        from app.db_legacy import delete_preference
        return delete_preference(key, user_id=user_id)


class _LegacyAgentRoleRepo:
    """db_legacy 角色函数的 async 包装。"""

    async def list(self, active_only: bool = False) -> list[dict[str, Any]]:
        from app.db_legacy import list_agent_roles
        return list_agent_roles(active_only=active_only)

    async def get(self, role_id: str) -> dict[str, Any] | None:
        from app.db_legacy import get_agent_role
        return get_agent_role(role_id)

    async def save(self, role: dict[str, Any]) -> None:
        from app.db_legacy import save_agent_role
        save_agent_role(role)

    async def delete(self, role_id: str) -> bool:
        from app.db_legacy import delete_agent_role
        return delete_agent_role(role_id)

    async def get_by_ids(self, role_ids: list[str]) -> list[dict[str, Any]]:
        from app.db_legacy import get_agent_roles_by_ids
        return get_agent_roles_by_ids(role_ids)


class LegacyRepoBundle:
    """Legacy 后端：所有 db_legacy 函数的 async 包装，按实体分组。"""

    def __init__(self) -> None:
        self.meetings = _LegacyMeetingRepo()
        self.messages = _LegacyMessageRepo()
        self.events = _LegacyEventRepo()
        self.tags = _LegacyTagRepo()
        self.preferences = _LegacyPreferenceRepo()
        self.agent_roles = _LegacyAgentRoleRepo()
        # net_auth 暂不在 db_legacy 中，orm 模式下才完整支持
        self.net_auth = None


# ============================================================
# 工厂函数
# ============================================================

@asynccontextmanager
async def get_repos() -> AsyncIterator[Any]:
    """异步上下文管理器：返回 Repository bundle（SQLAlchemy ORM）。"""
    from app.db.engine import async_session_factory
    from app.db.sqlalchemy_repo import RepositoryFactory

    async with async_session_factory() as session:
        try:
            yield RepositoryFactory(session)
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def get_backend_name() -> str:
    """返回当前配置的后端名称，用于日志/健康检查。"""
    return "orm"
