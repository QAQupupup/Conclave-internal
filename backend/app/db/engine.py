"""异步数据库引擎 + 会话工厂。

支持 SQLite（开发）和 PostgreSQL（生产）双后端，由 DATABASE_URL 自动切换。
"""
from __future__ import annotations

import asyncio

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)
from app.config import settings

# 根据 DATABASE_URL 自动选择驱动
# PostgreSQL: postgresql+asyncpg://user:pass@host:5432/db
# SQLite:      sqlite+aiosqlite:///conclave.db
_database_url = settings.database_url


def _create_async_engine(url: str) -> AsyncEngine:
    """根据 URL 创建合适的异步引擎。"""
    # SQLite 需要特殊配置：关闭连接池（单文件），开启 WAL 外键
    if url.startswith("sqlite"):
        return create_async_engine(
            url,
            echo=False,
            poolclass=None,  # SQLite 不需要连接池
            connect_args={"check_same_thread": False},
        )
    return create_async_engine(
        url,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,
        pool_recycle=3600,
        echo=False,
    )


_engine: AsyncEngine | None = _create_async_engine(_database_url)


def _ensure_engine() -> AsyncEngine:
    """返回当前引擎；如已被 dispose，则重新创建。"""
    global _engine
    if _engine is None:
        _engine = _create_async_engine(_database_url)
    return _engine


class _LazyAsyncSessionFactory:
    """延迟绑定到当前 engine 的会话工厂，支持 dispose 后重建。"""

    def __call__(self, **kwargs) -> AsyncSession:
        return async_sessionmaker(
            _ensure_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
            **kwargs,
        )()


# 异步会话工厂（延迟绑定，dispose 后可重建）
async_session_factory = _LazyAsyncSessionFactory()


async def get_engine():
    """获取异步引擎（用于 Alembic 等场景）"""
    return _ensure_engine()


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


def dispose_async_engine() -> None:
    """释放当前异步引擎并将其置为 None，使下次访问时重建。

    主要用于测试隔离，避免连接池跨测试泄漏。
    """
    global _engine
    if _engine is not None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is None:
            asyncio.run(_engine.dispose())
        else:
            # 当前线程已有事件循环，另起线程执行 dispose
            import threading

            def _dispose() -> None:
                asyncio.run(_engine.dispose())

            t = threading.Thread(target=_dispose)
            t.start()
            t.join(timeout=30)
        _engine = None
