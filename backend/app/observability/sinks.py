# LogSink 实现：ConsoleSink / JSONFileSink / RemoteGRPCSink（预留）
from __future__ import annotations

import json
import sys
import threading
from datetime import datetime, timezone
from typing import Any, TextIO


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
            logger = event.get("logger", "")
            msg = event.get("message", "")
            extra = event.get("extra", {})
            extra_str = f" {json.dumps(extra, ensure_ascii=False)}" if extra else ""
            line = f"{ts} [{level}] [{rid}] [{mid}] [{sid}] {logger}: {msg}{extra_str}\n"
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
        # 打开文件（追加模式，UTF-8）
        self._file = open(file_path, "a", encoding="utf-8")

    def write(self, event: dict[str, Any]) -> None:
        try:
            line = json.dumps(event, ensure_ascii=False, default=str) + "\n"
            with self._lock:
                self._file.write(line)
                self._file.flush()
        except Exception:
            pass  # sink 异常不影响主流程

    def close(self) -> None:
        try:
            self._file.close()
        except Exception:
            pass


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
        buffer_count = len(self._buffer)
        self._buffer.clear()

    def close(self) -> None:
        try:
            self._flush()
        except Exception:
            pass
