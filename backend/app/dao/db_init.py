"""数据库连接池管理（手写建表 DDL 已废弃）。

建表统一由单一入口负责：
- 有 ORM 模型的表：`Base.metadata.create_all()`（见 app/main.py lifespan / conftest）
- 增量 schema 变更：Alembic 迁移（backend/alembic/versions/）

历史遗留：init_db() 曾手写 legacy 表 DDL（meetings/messages/events 等），
现已成为与 ORM/Alembic "双源真相"的冲突源，已于 2026-08 废弃
（见 docs/sql-development-rules.md §5 原生 SQL 例外）。
"""

from __future__ import annotations

from app.db.engine import get_engine


async def close_db_pool() -> None:
    """关闭连接池，主要用于测试清理。"""
    engine = await get_engine()
    await engine.dispose()


async def init_db() -> None:
    """[已废弃] 建表由 Base.metadata.create_all() + Alembic 单入口负责。

    保留此函数仅为兼容旧调用点（app/main.py lifespan / conftest.py），
    不再执行任何手写 DDL。
    """
    # no-op：历史手写 legacy 表 DDL 已移除（2026-08）。
    # 建表交由 Base.metadata.create_all()（新库）与 Alembic 迁移（增量）完成。
