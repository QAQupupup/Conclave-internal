"""PluginEventBus 单元测试。"""
from __future__ import annotations

import pytest

from app.plugins.core.event_bus import PluginEvent, PluginEventBus


@pytest.fixture
def bus():
    return PluginEventBus()


async def test_subscribe_publish(bus):
    received: list[PluginEvent] = []

    async def handler(ev: PluginEvent) -> None:
        received.append(ev)

    bus.subscribe("user.created", handler)
    await bus.publish(PluginEvent(type="user.created", payload={"id": 1}))
    assert len(received) == 1
    assert received[0].payload["id"] == 1


async def test_multiple_subscribers_all_called(bus):
    calls: list[str] = []

    async def h1(ev):
        calls.append("h1")

    async def h2(ev):
        calls.append("h2")

    bus.subscribe("e", h1)
    bus.subscribe("e", h2)
    await bus.publish(PluginEvent(type="e"))
    assert set(calls) == {"h1", "h2"}


async def test_unsubscribe(bus):
    calls = []

    async def h(ev):
        calls.append(1)

    unsub = bus.subscribe("e", h)
    unsub()
    await bus.publish(PluginEvent(type="e"))
    assert calls == []


async def test_handler_exception_isolated(bus):
    """单个 handler 抛异常不影响其他 handler。"""
    calls = []

    async def bad(ev):
        raise RuntimeError("boom")

    async def good(ev):
        calls.append(1)

    bus.subscribe("e", bad)
    bus.subscribe("e", good)
    # 不应抛出
    await bus.publish(PluginEvent(type="e"))
    assert calls == [1]


async def test_no_handler_no_op(bus):
    # 无订阅者时 publish 不抛
    await bus.publish(PluginEvent(type="nope"))


async def test_unsubscribe_all(bus):
    async def h(ev):
        pass

    bus.subscribe("e", h)
    bus.unsubscribe_all()
    await bus.publish(PluginEvent(type="e"))
    # 无异常即通过
