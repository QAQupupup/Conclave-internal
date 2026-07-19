"""懒加载 asyncio 原语（Lock/Semaphore），自动处理事件循环绑定问题。

在测试场景中，每个 TestClient 使用独立的事件循环，而模块级 asyncio.Lock()
在导入时绑定到第一个循环，后续在不同循环中使用会报 "attached to a different loop"。
本模块提供 LazyLock / LazySemaphore，在首次访问时绑定到当前循环，
并在检测到循环变化时自动重建。
"""
from __future__ import annotations

import asyncio
from typing import Any, cast


class _LazyAsyncPrimitive:
    """懒加载 asyncio 原语基类。"""

    _primitive: Any = None
    _loop: asyncio.AbstractEventLoop | None = None

    def _get_loop(self) -> asyncio.AbstractEventLoop | None:
        try:
            loop = asyncio.get_running_loop()
            if loop.is_closed():
                return None
            return loop
        except RuntimeError:
            return None

    def _ensure(self) -> Any:
        cur_loop = self._get_loop()
        need_new = (
            self._primitive is None
            or self._loop is None
            or self._loop.is_closed()
            or cur_loop is None
            or self._loop is not cur_loop
        )
        if need_new:
            self._primitive = self._create()
            self._loop = cur_loop
        return self._primitive

    def _create(self) -> Any:  # pragma: no cover - 子类实现
        raise NotImplementedError

    def __aenter__(self) -> Any:
        return self._ensure().__aenter__()

    def __aexit__(self, *args: Any) -> Any:
        return self._ensure().__aexit__(*args)


class LazyLock(_LazyAsyncPrimitive):
    """懒加载 asyncio.Lock，自动绑定当前事件循环。"""

    def _create(self) -> asyncio.Lock:
        return asyncio.Lock()

    async def acquire(self) -> bool:
        return cast(bool, await self._ensure().acquire())

    def release(self) -> None:
        self._ensure().release()

    def locked(self) -> bool:
        lock = self._ensure()
        return cast(bool, lock.locked())


class LazySemaphore(_LazyAsyncPrimitive):
    """懒加载 asyncio.Semaphore，自动绑定当前事件循环。"""

    def __init__(self, value: int = 1) -> None:
        self._value = value

    def _create(self) -> asyncio.Semaphore:
        return asyncio.Semaphore(self._value)

    async def acquire(self) -> bool:
        return cast(bool, await self._ensure().acquire())

    def release(self) -> None:
        self._ensure().release()
