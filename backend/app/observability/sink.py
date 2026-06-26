# 结构化日志 Sink 协议 + 多 sink 实现
# 旁路架构：应用代码只 emit 结构化日志事件，不关心 sink 怎么处理
# Sink 实现：ConsoleSink（控制台）/ JSONFileSink（文件）/ RemoteGRPCSink（远程，预留接口）
from __future__ import annotations

import json
import sys
import threading
from datetime import datetime, timezone
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class LogSink(Protocol):
    """日志 Sink 协议：旁路日志处理

    应用代码通过 LogBus.emit 发送结构化日志事件，
    LogBus 分发到所有注册的 sink，sink 各自决定如何处理（输出/存储/远程发送）。

    设计原则：
    - 应用代码与日志处理解耦
    - sink 异常不影响主流程（try/except 包裹）
    - 支持多 sink 并行（Console + File + Remote）
    - 结构化 JSON 格式（便于 ELK/Loki/Grafana 等日志系统解析）
    """

    def write(self, event: dict[str, Any]) -> None:
        """处理一条结构化日志事件

        event 是一个完整的结构化日志，包含：
        - timestamp: ISO8601 时间戳
        - level: INFO / WARNING / ERROR / DEBUG
        - request_id: 关联的 HTTP 请求 ID
        - meeting_id: 关联的会议 ID
        - runner_session_id: 关联的 Runner 执行会话 ID
        - logger: 模块名
        - message: 日志消息
        - extra: 扩展字段（如 stage, latency_ms, error_detail 等）
        """
        ...


