"""插件间事件总线。

注意：此 EventBus 与 app/events.py（InMemoryEventBus + DomainEvent，用于 WS 推送）
是两个独立的总线。现有 events.py 继续服务 WebSocket 实时推送；本 EventBus 专门
用于插件间解耦通信，不持久化、不用于 WS。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("plugins.event_bus")

EventHandler = Callable[["PluginEvent"], Awaitable[None]]


@dataclass
class PluginEvent:
    """插件间通信事件。"""

    type: str
    payload: dict[str, Any] = field(default_factory=dict)
    ts: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    source_plugin: str = ""
    request_id: str = ""


class PluginEventBus:
    """插件间事件总线：简单 pub/sub，异步派发，不持久化。

    - subscribe(event_type, handler) 返回取消订阅函数
    - publish(event) 并发通知所有订阅者，异常隔离（单 handler 失败不影响其他）
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler]] = {}

    def subscribe(self, event_type: str, handler: EventHandler) -> Callable[[], None]:
        """订阅事件，返回取消订阅函数。"""
        self._handlers.setdefault(event_type, []).append(handler)

        def _unsub() -> None:
            try:
                self._handlers[event_type].remove(handler)
                if not self._handlers[event_type]:
                    del self._handlers[event_type]
            except (ValueError, KeyError):
                pass

        return _unsub

    async def publish(self, event: PluginEvent) -> None:
        """发布事件：并发通知所有订阅者，异常隔离。"""
        handlers = list(self._handlers.get(event.type, []))
        if not handlers:
            return
        results = await asyncio.gather(*[h(event) for h in handlers], return_exceptions=True)
        for h, r in zip(handlers, results, strict=True):
            if isinstance(r, Exception):
                logger.warning(
                    "Plugin event handler %s for event '%s' failed: %s",
                    getattr(h, "__qualname__", h),
                    event.type,
                    r,
                )

    def unsubscribe_all(self) -> None:
        """移除所有订阅者（测试/关闭时使用）。"""
        self._handlers.clear()
