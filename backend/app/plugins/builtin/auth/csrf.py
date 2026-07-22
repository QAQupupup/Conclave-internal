"""CSRF double-submit cookie 工具。

策略：
- 登录成功后，服务端设置 `csrf_token` Cookie（JS 可读，HttpOnly=False）
- 所有 POST/PUT/PATCH/DELETE 请求必须在 `X-CSRF-Token` Header 中携带该值
- 中间件比对 Header 和 Cookie 是否一致
- GET/HEAD/OPTIONS 请求不校验 CSRF
- 公开路径（/auth/login、/setup 等）不校验 CSRF
"""

from __future__ import annotations

import hmac
import secrets

from fastapi import Request, Response

CSRF_COOKIE_NAME = "csrf_token"
CSRF_HEADER_NAME = "X-CSRF-Token"
CSRF_TOKEN_BYTES = 32


def generate_csrf_token() -> str:
    """生成一个新的 CSRF token。"""
    return secrets.token_urlsafe(CSRF_TOKEN_BYTES)


def set_csrf_cookie(response: Response, token: str, *, secure: bool = False) -> None:
    """在响应中设置 CSRF cookie。"""
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=token,
        httponly=False,  # JS 需要读取
        secure=secure,
        samesite="strict",
        path="/",
        max_age=30 * 24 * 3600,  # 30 天，与 refresh_token 一致
    )


def clear_csrf_cookie(response: Response) -> None:
    response.delete_cookie(CSRF_COOKIE_NAME, path="/")


def extract_csrf_from_cookie(request: Request) -> str | None:
    """从 Cookie 中提取 CSRF token。"""
    return request.cookies.get(CSRF_COOKIE_NAME)


def extract_csrf_from_header(request: Request) -> str | None:
    """从 Header 中提取 CSRF token。"""
    return request.headers.get(CSRF_HEADER_NAME)


def validate_csrf(request: Request) -> bool:
    """校验 CSRF token（cookie 与 header 必须一致且非空）。"""
    cookie_token = extract_csrf_from_cookie(request)
    header_token = extract_csrf_from_header(request)
    if not cookie_token or not header_token:
        return False
    return hmac.compare_digest(cookie_token.encode("utf-8"), header_token.encode("utf-8"))


def is_csrf_required(method: str) -> bool:
    """判断该 HTTP 方法是否需要 CSRF 校验。"""
    return method.upper() in {"POST", "PUT", "PATCH", "DELETE"}


def check_csrf(request: Request) -> bool:
    """Middleware 调用的 CSRF 校验入口（返回 True 表示通过）。"""
    if not is_csrf_required(request.method):
        return True
    return validate_csrf(request)
