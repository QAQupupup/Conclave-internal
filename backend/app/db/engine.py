"""异步数据库引擎 + 会话工厂。

支持 SQLite（开发）和 PostgreSQL（生产）双后端，由 DATABASE_URL 自动切换。
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from app.config import settings

# 根据 DATABASE_URL 自动选择驱动
# PostgreSQL: postgresql+asyncpg://user:pass@host:5432/db
# SQLite:      sqlite+aiosqlite:///conclave.db
_database_url = settings.database_url

# SQLite 需要特殊配置：关闭连接池（单文件），开启 WAL 外键
if _database_url.startswith("sqlite"):
    _engine = create_async_engine(
        _database_url,
        echo=False,
        poolclass=None,  # SQLite 不需要连接池
        connect_args={"check_same_thread": False},
    )
else:
    _engine = create_async_engine(
        _database_url,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,
        pool_recycle=3600,
        echo=False,
    )

# 异步会话工厂
async_session_factory = async_sessionmaker(
    _engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_engine():
    """获取异步引擎（用于 Alembic 等场景）"""
    return _engine


async def get_db():
    """FastAPI 依赖注入：每个请求一个独立会话，自动提交/回滚。"""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()