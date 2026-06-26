# 请求追踪中间件：每个 HTTP 请求分配 request_id，设置到 contextvars
from __future__ import annotations

import time

from fastapi import FastAPI, Request
from fastapi.responses import Response

from app.context import new_request_id, set_request_id, reset_request_id
from app.logging_config import get_logger

logger = get_logger("middleware.trace")


def setup_trace_middleware(app: FastAPI) -> None:
    """注册请求追踪中间件

    每个 HTTP 请求进入时：
    1. 分配唯一 request_id（或从 X-Request-Id header 继承）
    2. 设置到 contextvars（异步安全）
    3. 响应时在 header 中返回 X-Request-Id
    4. 记录请求日志（方法、路径、状态码、耗时）
    """

    @app.middleware("http")
    async def trace_middleware(request: Request, call_next) -> Response:
        # 从 header 继承或生成新的 request_id
        rid = request.headers.get("X-Request-Id") or new_request_id()
        token = set_request_id(rid)

        t0 = time.monotonic()
        method = request.method
        path = request.url.path

        try:
            response = await call_next(request)
        except Exception as e:
            elapsed = (time.monotonic() - t0) * 1000
            logger.error(
                "request_id=%s %s %s 500 %.0fms [异常: %s]",
                rid, method, path, elapsed, type(e).__name__,
            )
            raise
        finally:
            reset_request_id(token)

        elapsed = (time.monotonic() - t0) * 1000
        status = response.status_code

        # 按状态码级别记录日志
        if status >= 500:
            logger.error(
                "request_id=%s %s %s %d %.0fms",
                rid, method, path, status, elapsed,
            )
        elif status >= 400:
            logger.warning(
                "request_id=%s %s %s %d %.0fms",
                rid, method, path, status, elapsed,
            )
        else:
            logger.info(
                "request_id=%s %s %s %d %.0fms",
                rid, method, path, status, elapsed,
            )

        # 响应头返回 request_id（便于客户端关联）
        response.headers["X-Request-Id"] = rid
        return response
