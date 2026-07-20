"""插件测试公共 fixtures 和 mock 插件类。"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import pytest

from app.plugins.core.types import (
    PluginContext,
    PluginHealth,
    PluginTier,
)


@dataclass
class _CallRecord:
    """记录钩子/生命周期调用顺序，用于断言。"""

    calls: list[tuple[str, str]] = field(default_factory=list)

    def record(self, plugin: str, hook: str) -> None:
        self.calls.append((plugin, hook))

    def reset(self) -> None:
        self.calls.clear()

    def names_for(self, hook: str) -> list[str]:
        return [p for p, h in self.calls if h == hook]


class _MockPluginBase:
    """Mock 插件基类，实现 PluginBase Protocol 所需属性 + LifecycleMixin。"""

    name: str = "mock"
    version: str = "1.0.0"
    tier: PluginTier = PluginTier.OPTIONAL
    dependencies: list[str]
    priority: int = 100

    def __init__(
        self,
        name: str = "mock",
        tier: PluginTier = PluginTier.OPTIONAL,
        dependencies: list[str] | None = None,
        priority: int = 100,
        *,
        startup_sleep: float = 0,
        startup_raise: Exception | None = None,
        shutdown_raise: Exception | None = None,
        health_result: PluginHealth | None = None,
    ) -> None:
        self.name = name
        self.tier = tier
        self.version = "1.0.0"
        self.dependencies = dependencies or []
        self.priority = priority
        self.startup_sleep = startup_sleep
        self.startup_raise = startup_raise
        self.shutdown_raise = shutdown_raise
        self.health_result = health_result or PluginHealth(healthy=True)
        # 可由外部注入 recorder
        self.recorder: _CallRecord | None = None

    async def on_startup(self, ctx: PluginContext) -> None:
        if self.recorder:
            self.recorder.record(self.name, "on_startup")
        if self.startup_sleep:
            await asyncio.sleep(self.startup_sleep)
        if self.startup_raise:
            raise self.startup_raise

    async def on_shutdown(self, ctx: PluginContext) -> None:
        if self.recorder:
            self.recorder.record(self.name, "on_shutdown")
        if self.shutdown_raise:
            raise self.shutdown_raise

    async def health_check(self) -> PluginHealth:
        if self.recorder:
            self.recorder.record(self.name, "health_check")
        return self.health_result


class _InterceptorPlugin(_MockPluginBase):
    """带拦截型钩子的 mock 插件（on_meeting_creating 语义）。"""

    def __init__(self, *args: Any, hook_result: Any = None, hook_sleep: float = 0, hook_raise: Exception | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._hook_result = hook_result
        self._hook_sleep = hook_sleep
        self._hook_raise = hook_raise
        self.hook_called = 0

    async def on_meeting_creating(self, ctx: PluginContext, payload: dict) -> Any:
        self.hook_called += 1
        if self.recorder:
            self.recorder.record(self.name, "on_meeting_creating")
        if self._hook_sleep:
            await asyncio.sleep(self._hook_sleep)
        if self._hook_raise:
            raise self._hook_raise
        return self._hook_result


class _ObserverPlugin(_MockPluginBase):
    """带观察型钩子的 mock 插件。"""

    def __init__(self, *args: Any, hook_sleep: float = 0, hook_raise: Exception | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._hook_sleep = hook_sleep
        self._hook_raise = hook_raise
        self.hook_called = 0
        self.last_payload: dict | None = None

    async def on_meeting_created(self, ctx: PluginContext, payload: dict) -> None:
        self.hook_called += 1
        self.last_payload = payload
        if self.recorder:
            self.recorder.record(self.name, "on_meeting_created")
        if self._hook_sleep:
            await asyncio.sleep(self._hook_sleep)
        if self._hook_raise:
            raise self._hook_raise


@pytest.fixture
def call_recorder() -> _CallRecord:
    return _CallRecord()


@pytest.fixture
def make_mock_plugin(call_recorder: _CallRecord):
    """工厂：创建带 recorder 的 _MockPluginBase 实例。"""

    def _make(
        name: str = "mock",
        tier: PluginTier = PluginTier.OPTIONAL,
        dependencies: list[str] | None = None,
        priority: int = 100,
        **kwargs: Any,
    ) -> _MockPluginBase:
        p = _MockPluginBase(name=name, tier=tier, dependencies=dependencies, priority=priority, **kwargs)
        p.recorder = call_recorder
        return p

    return _make


@pytest.fixture
def make_interceptor(call_recorder: _CallRecord):
    def _make(name: str = "intercept", tier: PluginTier = PluginTier.OPTIONAL, hook_result: Any = None, **kwargs: Any) -> _InterceptorPlugin:
        p = _InterceptorPlugin(name=name, tier=tier, hook_result=hook_result, **kwargs)
        p.recorder = call_recorder
        return p

    return _make


@pytest.fixture
def make_observer(call_recorder: _CallRecord):
    def _make(name: str = "observe", tier: PluginTier = PluginTier.OPTIONAL, **kwargs: Any) -> _ObserverPlugin:
        p = _ObserverPlugin(name=name, tier=tier, **kwargs)
        p.recorder = call_recorder
        return p

    return _make


@pytest.fixture
def empty_registry():
    """提供一个空 PluginRegistry（hook_timeout=50ms 加快测试）。"""
    from app.plugins.core.registry import PluginRegistry

    return PluginRegistry(hook_timeout_ms=50)


@pytest.fixture
def tmp_ctx(empty_registry):
    return PluginContext(app=None, registry=empty_registry, event_bus=empty_registry.event_bus)
