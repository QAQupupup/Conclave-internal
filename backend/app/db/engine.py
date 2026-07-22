"""异步数据库引擎 + 会话工厂。

仅支持 PostgreSQL 后端，由 DATABASE_URL 配置。
支持跨事件循环自动重建引擎（测试隔离场景）。
"""

from __future__ import annotations

import asyncio
import contextlib
import threading

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings

# PostgreSQL: postgresql+asyncpg://user:pass@host:5432/db
_database_url = settings.database_url


def _create_async_engine(url: str) -> AsyncEngine:
    """创建 PostgreSQL 异步引擎。"""
    return create_async_engine(
        url,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,
        pool_recycle=3600,
        echo=False,
    )


_engine: AsyncEngine | None = None
_engine_loop: asyncio.AbstractEventLoop | None = None
_engine_lock = threading.Lock()


def _ensure_engine() -> AsyncEngine:
    """返回当前引擎；如已 dispose、未初始化或绑定到不同/已关闭循环，则重建。"""
    global _engine, _engine_loop
    try:
        cur_loop = asyncio.get_running_loop()
    except RuntimeError:
        cur_loop = None
    # 检测是否需要重建引擎：
    # 1. 引擎不存在
    # 2. 之前记录的循环已关闭
    # 3. 当前循环与之前不同（id 不同或者是不同对象）
    need_new = (
        _engine is None
        or _engine_loop is None
        or _engine_loop.is_closed()
        or cur_loop is None
        or _engine_loop is not cur_loop
    )
    if need_new:
        with _engine_lock:
            # double-check
            try:
                cur_loop = asyncio.get_running_loop()
            except RuntimeError:
                cur_loop = None
            need_new = (
                _engine is None
                or _engine_loop is None
                or _engine_loop.is_closed()
                or cur_loop is None
                or _engine_loop is not cur_loop
            )
            if need_new:
                # 循环变化时直接丢弃旧引擎引用（GC 会回收）
                # 生产环境只有一个事件循环，不会走到这里；仅测试场景（多次 asyncio.run）触发
                _engine = _create_async_engine(_database_url)
                _engine_loop = cur_loop
    assert _engine is not None
    return _engine


class _LazyAsyncSessionFactory:
    """延迟绑定到当前 engine 的会话工厂，支持 dispose / 循环切换后重建。"""

    def __call__(self, **kwargs) -> AsyncSession:
        return async_sessionmaker(
            _ensure_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
            **kwargs,
        )()


# 异步会话工厂（延迟绑定，dispose / 循环切换后可重建）
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
    global _engine, _engine_loop
    with _engine_lock:
        engine_to_dispose = _engine
        _engine = None
        _engine_loop = None
    if engine_to_dispose is not None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        try:
            if loop is None or loop.is_closed():
                asyncio.run(engine_to_dispose.dispose())
            else:
                # 当前线程已有事件循环，另起线程执行 dispose
                def _dispose() -> None:
                    with contextlib.suppress(Exception):
                        asyncio.run(engine_to_dispose.dispose())

                t = threading.Thread(target=_dispose)
                t.start()
                t.join(timeout=5)
        except Exception:
            pass
