# §4 WebSocket 事件：DomainEvent + InMemoryEventBus
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from pydantic import BaseModel


class DomainEvent(BaseModel):
    """领域事件，所有 WS 推送与内部通信的统一信封"""
    type: str
    meeting_id: str
    payload: dict[str, Any]
    ts: datetime
    trace_id: str | None = None
    seq: int = 0  # 事件序列号，按 meeting_id 自增（0 开始）


# 订阅者签名：async def handler(event: DomainEvent) -> None
Subscriber = Callable[[DomainEvent], Awaitable[None]]


class InMemoryEventBus:
    """内存事件总线，后期换 RedisEventBus / MQ 不改上层调用"""

    def __init__(self) -> None:
        # topic -> 订阅者列表
        self._subs: dict[str, list[Subscriber]] = {}
        # meeting_id -> 最近事件缓存，供 WS 新连接回放
        self._history: dict[str, list[DomainEvent]] = {}

    async def publish(self, event: DomainEvent) -> None:
        """发布事件：广播给所有订阅者，并写入历史缓存"""
        # 设置序列号（基于当前历史长度，从 0 自增）
        event.seq = len(self._history.get(event.meeting_id, []))
        # 写入历史
        self._history.setdefault(event.meeting_id, []).append(event)
        # 广播给 topic 级订阅者
        for sub in list(self._subs.get(event.meeting_id, [])):
            try:
                await sub(event)
            except Exception:  # noqa: BLE001 单个订阅者失败不影响其它
                pass
        # 广播给通配订阅者
        for sub in list(self._subs.get("*", [])):
            try:
                await sub(event)
            except Exception:  # noqa: BLE001
                pass

    def subscribe(self, meeting_id: str, handler: Subscriber) -> Callable[[], None]:
        """订阅指定会议的事件，返回取消订阅函数"""
        self._subs.setdefault(meeting_id, []).append(handler)

        def _unsubscribe() -> None:
            try:
                self._subs[meeting_id].remove(handler)
            except ValueError:
                pass

        return _unsubscribe

    def history(self, meeting_id: str) -> list[DomainEvent]:
        """取某会议已发布事件，供 WS 新连接回放"""
        return list(self._history.get(meeting_id, []))

    def replay(self, meeting_id: str, from_seq: int = 0) -> list[DomainEvent]:
        """增量回放：from_seq=0 返回全部事件，from_seq>0 返回 seq > from_seq 的事件"""
        events = self._history.get(meeting_id, [])
        if from_seq <= 0:
            return list(events)
        return [e for e in events if e.seq > from_seq]

    def last_seq(self, meeting_id: str) -> int:
        """取某会议最后一条事件的 seq，无事件返回 0"""
        events = self._history.get(meeting_id, [])
        return events[-1].seq if events else 0

    def clear(self, meeting_id: str) -> None:
        """清理某会议的历史缓存"""
        self._history.pop(meeting_id, None)


# 进程级单例事件总线
bus = InMemoryEventBus()


def make_event(
    event_type: str,
    meeting_id: str,
    payload: dict[str, Any],
    trace_id: str | None = None,
) -> DomainEvent:
    """构造领域事件的便捷工厂"""
    return DomainEvent(
        type=event_type,
        meeting_id=meeting_id,
        payload=payload,
        ts=datetime.now(timezone.utc),
        trace_id=trace_id,
    )
