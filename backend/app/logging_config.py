# 日志配置：统一的 Python logging 配置 + 全链路追踪 ID 注入
# 每条日志自动带上 request_id 和 meeting_id，满足工业级回溯定位需求
from __future__ import annotations

import logging
import os
import sys


class TraceContextFilter(logging.Filter):
    """日志过滤器：从 contextvars 注入 request_id 和 meeting_id 到每条日志

    确保一个请求从入口到出口的所有日志都能通过 request_id 关联，
    以及所有会议运行期间的日志都能通过 meeting_id 关联。
    """

    def filter(self, record: logging.LogRecord) -> bool:
        # 延迟导入避免循环依赖
        from app.context import get_trace_context

        ctx = get_trace_context()
        record.request_id = ctx["request_id"]
        record.meeting_id = ctx["meeting_id"]
        record.runner_session_id = ctx["runner_session_id"]
        record.agent_role = ctx.get("agent_role", "")
        return True


def setup_logging(level: str | None = None) -> None:
    """配置全局日志格式和级别

    - level 从环境变量 CONCLAVE_LOG_LEVEL 读取，默认 INFO
    - 格式：[时间] [级别] [request_id] [meeting_id] [模块] 消息
    - 输出到 stdout（uvicorn / docker 友好）
    - 每条日志自动注入 request_id 和 meeting_id
    """
    log_level = level or os.environ.get("CONCLAVE_LOG_LEVEL", "INFO")
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)

    # 统一格式：带追踪 ID（含 runner_session_id 和 agent_role）
    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] [%(request_id)s] [%(meeting_id)s] [%(runner_session_id)s] [%(agent_role)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 控制台 handler + 追踪过滤器
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    handler.addFilter(TraceContextFilter())

    # 配置根日志器
    root = logging.getLogger()
    root.setLevel(numeric_level)
    # 避免重复 handler（热重载时可能多次调用）
    if not any(
        isinstance(h, logging.StreamHandler) and isinstance(h.formatter, logging.Formatter) for h in root.handlers
    ):
        root.addHandler(handler)
    else:
        # 更新已有 handler 的 formatter（确保追踪格式生效）
        for h in root.handlers:
            if isinstance(h, logging.StreamHandler):
                h.setFormatter(formatter)
                # 确保 filter 存在
                if not any(isinstance(f, TraceContextFilter) for f in h.filters):
                    h.addFilter(TraceContextFilter())

    # 模块级日志级别
    logging.getLogger("app").setLevel(numeric_level)
    logging.getLogger("app.agents").setLevel(numeric_level)
    logging.getLogger("app.orchestrator").setLevel(numeric_level)
    logging.getLogger("app.routers").setLevel(numeric_level)
    # httpx / uvicorn 访问日志降级，减少噪声
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """获取模块日志器（带模块名前缀）"""
    return logging.getLogger(f"app.{name}")
