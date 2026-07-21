# §4 WebSocket 事件：DomainEvent + InMemoryEventBus
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)

# 进程实例 ID，用于 Redis Pub/Sub 回环防护
instance_id = str(uuid.uuid4())

# Redis Pub/Sub 频道常量
_REDIS_CHANNEL_PREFIX = "conclave:events:"
_REDIS_CHANNEL_PATTERN = "conclave:events:*"
_REDIS_SYSTEM_CHANNEL = "conclave:events:__system__"


class DomainEvent(BaseModel):
    """领域事件，所有 WS 推送与内部通信的统一信封

    schema_version: 事件载荷 schema 版本，默认 "1.0"。
        旧事件（DB 中持久化的数据）可能不含该字段，反序列化时自动补 "1.0"。
        未来不兼容变更时递增主版本号（如 "2.0"），消费者据此做迁移。
    """

    model_config = {"populate_by_name": True, "extra": "allow"}

    type: str
    meeting_id: str
    payload: dict[str, Any]
    schema_version: str = "1.0"
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
        # Redis Pub/Sub 桥接相关（循环感知，遵循 AGENTS.md §4.1）
        self._instance_id = instance_id  # 进程标识，防止回环
        self._redis_listener_task: asyncio.Task | None = None
        self._redis_pubsub: Any = None  # Redis pubsub 对象（延迟初始化）
        self._loop: asyncio.AbstractEventLoop | None = None  # Redis 桥接绑定的事件循环

    def _redis_available(self) -> bool:
        """检查 Redis 桥接是否在当前循环下可用。

        循环已关闭/切换/不存在时返回 False，避免 "attached to a different loop"。
        """
        if self._loop is None or self._redis_pubsub is None:
            return False
        if self._loop.is_closed():
            return False
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            return False
        return current_loop is self._loop

    def _detach_redis_state(self) -> None:
        """丢弃 Redis 相关状态引用（不做跨循环 await）。

        在检测到循环切换/关闭时调用，只清除引用让 GC 回收，
        符合 AGENTS.md §4.1 规则 3：不要在同步代码中跨循环释放资源。
        """
        self._redis_listener_task = None
        self._redis_pubsub = None
        self._loop = None

    async def publish(self, event: DomainEvent) -> None:
        """发布事件：写入 PostgreSQL + 内存缓存，广播给订阅者，并通过 Redis 跨实例广播"""
        from app.db_legacy import save_event

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

        # 本地分发：写入内存历史 + 通知订阅者
        await self._local_dispatch(event)

        # Redis Pub/Sub 跨实例广播
        await self._redis_publish(event)

    async def _local_dispatch(self, event: DomainEvent) -> None:
        """将事件写入内存历史并通知本地订阅者。

        供 publish()（本地发布）和 _redis_listener()（收到远程事件）共同调用。
        不涉及 DB 写入和 Redis 广播——仅内存历史追加 + 同步顺序 await 订阅者。
        """
        # 写入内存历史，按 seq 排序保证并发场景下顺序一致
        history = self._history.setdefault(event.meeting_id, [])
        # 去重：如果已存在相同 seq 的事件，跳过（防止 Redis 消息重复投递）
        for existing in history:
            if existing.seq == event.seq:
                return
        history.append(event)
        history.sort(key=lambda e: e.seq)
        if len(history) > self._MAX_HISTORY_PER_MEETING:
            del history[: len(history) - self._MAX_HISTORY_PER_MEETING]

        # 广播给该会议的订阅者
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
        # 广播给通配符订阅者（系统级事件不再重复通知）
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

    async def _redis_publish(self, event: DomainEvent) -> None:
        """将事件 PUBLISH 到 Redis（Redis 不可用/循环不匹配时静默降级）。"""
        # 循环感知检查：不在当前循环绑定的 Redis 桥上做任何 await
        if not self._redis_available():
            return
        try:
            # 延迟 import，避免模块加载时 Redis 未初始化
            from app.db.redis import get_redis_client

            redis_client = get_redis_client()
            if redis_client is None:
                return

            # 确定 Redis channel
            channel = _REDIS_SYSTEM_CHANNEL if event.meeting_id == "*" else f"{_REDIS_CHANNEL_PREFIX}{event.meeting_id}"

            # 消息体：instance_id + 事件 JSON（用 pydantic 原生序列化）
            payload = json.dumps(
                {
                    "instance_id": self._instance_id,
                    "event": event.model_dump_json(),
                }
            )
            await redis_client.publish(channel, payload)
        except RuntimeError as e:
            # "Event loop is closed" / "attached to a different loop" —— 静默降级
            # 这是测试/关闭场景的正常情况，不输出 WARNING 避免噪声
            if "loop" not in str(e).lower():
                logger.warning(
                    "Redis PUBLISH 失败（降级）: meeting=%s type=%s: %s",
                    event.meeting_id,
                    event.type,
                    str(e)[:200],
                )
            # 标记桥接已失效，后续调用直接走降级路径
            self._detach_redis_state()
        except Exception as e:
            logger.warning(
                "Redis PUBLISH failed (graceful degradation): meeting=%s type=%s: %s",
                event.meeting_id,
                event.type,
                str(e)[:200],
            )

    async def start(self) -> None:
        """启动 Redis Pub/Sub 监听（Redis 不可用时静默降级为纯内存模式）。

        循环感知：若检测到当前循环与已绑定循环不同，先丢弃旧状态（不跨循环 await），
        再在新循环上重新启动。
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return  # 无运行中循环，不能启动

        # 如果已有绑定且是同一循环，幂等返回
        if self._loop is loop and self._redis_pubsub is not None:
            return

        # 循环已切换或首次启动：丢弃旧状态引用（不跨循环 await 关闭）
        self._detach_redis_state()

        try:
            from app.db.redis import get_redis_client

            redis_client = get_redis_client()
            if redis_client is None:
                logger.info("Redis 不可用，事件总线以纯内存模式运行")
                return

            # 创建 pubsub 并订阅 pattern
            self._redis_pubsub = redis_client.pubsub()
            await self._redis_pubsub.psubscribe(_REDIS_CHANNEL_PATTERN)
            # 启动后台监听任务
            self._redis_listener_task = asyncio.create_task(self._redis_listener(), name="event-bus-redis-listener")
            self._loop = loop
            logger.info("事件总线 Redis Pub/Sub 桥接已启动（instance_id=%s）", self._instance_id[:8])
        except Exception as e:
            logger.warning(
                "事件总线 Redis 桥接启动失败（降级为纯内存模式）: %s: %s",
                type(e).__name__,
                str(e)[:200],
            )
            self._detach_redis_state()

    async def stop(self) -> None:
        """停止 Redis Pub/Sub 监听，清理资源。

        循环感知：仅在绑定的循环上执行真正的 await 清理；若循环已关闭/切换，
        直接丢弃引用（符合 AGENTS.md §4.1 规则 3）。
        """
        # 如果不在正确的循环上，只丢弃引用不做 await
        if self._loop is not None:
            try:
                current_loop = asyncio.get_running_loop()
            except RuntimeError:
                current_loop = None
            if current_loop is not self._loop or (self._loop is not None and self._loop.is_closed()):
                self._detach_redis_state()
                return

        # 取消监听任务
        if self._redis_listener_task is not None:
            self._redis_listener_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._redis_listener_task

        # 关闭 pubsub 连接
        if self._redis_pubsub is not None:
            with contextlib.suppress(Exception):
                await self._redis_pubsub.close()

        self._detach_redis_state()
        logger.info("事件总线 Redis Pub/Sub 桥接已停止")

    async def _redis_listener(self) -> None:
        """后台任务：持续监听 Redis Pub/Sub 消息，将远程事件分发到本地订阅者。

        - 跳过自己发布的消息（通过 instance_id 判断，防止回环）
        - 从 Redis 收到的事件不再写 DB（发布方已写），不再 PUBLISH（会循环）
        - 异常时记录日志并等待 1 秒后自动重连
        - 检测到事件循环关闭时主动退出，不抛异常
        """
        while True:
            pubsub = None
            try:
                # 主动检测循环是否关闭，避免在已关闭循环上做 I/O
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    break
                if loop.is_closed():
                    break

                from app.db.redis import get_redis_client

                redis_client = get_redis_client()
                if redis_client is None:
                    # Redis 不可用，等待后重试
                    await asyncio.sleep(5)
                    continue

                pubsub = redis_client.pubsub()
                self._redis_pubsub = pubsub
                await pubsub.psubscribe(_REDIS_CHANNEL_PATTERN)
                logger.info("Redis Pub/Sub listener 已 (重新)连接")

                async for message in pubsub.listen():
                    # 只处理 pmessage 类型（pattern 匹配的消息）
                    if message.get("type") != "pmessage":
                        continue

                    try:
                        raw_data = message.get("data")
                        if not isinstance(raw_data, str):
                            continue

                        data = json.loads(raw_data)
                        # 跳过自己发布的消息（回环防护）
                        if data.get("instance_id") == self._instance_id:
                            continue

                        # 反序列化事件（使用 pydantic 原生方法）
                        event_json = data.get("event")
                        if not event_json:
                            continue
                        event = DomainEvent.model_validate_json(event_json)

                        # 写入本地历史 + 通知本地订阅者（不写 DB、不再 PUBLISH）
                        await self._local_dispatch(event)
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:
                        logger.error(
                            "处理 Redis 事件消息失败: %s: %s",
                            type(e).__name__,
                            str(e)[:200],
                        )
            except asyncio.CancelledError:
                # 任务被取消，正常退出
                break
            except RuntimeError as e:
                # "Event loop is closed" —— 正常关闭路径，退出循环
                if "loop" in str(e).lower() and "closed" in str(e).lower():
                    break
                logger.error(
                    "Redis Pub/Sub listener RuntimeError，1秒后重试: %s",
                    str(e)[:200],
                )
                try:
                    await asyncio.sleep(1)
                except (RuntimeError, asyncio.CancelledError):
                    break
            except Exception as e:
                logger.error(
                    "Redis Pub/Sub listener 异常，1秒后重试: %s: %s",
                    type(e).__name__,
                    str(e)[:200],
                )
                try:
                    await asyncio.sleep(1)
                except (RuntimeError, asyncio.CancelledError):
                    break
            finally:
                if pubsub is not None:
                    with contextlib.suppress(Exception):
                        await pubsub.close()
                if self._redis_pubsub is pubsub:
                    self._redis_pubsub = None

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


async def start_event_bus() -> None:
    """启动事件总线（含 Redis Pub/Sub 桥接）。供 lifespan 调用。"""
    await bus.start()


async def stop_event_bus() -> None:
    """停止事件总线（含 Redis Pub/Sub 桥接）。供 lifespan 调用。"""
    await bus.stop()


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
