"""认证 + CSRF 中间件（Auth 插件）。

功能：
- 从 HttpOnly Cookie（新）或 Authorization Bearer header（旧）提取 JWT
- Dev Token 支持（开发模式）
- 测试模式跳过认证（APP_ENV=test + CONCLAVE_TEST_DISABLE_AUTH=1）
- 速率限制（复用 app.middleware._check_rate_limit）
- CSRF double-submit cookie 保护（仅对 Cookie 认证的写操作）
- 公共路径白名单（/health, /auth/login, /auth/csrf-token, /setup/* 等）
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import Request, Response
from fastapi.responses import JSONResponse

from app.context import set_request_id, set_user_id, set_user_role, set_username
from app.observability.audit import audit
from app.plugins.builtin.auth.csrf import (
    CSRF_COOKIE_NAME,
    CSRF_HEADER_NAME,
    check_csrf,
)

logger = logging.getLogger(__name__)

# Cookie 名（与前端约定）
COOKIE_ACCESS_TOKEN = "conclave_access_token"
COOKIE_REFRESH_TOKEN = "conclave_refresh_token"

# 公共路径（不需要认证）
_PUBLIC_PATHS = {
    "/health",
    "/metrics",
    "/healthz",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/debug/auth-info",
    "/auth/login",
    "/auth/csrf-token",
    "/setup",
    "/setup/status",
    "/api/captcha",
}


def _client_ip(request: Request) -> str:
    """从 request 中提取客户端 IP（优先 X-Forwarded-For）。"""
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _normalize_path(path: str) -> str:
    """规范化路径用于白名单匹配（去除末尾斜杠、小写）。"""
    p = path.rstrip("/")
    if not p:
        p = "/"
    return p.lower()


def _is_public_path(path: str) -> bool:
    norm = _normalize_path(path)
    for p in _PUBLIC_PATHS:
        if norm == p:
            return True
        # 前缀匹配：子路径也公开
        if norm.startswith(p + "/"):
            return True
    return False


def _should_check_csrf(request: Request, is_cookie_auth: bool) -> bool:
    """是否需要 CSRF 检查：Cookie 认证 + 非安全 HTTP 方法。"""
    if not is_cookie_auth:
        return False
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return False
    if _is_public_path(request.url.path):
        return False
    return True


def setup_auth_middleware(app, plugin=None) -> None:
    """注册认证中间件到 FastAPI app（使用 @app.middleware 装饰器，与旧 middleware 一致）。"""

    @app.middleware("http")
    async def auth_middleware(request: Request, call_next) -> Response:
        import os
        import uuid
        import hmac

        # 生成 request_id
        req_id = request.headers.get("x-request-id", str(uuid.uuid4())[:12])
        set_request_id(req_id)

        path = request.url.path
        method = request.method
        ip = _client_ip(request)

        # 测试模式：跳过认证与限流，注入测试 admin 用户（与旧 middleware 行为一致）
        if os.environ.get("APP_ENV") == "test" and os.environ.get("CONCLAVE_TEST_DISABLE_AUTH") == "1":
            request.state.auth_user = {"username": "test", "role": "admin", "uid": None}
            set_user_id("test")
            set_username("test")
            set_user_role("admin")
            return await call_next(request)

        # OPTIONS 预检直接放行
        if method == "OPTIONS":
            return await call_next(request)

        # WebSocket 端点单独处理
        if path.startswith("/ws"):
            return await call_next(request)

        # 公共路径放行（清除 ContextVar 避免污染）
        if _is_public_path(path):
            set_user_id("")
            set_username("")
            set_user_role("")
            request.state.auth_user = None
            return await call_next(request)

        # 延迟 import 避免循环引用
        from app.middleware import _DEV_TOKEN, _check_rate_limit, _RATE_BLOCK_SECONDS
        from app.auth import decode_token

        # 速率限制
        ok, reason = _check_rate_limit(ip, is_failed_attempt=False)
        if not ok:
            audit("auth.rate_limited", "failure", {"path": path, "reason": reason}, ip=ip)
            return JSONResponse(
                status_code=429,
                content={"detail": f"请求过于频繁：{reason}"},
                headers={"Retry-After": str(_RATE_BLOCK_SECONDS)},
            )

        # 1. 提取 token（优先 Cookie，其次 Authorization header，最后 dev token）
        token = None
        is_cookie_auth = False

        cookie_token = request.cookies.get(COOKIE_ACCESS_TOKEN)
        if cookie_token:
            token = cookie_token
            is_cookie_auth = True

        auth_header = request.headers.get("authorization", "")
        if auth_header.lower().startswith("bearer "):
            token = auth_header[7:].strip()
            is_cookie_auth = False
        elif auth_header.lower().startswith("token "):
            token = auth_header[6:].strip()
            is_cookie_auth = False

        using_dev_token = False
        dev_token_header = request.headers.get("x-dev-token", "")
        dev_token_query = request.query_params.get("dev_token", "")
        dev_token = dev_token_header or dev_token_query
        if dev_token and not token:
            if hmac.compare_digest(dev_token.encode("utf-8"), _DEV_TOKEN.encode("utf-8")):
                using_dev_token = True
                set_user_id("dev")
                set_username("dev")
                set_user_role("admin")
                request.state.auth_user = {"username": "dev", "role": "admin", "uid": None}

        # 2. CSRF 检查（Cookie 认证的写操作）
        if _should_check_csrf(request, is_cookie_auth):
            if not check_csrf(request):
                audit("auth.csrf_failed", "failure", {"path": path, "method": method}, ip=ip)
                return JSONResponse(
                    status_code=403,
                    content={"detail": "CSRF 验证失败，请刷新页面重试"},
                )

        # 3. 验证 token
        if not using_dev_token:
            if not token:
                _check_rate_limit(ip, is_failed_attempt=True)
                return JSONResponse(
                    status_code=401,
                    content={"detail": "未授权：请先登录"},
                    headers={"WWW-Authenticate": "Bearer"},
                )

            claims = decode_token(token)
            if not claims:
                _check_rate_limit(ip, is_failed_attempt=True)
                audit("auth.invalid_token", "failure", {"path": path}, ip=ip)
                return JSONResponse(
                    status_code=401,
                    content={"detail": "token 无效或已过期"},
                    headers={"WWW-Authenticate": "Bearer"},
                )

            if claims.get("type") == "refresh":
                return JSONResponse(
                    status_code=401,
                    content={"detail": "不能使用 refresh token 访问 API"},
                )

            # 设置 ContextVar 和 request.state.auth_user
            username = claims.get("sub", "")
            uid = claims.get("uid")
            role = claims.get("role", "user")
            uid_str = str(uid) if uid is not None else username
            set_user_id(uid_str)
            set_username(username)
            set_user_role(role)
            # auth_user 格式与旧 middleware 兼容：直接使用 claims dict（含 sub/role/uid 等字段）
            # 但 auth_guard.py 读取的是 username 字段，所以需要显式设置
            auth_user = dict(claims)
            auth_user["username"] = username
            auth_user["uid"] = uid_str
            request.state.auth_user = auth_user

        # 4. 放行
        response = await call_next(request)

        # 5. 安全响应头
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        return response

    logger.info("Auth 中间件已注册（Cookie + Bearer 双模式）")
