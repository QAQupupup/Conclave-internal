"""SQLAlchemy 方言感知的 upsert 工具。

[CON-16 修复] 旧版 sqlalchemy_repo.py 在所有 save() 中硬编码使用
`from sqlalchemy.dialects.postgresql import insert as pg_insert`，
没有根据当前数据库方言选择。当 db_mode=sqlite（开发）时硬编码 PG 方言
会导致 Insert 对象走 PostgreSQL 编译器、行为异常。

本模块提供 `dialect_upsert(session, model, values, index_elements, set_)`，
自动根据当前 session 的 dialect 选择合适的 insert 实现：
- postgresql → ON CONFLICT ... DO UPDATE
- sqlite     → ON CONFLICT ... DO UPDATE (SQLite ≥ 3.24)
- mysql      → ON DUPLICATE KEY UPDATE
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

from sqlalchemy.ext.asyncio import AsyncSession


def dialect_upsert(
    session: AsyncSession,
    model: type,
    values: Mapping[str, Any],
    *,
    index_elements: Sequence[str],
    set_: Mapping[str, Any] | None = None,
) -> Any:
    """根据当前 session 的方言返回合适的 upsert 语句。

    Args:
        session: AsyncSession
        model: ORM 模型类
        values: 要插入的字段值（dict）
        index_elements: 唯一键列名列表（用于冲突判定）
        set_: 冲突时更新的字段值（dict），None 表示不做更新（纯 insert）

    Returns:
        SQLAlchemy statement，可直接 await session.execute(stmt)
    """
    bind = session.get_bind()
    dialect_name = bind.dialect.name if bind is not None else "default"

    if dialect_name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        stmt = pg_insert(model).values(**values)
        if set_ is not None:
            stmt = stmt.on_conflict_do_update(index_elements=list(index_elements), set_=set_)
        return stmt

    if dialect_name == "sqlite":
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        stmt = sqlite_insert(model).values(**values)
        if set_ is not None:
            stmt = stmt.on_conflict_do_update(index_elements=list(index_elements), set_=set_)
        return stmt

    if dialect_name == "mysql":
        from sqlalchemy.dialects.mysql import insert as mysql_insert

        stmt = mysql_insert(model).values(**values)
        if set_ is not None:
            # MySQL 用 ON DUPLICATE KEY UPDATE，参数是 (set_,) 元组
            stmt = stmt.on_duplicate_key_update(**set_)
        return stmt

    # 兜底：用通用 Insert（不支持 upsert，调用方需自己 try/except）
    # 在不支持 upsert 的方言上，会因主键冲突抛 IntegrityError
    from sqlalchemy import insert as generic_insert

    return generic_insert(model).values(**values)


def is_upsert_supported(session: AsyncSession) -> bool:
    """判断当前方言是否支持 upsert。"""
    bind = session.get_bind()
    if bind is None:
        return False
    name = bind.dialect.name
    return name in ("postgresql", "sqlite", "mysql")
