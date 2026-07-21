"""用户偏好（user_preferences）持久化。

提供单条/全部偏好的读写与删除。
原迁移自 app/db_legacy.py，逻辑未做任何修改。

多租户：写入时自动填充 tenant_id；读取按租户过滤。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import text

from app.db.engine import async_session_factory
from app.tenants import current_tenant_id, tenant_filter_clause


async def get_preference(user_id: str, key: str) -> str | None:
    """取单条用户偏好，不存在返回 None。自动租户过滤。"""
    tcond, tparams = tenant_filter_clause()
    async with async_session_factory() as session:
        result = await session.execute(
            text(f"SELECT value FROM user_preferences WHERE user_id = :user_id AND key = :key AND {tcond}"),
            {"user_id": user_id, "key": key, **tparams},
        )
        row = result.mappings().first()
        return row["value"] if row else None


async def set_preference(user_id: str, key: str, value: str) -> str:
    """upsert 用户偏好，返回写入的 updated_at。自动填充 tenant_id。"""
    updated_at = datetime.now().isoformat()
    tid = current_tenant_id()
    async with async_session_factory() as session:
        if tid is not None:
            await session.execute(
                text(
                    """
                    INSERT INTO user_preferences (user_id, key, value, updated_at, tenant_id)
                    VALUES (:user_id, :key, :value, :updated_at, :tenant_id)
                    ON CONFLICT(user_id, key) DO UPDATE SET
                        value=excluded.value,
                        updated_at=excluded.updated_at
                    """
                ),
                {
                    "user_id": user_id,
                    "key": key,
                    "value": value,
                    "updated_at": updated_at,
                    "tenant_id": tid,
                },
            )
        else:
            await session.execute(
                text(
                    """
                    INSERT INTO user_preferences (user_id, key, value, updated_at)
                    VALUES (:user_id, :key, :value, :updated_at)
                    ON CONFLICT(user_id, key) DO UPDATE SET
                        value=excluded.value,
                        updated_at=excluded.updated_at
                    """
                ),
                {
                    "user_id": user_id,
                    "key": key,
                    "value": value,
                    "updated_at": updated_at,
                },
            )
        await session.commit()
        return updated_at


async def get_all_preferences(user_id: str) -> dict[str, str]:
    """取该用户全部偏好，返回 {key: value}。自动租户过滤。"""
    tcond, tparams = tenant_filter_clause()
    async with async_session_factory() as session:
        result = await session.execute(
            text(f"SELECT key, value FROM user_preferences WHERE user_id = :user_id AND {tcond}"),
            {"user_id": user_id, **tparams},
        )
        rows = result.mappings().all()
        return {row["key"]: row["value"] for row in rows}


async def delete_preference(user_id: str, key: str) -> bool:
    """删除单条用户偏好，返回是否删除了记录。自动租户过滤。"""
    tcond, tparams = tenant_filter_clause()
    async with async_session_factory() as session:
        result = await session.execute(
            text(f"DELETE FROM user_preferences WHERE user_id = :user_id AND key = :key AND {tcond}"),
            {"user_id": user_id, "key": key, **tparams},
        )
        await session.commit()
        return result.rowcount > 0  # type: ignore[no-any-return]
