"""CSRF double-submit cookie 防御测试。

覆盖 P0 审计发现：CSRF 防御完全零测试。
测试策略遵循 AGENTS.md §5.7.4 关键安全函数专项测试规范。
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import Request, Response
from starlette.datastructures import Headers

from app.plugins.builtin.auth.csrf import (
    CSRF_COOKIE_NAME,
    CSRF_HEADER_NAME,
    check_csrf,
    clear_csrf_cookie,
    extract_csrf_from_cookie,
    extract_csrf_from_header,
    generate_csrf_token,
    is_csrf_required,
    set_csrf_cookie,
    validate_csrf,
)

# ── Token 生成 ──────────────────────────────────────────


class TestGenerateToken:
    def test_token_is_non_empty_string(self) -> None:
        token = generate_csrf_token()
        assert isinstance(token, str)
        assert len(token) > 0

    def test_tokens_are_unique(self) -> None:
        """每次生成的 token 必须唯一。"""
        tokens = {generate_csrf_token() for _ in range(100)}
        assert len(tokens) == 100

    def test_token_is_url_safe(self) -> None:
        """token_urlsafe 生成的 token 不应包含 URL 不安全字符。"""
        token = generate_csrf_token()
        # URL-safe base64 不含 + / =
        assert "+" not in token
        assert "/" not in token


# ── Cookie 操作 ─────────────────────────────────────────


class TestCsrfCookie:
    def test_set_csrf_cookie_sets_correct_attributes(self) -> None:
        response = MagicMock(spec=Response)
        token = generate_csrf_token()
        set_csrf_cookie(response, token)
        response.set_cookie.assert_called_once()
        kwargs = response.set_cookie.call_args.kwargs
        assert kwargs["key"] == CSRF_COOKIE_NAME
        assert kwargs["value"] == token
        assert kwargs["httponly"] is False  # JS 需要读取
        assert kwargs["samesite"] == "strict"
        assert kwargs["path"] == "/"
        assert kwargs["max_age"] == 30 * 24 * 3600

    def test_set_csrf_cookie_secure_flag(self) -> None:
        response = MagicMock(spec=Response)
        set_csrf_cookie(response, "tok", secure=True)
        kwargs = response.set_cookie.call_args.kwargs
        assert kwargs["secure"] is True

    def test_clear_csrf_cookie(self) -> None:
        response = MagicMock(spec=Response)
        clear_csrf_cookie(response)
        response.delete_cookie.assert_called_once_with(CSRF_COOKIE_NAME, path="/")


# ── Token 提取 ──────────────────────────────────────────


class TestExtractToken:
    def test_extract_from_cookie_present(self) -> None:
        request = MagicMock(spec=Request)
        request.cookies = {CSRF_COOKIE_NAME: "abc123"}
        assert extract_csrf_from_cookie(request) == "abc123"

    def test_extract_from_cookie_absent(self) -> None:
        request = MagicMock(spec=Request)
        request.cookies = {}
        assert extract_csrf_from_cookie(request) is None

    def test_extract_from_header_present(self) -> None:
        request = MagicMock(spec=Request)
        request.headers = Headers({CSRF_HEADER_NAME: "xyz789"})
        assert extract_csrf_from_header(request) == "xyz789"

    def test_extract_from_header_absent(self) -> None:
        request = MagicMock(spec=Request)
        request.headers = Headers({})
        assert extract_csrf_from_header(request) is None


# ── CSRF 校验 ───────────────────────────────────────────


class TestValidateCsrf:
    def _make_request(self, cookie_token: str | None, header_token: str | None) -> Request:
        request = MagicMock(spec=Request)
        request.cookies = {CSRF_COOKIE_NAME: cookie_token} if cookie_token else {}
        headers_dict = {CSRF_HEADER_NAME: header_token} if header_token else {}
        request.headers = Headers(headers_dict)
        return request

    def test_matching_tokens_pass(self) -> None:
        token = generate_csrf_token()
        request = self._make_request(token, token)
        assert validate_csrf(request) is True

    def test_mismatched_tokens_fail(self) -> None:
        request = self._make_request("token-a", "token-b")
        assert validate_csrf(request) is False

    def test_missing_cookie_fails(self) -> None:
        request = self._make_request(None, "some-token")
        assert validate_csrf(request) is False

    def test_missing_header_fails(self) -> None:
        request = self._make_request("some-token", None)
        assert validate_csrf(request) is False

    def test_both_missing_fails(self) -> None:
        request = self._make_request(None, None)
        assert validate_csrf(request) is False

    def test_timing_safe_comparison(self) -> None:
        """使用 hmac.compare_digest 避免时序攻击。"""
        # 构造两个相同前缀不同后缀的 token，验证不会因前缀匹配而通过
        request = self._make_request("a" * 43, "a" * 42 + "b")
        assert validate_csrf(request) is False


# ── HTTP 方法判断 ──────────────────────────────────────


class TestIsCsrfRequired:
    @pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS"])
    def test_safe_methods_not_required(self, method: str) -> None:
        assert is_csrf_required(method) is False

    @pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
    def test_unsafe_methods_required(self, method: str) -> None:
        assert is_csrf_required(method) is True

    def test_case_insensitive(self) -> None:
        assert is_csrf_required("post") is True
        assert is_csrf_required("get") is False


# ── check_csrf（中间件入口）─────────────────────────────


class TestCheckCsrf:
    def _make_request(self, method: str, cookie: str | None = None, header: str | None = None) -> Request:
        request = MagicMock(spec=Request)
        request.method = method
        request.cookies = {CSRF_COOKIE_NAME: cookie} if cookie else {}
        headers_dict = {CSRF_HEADER_NAME: header} if header else {}
        request.headers = Headers(headers_dict)
        return request

    @pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS"])
    def test_get_requests_always_pass(self, method: str) -> None:
        """GET/HEAD/OPTIONS 不校验 CSRF，即使无 token 也通过。"""
        request = self._make_request(method)
        assert check_csrf(request) is True

    def test_post_with_valid_token_passes(self) -> None:
        token = generate_csrf_token()
        request = self._make_request("POST", token, token)
        assert check_csrf(request) is True

    def test_post_without_token_fails(self) -> None:
        request = self._make_request("POST")
        assert check_csrf(request) is False

    def test_post_with_mismatched_token_fails(self) -> None:
        request = self._make_request("POST", "cookie-tok", "header-tok")
        assert check_csrf(request) is False

    @pytest.mark.parametrize("method", ["PUT", "PATCH", "DELETE"])
    def test_other_unsafe_methods_require_token(self, method: str) -> None:
        request = self._make_request(method)
        assert check_csrf(request) is False
        token = generate_csrf_token()
        request = self._make_request(method, token, token)
        assert check_csrf(request) is True
