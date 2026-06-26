# 日志总线：旁路日志分发，应用代码只 emit，不关心 sink
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.context import get_request_id, get_meeting_id
from app.observability.sinks import ConsoleSink


class LogBus:
    """日志事件总线：结构化日志旁路分发

    架构：
    - 应用代码调用 log_bus.emit(level, message, extra) 发送日志
    - LogBus 构造结构化事件（含 timestamp, request_id, meeting_id 等）
    - 分发到所有注册的 sink（ConsoleSink / JSONFileSink / RemoteGRPCSink）
    - sink 异常不影响主流程

    使用方式：
        from app.observability.log_bus import log_bus
        log_bus.emit("INFO", "会议已创建", extra={"meeting_id": mid})
    """

    def __init__(self) -> None:
        self._sinks: list = []
        # 默认注册 ConsoleSink
        self._sinks.append(ConsoleSink())

    def add_sink(self, sink) -> None:
        """注册日志 sink"""
        self._sinks.append(sink)

    def clear_sinks(self) -> None:
        """清空所有 sink（测试用）"""
        self._sinks.clear()

    def emit(
        self,
        level: str,
        message: str,
        logger: str = "",
        extra: dict[str, Any] | None = None,
    ) -> None:
        """发送一条结构化日志事件到所有 sink

        自动注入追踪上下文（request_id, meeting_id, runner_session_id）。
        """
        from app.context import get_runner_session_id

        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": level,
            "request_id": get_request_id(),
            "meeting_id": get_meeting_id(),
            "runner_session_id": get_runner_session_id(),
            "logger": logger,
            "message": message,
            "extra": extra or {},
        }

        for sink in self._sinks:
            try:
                sink.write(event)
            except Exception:
                pass  # sink 异常不影响主流程

    def info(self, message: str, logger: str = "", extra: dict[str, Any] | None = None) -> None:
        self.emit("INFO", message, logger, extra)

    def warning(self, message: str, logger: str = "", extra: dict[str, Any] | None = None) -> None:
        self.emit("WARNING", message, logger, extra)

    def error(self, message: str, logger: str = "", extra: dict[str, Any] | None = None) -> None:
        self.emit("ERROR", message, logger, extra)

    def debug(self, message: str, logger: str = "", extra: dict[str, Any] | None = None) -> None:
        self.emit("DEBUG", message, logger, extra)


# 进程级单例
log_bus = LogBus()
