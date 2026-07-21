# LogSink 实现：ConsoleSink / JSONFileSink / RemoteGRPCSink（预留）
from __future__ import annotations

import contextlib
import json
import sys
import threading
from typing import Any, ClassVar, TextIO


class ConsoleSink:
    """控制台日志 Sink：人类可读格式输出到 stdout

    格式：[时间] [级别] [request_id] [meeting_id] [session_id] 模块: 消息
    适合开发期调试。
    """

    def __init__(self, stream: TextIO | None = None) -> None:
        self._stream = stream or sys.stdout
        self._lock = threading.Lock()

    def write(self, event: dict[str, Any]) -> None:
        try:
            ts = event.get("timestamp", "")[:19]
            level = event.get("level", "INFO")
            rid = event.get("request_id", "-")
            mid = event.get("meeting_id", "-")
            sid = event.get("runner_session_id", "-")
            user = event.get("username", "-")
            logger = event.get("logger", "")
            msg = event.get("message", "")
            extra = event.get("extra", {})
            user_str = f"[{user}]" if user and user != "-" else ""
            extra_str = f" {json.dumps(extra, ensure_ascii=False)}" if extra else ""
            line = f"{ts} [{level}] [{rid}] [{mid}] [{sid}]{user_str} {logger}: {msg}{extra_str}\n"
            with self._lock:
                self._stream.write(line)
                self._stream.flush()
        except Exception:
            pass  # sink 异常不影响主流程


class JSONFileSink:
    """JSON 文件日志 Sink：每行一个 JSON 对象

    适合生产环境，可被 ELK / Loki / Fluentd 等日志系统直接消费。
    文件路径可配置，支持日志轮转（外部 logrotate）。
    """

    def __init__(self, file_path: str) -> None:
        self._file_path = file_path
        self._lock = threading.Lock()
        # 打开文件（追加模式，UTF-8）—— 长生命周期文件句柄，在 close() 中关闭
        self._file = open(file_path, "a", encoding="utf-8")  # noqa: SIM115

    def write(self, event: dict[str, Any]) -> None:
        try:
            line = json.dumps(event, ensure_ascii=False, default=str) + "\n"
            with self._lock:
                self._file.write(line)
                self._file.flush()
        except Exception:
            pass  # sink 异常不影响主流程

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self._file.close()


class RemoteGRPCSink:
    """远程 gRPC 日志 Sink（预留接口）

    通过 gRPC 将结构化日志发送到独立的日志服务。
    实际实现需要：
    1. 定义 .proto 文件（LogEvent message + LogService service）
    2. 生成 gRPC stub
    3. 实现异步发送（批量 + 重试 + 断路器）

    当前为 stub 实现，日志暂存内存队列，达到阈值或定时 flush。
    生产环境接入时替换为真实 gRPC client。
    """

    def __init__(self, endpoint: str = "", batch_size: int = 100) -> None:
        self._endpoint = endpoint
        self._batch_size = batch_size
        self._buffer: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def write(self, event: dict[str, Any]) -> None:
        try:
            with self._lock:
                self._buffer.append(event)
                if len(self._buffer) >= self._batch_size:
                    self._flush()
        except Exception:
            pass

    def _flush(self) -> None:
        """将缓冲区的日志批量发送到远程服务（stub：清空缓冲区）"""
        # TODO: 实现 gRPC 远程发送
        # from grpc import insecure_channel
        # channel = insecure_channel(self._endpoint)
        # stub = LogServiceStub(channel)
        # for event in self._buffer:
        #     stub.SendLog(LogEvent(**event))
        len(self._buffer)
        self._buffer.clear()

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self._flush()


class EventBusSink:
    """事件总线日志 Sink：将结构化日志通过 WebSocket 推送到前端

    仅推送有 meeting_id 上下文的日志（会议运行期间产生的日志），
    以 log.entry 事件类型发布到事件总线，前端通过 WebSocket 接收。
    为避免日志量过大，只推送 INFO 及以上级别，且过滤掉高频心跳日志。
    """

    # 不需要推送到前端的高频/噪声日志
    _NOISY_LOGGERS: ClassVar[set[str]] = {
        "app.middleware.trace",
        "uvicorn.access",
        "uvicorn.error",
    }
    # 只推送到前端的日志级别及以上
    _MIN_LEVEL: ClassVar[str] = "INFO"
    _LEVEL_RANK: ClassVar[dict[str, int]] = {"DEBUG": 0, "INFO": 1, "WARNING": 2, "ERROR": 3}

    def write(self, event: dict[str, Any]) -> None:
        try:
            import asyncio

            from app.events import bus, make_event

            mid = event.get("meeting_id", "-")
            if not mid or mid == "-":
                return  # 无会议上下文的日志不推送

            logger_name = event.get("logger", "")
            if logger_name in self._NOISY_LOGGERS:
                return  # 过滤噪声日志

            level = event.get("level", "INFO")
            if self._LEVEL_RANK.get(level, 0) < self._LEVEL_RANK.get(self._MIN_LEVEL, 1):
                return  # 过滤 DEBUG 级别

            # 构造精简的日志 payload（避免推送过大的 extra 数据）
            payload = {
                "level": level,
                "logger": logger_name,
                "message": event.get("message", ""),
                "timestamp": event.get("timestamp", ""),
                "agent_role": event.get("agent_role", ""),
                "stage": (event.get("extra") or {}).get("stage", ""),
            }

            # 在事件循环中发布（log_bus 可能在非 async 上下文中调用）
            # 使用 call_soon_threadsafe 确保线程安全
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                # 没有运行中的事件循环，无法推送
                return
            loop.call_soon_threadsafe(lambda: asyncio.ensure_future(bus.publish(make_event("log.entry", mid, payload))))
        except Exception:
            pass  # sink 异常不影响主流程
