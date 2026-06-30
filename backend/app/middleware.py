# 请求追踪中间件：每个 HTTP 请求分配 request_id，设置到 contextvars
# API 认证中间件：基于 token 的简单认证
from __future__ import annotations

import os
import re
import time

from fastapi import FastAPI, Request
from fastapi.responses import Response, JSONResponse

from app.context import new_request_id, set_request_id, reset_request_id
from app.logging_config import get_logger

logger = get_logger("middleware.trace")

# API 认证 token（留空则不启用认证，仅开发模式）
_API_TOKEN = os.environ.get("CONCLAVE_API_TOKEN", "")
# 免认证路径前缀
_PUBLIC_PATHS = {"/health", "/docs", "/openapi.json", "/redoc"}
# WebSocket 升级路径免认证（WebSocket 在 query 参数中传 token）
_WS_PATHS = {"/ws"}


def _is_public(path: str) -> bool:
    """判断路径是否免认证"""
    for p in _PUBLIC_PATHS:
        if path == p or path.startswith(p + "/") or path.startswith(p + "?"):
            return True
    return False


def setup_auth_middleware(app: FastAPI) -> None:
    """注册 API 认证中间件

    认证策略：
    - CONCLAVE_API_TOKEN 未设置 → 不启用认证（开发模式）
    - 设置了 token → 所有非公开路径需带 Authorization: Bearer <token> 或 ?token=<token>
    - WebSocket 连接通过 query 参数 ?token=<token> 认证
    """

    @app.middleware("http")
    async def auth_middleware(request: Request, call_next) -> Response:
        # 未配置 token 时不认证
        if not _API_TOKEN:
            return await call_next(request)

        path = request.url.path

        # 公开路径免认证
        if _is_public(path):
            return await call_next(request)

        # 检查 Authorization header
        auth_header = request.headers.get("Authorization", "")
        token = ""
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
        # 也支持 query 参数（用于 WebSocket 和浏览器直连）
        if not token:
            token = request.query_params.get("token", "")

        if token != _API_TOKEN:
            return JSONResponse(
                status_code=401,
                content={"detail": "未授权：请提供有效的 API token"},
            )

        return await call_next(request)


# ---- 命令注入防护 ----

# 危险命令模式（正则匹配，比精确匹配更难绕过）
_DANGEROUS_PATTERNS = [
    r"\brm\s+(-{1,2}\w+\s+)*-?r\w*\s+(-{1,2}\w+\s+)*[/~.*]",  # rm -rf / 或 rm -rf ~ 或 rm -rf . 或 rm -rf *
    r"\brm\s+(-{1,2}\w+\s+)*-?r\w*\s+\*",  # rm -rf *（删所有文件）
    r"\bmkfs\b",              # 格式化文件系统
    r"\b(?:shutdown|reboot|halt|poweroff)\b",  # 系统关机/重启
    r"\bdd\s+if=.+of=/dev/",  # dd 写设备
    r">\s*/dev/sd[a-z]",      # 重定向到块设备
    r"\bchmod\s+-R\s+777\s+/",  # 全盘改权限
    r"\b(?:curl|wget)\s+.+\|\s*/?(?:bash|sh|/bin/bash|/bin/sh)",  # curl|bash 含路径前缀
    r"\b(?:curl|wget)\s+.+\|\s*(?:bash|sh)",  # curl | shell 远程执行
    r"\beval\s+\$\(?",       # eval 命令注入
    r"\beval\s+\$\w+",       # eval $CMD 变量展开
    r"\bnc\s+.*-e\s+/bin/sh",  # netcat 反弹 shell
    r"\bpython\s+-c\s+.*import\s+subprocess",  # python subprocess 注入
    r"\bpython\s+-c\s+.*import\s+os",  # python os 模块注入
]


def is_dangerous_command(command: str) -> bool:
    """检测命令是否包含危险模式"""
    cmd = command.strip()
    for pattern in _DANGEROUS_PATTERNS:
        if re.search(pattern, cmd, re.IGNORECASE):
            return True
    return False


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
