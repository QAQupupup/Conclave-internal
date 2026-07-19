# §4 WebSocket 事件：DomainEvent + InMemoryEventBus
from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

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
    """内存事件总线 + PostgreSQL 持久化（重启不丢事件）

    事件同时写入内存缓存和 PostgreSQL，重启后从 PostgreSQL 恢复。
    后期换 RedisEventBus / MQ 不改上层调用。

    内存安全：
    - 单会议事件历史上限 _MAX_HISTORY_PER_MEETING=1000，超过自动裁剪最旧事件
    - clear() 清理内存历史
    - unsubscribe 后自动清理空的订阅列表
    """

    _MAX_HISTORY_PER_MEETING = 1000

    def __init__(self) -> None:
        # topic -> 订阅者列表
        self._subs: dict[str, list[Subscriber]] = {}
        # meeting_id -> 最近事件缓存，供 WS 新连接回放
        self._history: dict[str, list[DomainEvent]] = {}

    async def publish(self, event: DomainEvent) -> None:
        """发布事件：写入 PostgreSQL + 内存缓存，广播给订阅者"""
        import logging

        from app.db_legacy import save_event

        logger = logging.getLogger(__name__)
        ts_str = event.ts.isoformat() if hasattr(event.ts, "isoformat") else str(event.ts)
        try:
            db_seq = await save_event(
                meeting_id=event.meeting_id,
                event_type=event.type,
                payload=event.payload,
                ts=ts_str,
                trace_id=event.trace_id,
            )
            event.seq = db_seq
        except Exception as e:
            logger.error(
                "Failed to persist event to DB: meeting_id=%s type=%s error=%s: %s",
                event.meeting_id,
                event.type,
                type(e).__name__,
                str(e)[:200],
            )
            try:
                from app.observability.audit import audit

                audit(
                    "system.error",
                    "error",
                    {
                        "component": "event_bus",
                        "operation": "persist_event",
                        "event_type": event.type,
                        "meeting_id": event.meeting_id,
                        "error_type": type(e).__name__,
                        "error": str(e)[:300],
                    },
                )
            except Exception:
                pass
            fallback = self._history.get(event.meeting_id, [])
            event.seq = (fallback[-1].seq + 1) if fallback else 0

        # 写入内存历史，按 seq 排序保证并发场景下顺序一致
        history = self._history.setdefault(event.meeting_id, [])
        history.append(event)
        history.sort(key=lambda e: e.seq)
        if len(history) > self._MAX_HISTORY_PER_MEETING:
            del history[: len(history) - self._MAX_HISTORY_PER_MEETING]

        # 广播给订阅者
        for sub in list(self._subs.get(event.meeting_id, [])):
            try:
                await sub(event)
            except Exception as e:
                logger.warning(
                    "Event subscriber failed for meeting=%s type=%s: %s: %s",
                    event.meeting_id,
                    event.type,
                    type(e).__name__,
                    str(e)[:200],
                )
        if event.meeting_id != "*":
            for sub in list(self._subs.get("*", [])):
                try:
                    await sub(event)
                except Exception as e:
                    logger.warning(
                        "Wildcard event subscriber failed for meeting=%s type=%s: %s: %s",
                        event.meeting_id,
                        event.type,
                        type(e).__name__,
                        str(e)[:200],
                    )

    def subscribe(self, meeting_id: str, handler: Subscriber) -> Callable[[], None]:
        """订阅指定会议的事件，返回取消订阅函数"""
        self._subs.setdefault(meeting_id, []).append(handler)

        def _unsubscribe() -> None:
            try:
                subs = self._subs.get(meeting_id)
                if subs is not None:
                    subs.remove(handler)
                    # 清理空列表，防止字典只增不减
                    if not subs:
                        self._subs.pop(meeting_id, None)
            except ValueError:
                pass

        return _unsubscribe

    async def history(self, meeting_id: str) -> list[DomainEvent]:
        """取某会议已发布事件，优先从内存取，内存空则从 PostgreSQL 恢复（异步）"""
        mem_events = self._history.get(meeting_id)
        if mem_events:
            return list(mem_events)
        # 内存无缓存，从 PostgreSQL 恢复
        return await self._restore_from_db(meeting_id)

    def get_events(self, meeting_id: str) -> list[DomainEvent]:
        """同步获取事件：优先内存，内存空时通过 asyncio.run 从 DB 加载"""
        mem_events = self._history.get(meeting_id)
        if mem_events:
            return list(mem_events)
        import asyncio as _asyncio
        try:
            _loop = _asyncio.get_running_loop()
        except RuntimeError:
            _loop = None
        if _loop is None:
            return _asyncio.run(self._restore_from_db(meeting_id))
        # 在异步上下文中被同步调用，返回内存副本或空列表
        return []

    async def replay(self, meeting_id: str, from_seq: int = 0) -> list[DomainEvent]:
        """增量回放：from_seq=0 返回全部事件，from_seq>0 返回 seq > from_seq 的事件（异步）"""
        events = self._history.get(meeting_id)
        if not events:
            # 内存无缓存，从 PostgreSQL 恢复
            events = await self._restore_from_db(meeting_id)
        if from_seq <= 0:
            return list(events)
        return [e for e in events if e.seq > from_seq]

    def replay_sync(self, meeting_id: str, from_seq: int = 0) -> list[DomainEvent]:
        """同步版本的 replay"""
        events = self.get_events(meeting_id)
        if from_seq <= 0:
            return list(events)
        return [e for e in events if e.seq > from_seq]

    async def last_seq(self, meeting_id: str) -> int:
        """取某会议最后一条事件的 seq，无事件返回 0（异步）"""
        events = self._history.get(meeting_id)
        if events:
            return events[-1].seq
        # 内存无缓存，从 PostgreSQL 取
        from app.db_legacy import last_event_seq

        return await last_event_seq(meeting_id)

    def last_seq_sync(self, meeting_id: str) -> int:
        """同步版本的 last_seq"""
        events = self._history.get(meeting_id)
        if events:
            return events[-1].seq
        import asyncio as _asyncio
        try:
            _loop = _asyncio.get_running_loop()
        except RuntimeError:
            _loop = None
        if _loop is None:
            from app.db_legacy import last_event_seq as _les
            return _asyncio.run(_les(meeting_id))
        return 0

    def clear(self, meeting_id: str) -> None:
        """清理某会议的内存缓存（PostgreSQL 保留）"""
        self._history.pop(meeting_id, None)

    async def _restore_from_db(self, meeting_id: str) -> list[DomainEvent]:
        """从 PostgreSQL 恢复事件到内存缓存（限制最近 _MAX_HISTORY_PER_MEETING 条）"""
        from app.db_legacy import load_events

        rows = await load_events(meeting_id, from_seq=0, limit=self._MAX_HISTORY_PER_MEETING)
        events = []
        for row in rows:
            try:
                ts = datetime.fromisoformat(row["ts"])
            except (ValueError, TypeError):
                ts = datetime.now(timezone.utc)
            events.append(
                DomainEvent(
                    type=row["type"],
                    meeting_id=row["meeting_id"],
                    payload=row["payload"],
                    ts=ts,
                    trace_id=row.get("trace_id"),
                    seq=row["seq"],
                )
            )
        # 缓存到内存
        if events:
            self._history[meeting_id] = events
        return events


# 进程级单例事件总线
bus = InMemoryEventBus()


def make_event(
    event_type: str,
    meeting_id: str,
    payload: dict[str, Any],
    trace_id: str | None = None,
) -> DomainEvent:
    """构造领域事件的便捷工厂

    trace_id 未传时，自动从追踪上下文取 request_id，
    确保事件与触发它的 HTTP 请求关联。
    """
    if trace_id is None:
        # 从追踪上下文取 request_id（异步安全）
        from app.context import get_request_id

        rid = get_request_id()
        trace_id = rid if rid != "-" else None

    return DomainEvent(
        type=event_type,
        meeting_id=meeting_id,
        payload=payload,
        ts=datetime.now(timezone.utc),
        trace_id=trace_id,
    )
