"""用户偏好（user_preferences）持久化。

提供单条/全部偏好的读写与删除。
已迁移到 SQLAlchemy ORM：显式 select / pg_insert upsert / delete，
不使用手写 SQL 字符串和 relationship（见 docs/sql-development-rules.md）。

多租户：写入时自动填充 tenant_id；读取按租户过滤。
"""

from __future__ import annotations

from typing import Any, cast

from sqlalchemy import CursorResult, delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.base import utcnow
from app.db.engine import async_session_factory
from app.db.models import UserPreferenceModel
from app.tenants import current_tenant_id
from app.tenants.dao import tenant_filter_expr


async def get_preference(user_id: str, key: str) -> str | None:
    """取单条用户偏好，不存在返回 None。自动租户过滤。"""
    cond = tenant_filter_expr(UserPreferenceModel.tenant_id)
    async with async_session_factory() as session:
        result = await session.execute(
            select(UserPreferenceModel.value).where(
                UserPreferenceModel.user_id == user_id,
                UserPreferenceModel.key == key,
                cond,
            )
        )
        return result.scalar_one_or_none()


async def set_preference(user_id: str, key: str, value: str) -> str:
    """upsert 用户偏好，返回写入的 updated_at。自动填充 tenant_id。"""
    updated_at = utcnow()
    tid = current_tenant_id()
    values: dict[str, Any] = {
        "user_id": user_id,
        "key": key,
        "value": value,
        "updated_at": updated_at,
    }
    if tid is not None:
        values["tenant_id"] = tid
    insert_stmt = pg_insert(UserPreferenceModel).values(**values)
    stmt = insert_stmt.on_conflict_do_update(
        index_elements=["user_id", "key"],
        set_={
            "value": insert_stmt.excluded.value,
            "updated_at": insert_stmt.excluded.updated_at,
        },
    )
    async with async_session_factory() as session:
        await session.execute(stmt)
        await session.commit()
        return updated_at.isoformat()


async def get_all_preferences(user_id: str) -> dict[str, str]:
    """取该用户全部偏好，返回 {key: value}。自动租户过滤。"""
    cond = tenant_filter_expr(UserPreferenceModel.tenant_id)
    async with async_session_factory() as session:
        result = await session.execute(
            select(UserPreferenceModel.key, UserPreferenceModel.value).where(
                UserPreferenceModel.user_id == user_id,
                cond,
            )
        )
        rows = result.mappings().all()
        return {r["key"]: r["value"] for r in rows}


async def delete_preference(user_id: str, key: str) -> bool:
    """删除单条用户偏好，返回是否删除了记录。自动租户过滤。"""
    cond = tenant_filter_expr(UserPreferenceModel.tenant_id)
    stmt = delete(UserPreferenceModel).where(
        UserPreferenceModel.user_id == user_id,
        UserPreferenceModel.key == key,
        cond,
    )
    async with async_session_factory() as session:
        result = await session.execute(stmt)
        await session.commit()
        return cast(CursorResult, result).rowcount > 0
