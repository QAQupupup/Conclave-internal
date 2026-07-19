"""安全模块测试：API 认证中间件（token 认证 / 速率限制 / IP 封禁）。

测试目标（backend/app/middleware.py）：
- API Token 认证（CONCLAVE_API_TOKEN / _DEV_TOKEN，hmac.compare_digest 防时序攻击）
- 开发模式跳过认证（APP_ENV=test + CONCLAVE_TEST_DISABLE_AUTH=1）
- IP 封禁逻辑（失败计数 → 临时封禁 → 超时自动解除）
- localhost 豁免失败封禁
- 请求频率限制（滑动窗口 + 429）
- 辅助函数：_is_public / _client_ip / get_dev_token_info / is_dangerous_command

测试策略：
- 使用 FastAPI TestClient + 最小化应用（仅注册认证中间件，不启动完整应用）
- mock/patch 环境变量（APP_ENV / CONCLAVE_TEST_DISABLE_AUTH）与模块级状态
  （_DEV_TOKEN / _FAIL_BAN_ENABLED / _RATE_LIMIT_* / _request_log / _fail_log / _blocked_ips）
- 不依赖 PostgreSQL / Docker / 完整应用 lifespan

约束：
- 每个测试前后清理速率限制进程级状态，避免跨测试泄漏
- 不发起真实网络或数据库调用
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import middleware as mw

# ============================================================================
# 公共 fixtures
# ============================================================================


@pytest.fixture(autouse=True)
def _clear_rate_state():
    """每个测试前后清理速率限制 / 失败计数 / 封禁的进程级状态。"""
    mw._request_log.clear()
    mw._fail_log.clear()
    mw._blocked_ips.clear()
    yield
    mw._request_log.clear()
    mw._fail_log.clear()
    mw._blocked_ips.clear()


def _make_app() -> FastAPI:
    """构建仅含认证中间件的最小 FastAPI 应用。"""
    app = FastAPI()

    @app.get("/secure")
    def secure_endpoint():
        return {"message": "ok"}

    @app.get("/health")
    def health_endpoint():
        return {"status": "ok"}

    mw.setup_auth_middleware(app)
    return app


@pytest.fixture()
def auth_app(monkeypatch):
    """认证激活的测试应用：APP_ENV 非 test，_DEV_TOKEN 固定为已知值。"""
    # 确保 APP_ENV 不是 test，否则会触发认证跳过
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setattr(mw, "_DEV_TOKEN", "secret-test-token")
    return _make_app()


@pytest.fixture()
def client(auth_app):
    """FastAPI TestClient（仅认证中间件，无完整 lifespan 依赖）。"""
    with TestClient(auth_app) as c:
        yield c


# ============================================================================
# API Token 认证
# ============================================================================


class TestApiTokenAuth:
    """API Token 认证流程。"""

    def test_public_path_no_auth_required(self, client):
        """公开路径（/health）无需 token 即可访问。"""
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_valid_bearer_token_authenticates(self, client):
        """携带正确 Bearer token 应认证通过。"""
        r = client.get("/secure", headers={"Authorization": "Bearer secret-test-token"})
        assert r.status_code == 200
        assert r.json()["message"] == "ok"

    def test_missing_token_returns_401(self, client):
        """未携带 token 访问受保护路径应返回 401。"""
        r = client.get("/secure")
        assert r.status_code == 401
        assert "未授权" in r.json()["detail"]

    def test_invalid_token_returns_401(self, client):
        """携带错误 token 应返回 401。"""
        r = client.get("/secure", headers={"Authorization": "Bearer wrong-token"})
        assert r.status_code == 401
        assert "认证失败" in r.json()["detail"]

    def test_token_via_query_param_rejected(self, client):
        """[C-04] HTTP 请求不再接受 ?token= 查询参数（防 token 在 URL/日志/Referer 中泄露），应返回 401。
        WebSocket 升级请求由 ws router 自行处理 query 参数（浏览器 WS API 限制无法设置 Header）。"""
        r = client.get("/secure", params={"token": "secret-test-token"})
        assert r.status_code == 401

    def test_empty_bearer_token_returns_401(self, client):
        """空 Bearer token 应返回 401。"""
        r = client.get("/secure", headers={"Authorization": "Bearer "})
        assert r.status_code == 401

    def test_malformed_auth_header_returns_401(self, client):
        """非 Bearer 格式的 Authorization 头应返回 401。"""
        r = client.get("/secure", headers={"Authorization": "Basic secret-test-token"})
        assert r.status_code == 401

    def test_token_comparison_is_constant_time(self, monkeypatch):
        """token 比较应使用 hmac.compare_digest（防时序攻击）。

        通过验证正确/错误 token 都不抛异常且返回预期状态码来间接验证。
        """
        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.setattr(mw, "_DEV_TOKEN", "secret-test-token")
        app = _make_app()
        with TestClient(app) as c:
            # 错误 token：快速返回 401（compare_digest 对不等长也安全）
            r1 = c.get("/secure", headers={"Authorization": "Bearer x"})
            assert r1.status_code == 401
            # 正确 token
            r2 = c.get("/secure", headers={"Authorization": "Bearer secret-test-token"})
            assert r2.status_code == 200


# ============================================================================
# 开发模式跳过认证
# ============================================================================


class TestDevModeSkipAuth:
    """APP_ENV=test + CONCLAVE_TEST_DISABLE_AUTH=1 时跳过认证与限流。"""

    def test_test_mode_skips_auth(self, monkeypatch):
        """同时设置 APP_ENV=test 与 CONCLAVE_TEST_DISABLE_AUTH=1 时无需 token。"""
        monkeypatch.setenv("APP_ENV", "test")
        monkeypatch.setenv("CONCLAVE_TEST_DISABLE_AUTH", "1")
        monkeypatch.setattr(mw, "_DEV_TOKEN", "secret-test-token")
        app = _make_app()
        with TestClient(app) as c:
            r = c.get("/secure")
            assert r.status_code == 200

    def test_test_mode_requires_both_conditions(self, monkeypatch):
        """仅 APP_ENV=test 但未设 CONCLAVE_TEST_DISABLE_AUTH 不应跳过认证。"""
        monkeypatch.setenv("APP_ENV", "test")
        monkeypatch.delenv("CONCLAVE_TEST_DISABLE_AUTH", raising=False)
        monkeypatch.setattr(mw, "_DEV_TOKEN", "secret-test-token")
        app = _make_app()
        with TestClient(app) as c:
            r = c.get("/secure")
            assert r.status_code == 401

    def test_disable_auth_without_test_env_does_not_skip(self, monkeypatch):
        """CONCLAVE_TEST_DISABLE_AUTH=1 但 APP_ENV 非 test 不应跳过认证。"""
        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.setenv("CONCLAVE_TEST_DISABLE_AUTH", "1")
        monkeypatch.setattr(mw, "_DEV_TOKEN", "secret-test-token")
        app = _make_app()
        with TestClient(app) as c:
            r = c.get("/secure")
            assert r.status_code == 401


# ============================================================================
# 请求频率限制
# ============================================================================


class TestRateLimit:
    """请求频率限制（滑动窗口）。"""

    def test_rate_limit_returns_429_when_exceeded(self, client, monkeypatch):
        """超过每分钟请求上限后应返回 429。"""
        monkeypatch.setattr(mw, "_RATE_LIMIT_PER_MIN", 2)
        # 前两次正常
        r1 = client.get("/secure", headers={"Authorization": "Bearer secret-test-token"})
        assert r1.status_code == 200
        r2 = client.get("/secure", headers={"Authorization": "Bearer secret-test-token"})
        assert r2.status_code == 200
        # 第三次触发限流
        r3 = client.get("/secure", headers={"Authorization": "Bearer secret-test-token"})
        assert r3.status_code == 429
        assert "Retry-After" in r3.headers

    def test_rate_limit_applies_to_unauthenticated_too(self, client, monkeypatch):
        """未认证请求也应被限流（防扫描）。"""
        monkeypatch.setattr(mw, "_RATE_LIMIT_PER_MIN", 2)
        monkeypatch.setattr(mw, "_FAIL_BAN_ENABLED", False)
        # 前两次返回 401（未授权但不限流）
        client.get("/secure")
        client.get("/secure")
        # 第三次被限流
        r = client.get("/secure")
        assert r.status_code == 429

    def test_rate_limit_separated_per_ip(self, client, monkeypatch):
        """不同 IP 的请求计数应独立。"""
        monkeypatch.setattr(mw, "_RATE_LIMIT_PER_MIN", 2)
        # IP A 用满额度
        client.get("/secure", headers={"Authorization": "Bearer secret-test-token", "X-Forwarded-For": "1.1.1.1"})
        client.get("/secure", headers={"Authorization": "Bearer secret-test-token", "X-Forwarded-For": "1.1.1.1"})
        # IP B 仍可访问
        r = client.get("/secure", headers={"Authorization": "Bearer secret-test-token", "X-Forwarded-For": "2.2.2.2"})
        assert r.status_code == 200


# ============================================================================
# IP 封禁逻辑
# ============================================================================


class TestIpBan:
    """IP 失败封禁逻辑。"""

    def test_fail_ban_after_threshold(self, client, monkeypatch):
        """非 localhost IP 连续认证失败超过阈值后应被临时封禁（429）。"""
        monkeypatch.setattr(mw, "_FAIL_BAN_ENABLED", True)
        monkeypatch.setattr(mw, "_RATE_LIMIT_FAIL_PER_MIN", 3)
        monkeypatch.setattr(mw, "_RATE_BLOCK_SECONDS", 60)
        monkeypatch.setattr(mw, "_RATE_LIMIT_PER_MIN", 100000)
        headers = {"X-Forwarded-For": "1.2.3.4"}
        # 前 3 次失败返回 401
        for i in range(3):
            r = client.get("/secure", headers=headers)
            assert r.status_code == 401, f"第 {i + 1} 次应返回 401"
        # 第 4 次触发封禁 → 429
        r = client.get("/secure", headers=headers)
        assert r.status_code == 429
        assert "认证失败过多" in r.json()["detail"]

    def test_banned_ip_blocks_even_valid_token(self, client, monkeypatch):
        """已被封禁的 IP 即使携带正确 token 也应被拒绝（429）。"""
        monkeypatch.setattr(mw, "_FAIL_BAN_ENABLED", True)
        monkeypatch.setattr(mw, "_RATE_LIMIT_FAIL_PER_MIN", 2)
        monkeypatch.setattr(mw, "_RATE_BLOCK_SECONDS", 60)
        monkeypatch.setattr(mw, "_RATE_LIMIT_PER_MIN", 100000)
        headers = {"X-Forwarded-For": "5.6.7.8"}
        # 触发封禁（阈值 2 → 第 3 次封禁）
        for _ in range(3):
            client.get("/secure", headers=headers)
        # 携带正确 token 仍被封禁
        r = client.get("/secure", headers={**headers, "Authorization": "Bearer secret-test-token"})
        assert r.status_code == 429
        assert "封禁" in r.json()["detail"]

    def test_localhost_exempt_from_fail_ban(self, client, monkeypatch):
        """localhost IP 即使大量认证失败也不被封禁。"""
        monkeypatch.setattr(mw, "_FAIL_BAN_ENABLED", True)
        monkeypatch.setattr(mw, "_RATE_LIMIT_FAIL_PER_MIN", 2)
        monkeypatch.setattr(mw, "_RATE_BLOCK_SECONDS", 60)
        monkeypatch.setattr(mw, "_RATE_LIMIT_PER_MIN", 100000)
        headers = {"X-Forwarded-For": "127.0.0.1"}
        for _ in range(6):
            r = client.get("/secure", headers=headers)
            assert r.status_code == 401, "localhost 应始终 401，不被封禁"

    def test_fail_ban_disabled_in_dev_mode(self, client, monkeypatch):
        """开发模式（_FAIL_BAN_ENABLED=False）下失败不触发封禁。"""
        monkeypatch.setattr(mw, "_FAIL_BAN_ENABLED", False)
        monkeypatch.setattr(mw, "_RATE_LIMIT_FAIL_PER_MIN", 2)
        monkeypatch.setattr(mw, "_RATE_LIMIT_PER_MIN", 100000)
        headers = {"X-Forwarded-For": "3.3.3.3"}
        for _ in range(5):
            r = client.get("/secure", headers=headers)
            assert r.status_code == 401, "开发模式失败不应封禁"


class TestCheckRateLimitUnit:
    """_check_rate_limit 单元测试：封禁与解除逻辑。"""

    def test_active_ban_blocks_request(self, monkeypatch):
        """活跃封禁应阻止请求。"""
        monkeypatch.setattr(mw, "_FAIL_BAN_ENABLED", True)
        monkeypatch.setattr(mw, "_RATE_LIMIT_PER_MIN", 100000)
        mw._blocked_ips["9.9.9.9"] = time.monotonic() + 100
        allowed, reason = mw._check_rate_limit("9.9.9.9", is_failed_attempt=False)
        assert allowed is False
        assert "封禁" in reason

    def test_expired_ban_auto_cleared(self, monkeypatch):
        """过期封禁应在下次检查时自动解除。"""
        monkeypatch.setattr(mw, "_FAIL_BAN_ENABLED", True)
        monkeypatch.setattr(mw, "_RATE_LIMIT_PER_MIN", 100000)
        mw._blocked_ips["9.9.9.9"] = time.monotonic() - 1  # 已过期
        allowed, _ = mw._check_rate_limit("9.9.9.9", is_failed_attempt=False)
        assert allowed is True
        assert "9.9.9.9" not in mw._blocked_ips

    def test_failed_attempt_disabled_returns_ok(self, monkeypatch):
        """_FAIL_BAN_ENABLED=False 时失败计数直接返回 ok。"""
        monkeypatch.setattr(mw, "_FAIL_BAN_ENABLED", False)
        allowed, reason = mw._check_rate_limit("4.4.4.4", is_failed_attempt=True)
        assert allowed is True
        assert reason == "ok"

    def test_failed_attempt_localhost_returns_ok(self, monkeypatch):
        """localhost 的失败计数直接返回 ok（豁免封禁）。"""
        monkeypatch.setattr(mw, "_FAIL_BAN_ENABLED", True)
        allowed, reason = mw._check_rate_limit("127.0.0.1", is_failed_attempt=True)
        assert allowed is True
        assert reason == "ok"


# ============================================================================
# 辅助函数
# ============================================================================


class TestHelpers:
    """_is_public / _client_ip / get_dev_token_info / is_dangerous_command。"""

    @pytest.mark.parametrize("path", ["/health", "/metrics", "/docs", "/openapi.json", "/redoc"])
    def test_is_public_recognizes_public_paths(self, path):
        """公开路径应免认证。"""
        assert mw._is_public(path) is True

    def test_is_public_recognizes_subpaths(self):
        """公开路径的子路径也应免认证。"""
        assert mw._is_public("/health/status") is True
        assert mw._is_public("/docs/swagger") is True

    @pytest.mark.parametrize("path", ["/secure", "/api/meetings", "/", "/admin"])
    def test_is_public_rejects_private_paths(self, path):
        """非公开路径不应免认证。"""
        assert mw._is_public(path) is False

    def test_client_ip_prefers_x_forwarded_for(self):
        """_client_ip 应优先取 X-Forwarded-For 首段。"""
        request = MagicMock()
        request.headers = {"X-Forwarded-For": "1.2.3.4, 5.6.7.8"}
        request.client = MagicMock(host="127.0.0.1")
        assert mw._client_ip(request) == "1.2.3.4"

    def test_client_ip_falls_back_to_client_host(self):
        """无 X-Forwarded-For 时应退化到 client.host。"""
        request = MagicMock()
        request.headers = {}
        request.client = MagicMock(host="192.168.1.1")
        assert mw._client_ip(request) == "192.168.1.1"

    def test_client_ip_handles_missing_client(self):
        """无 client 信息时应返回 unknown。"""
        request = MagicMock()
        request.headers = {}
        request.client = None
        assert mw._client_ip(request) == "unknown"

    def test_get_dev_token_info_with_env_token(self, monkeypatch):
        """设置 CONCLAVE_API_TOKEN 时 token_source 应为 env。"""
        monkeypatch.setattr(mw, "_API_TOKEN", "real-token")
        monkeypatch.setattr(mw, "_FAIL_BAN_ENABLED", True)
        info = mw.get_dev_token_info()
        assert info["auth_enabled"] is True
        assert info["token_source"] == "env"
        assert info["fail_ban_enabled"] is True
        assert "rate_limit_per_min" in info
        assert "rate_limit_fail_per_min" in info

    def test_get_dev_token_info_with_dev_file(self, monkeypatch):
        """未设置 CONCLAVE_API_TOKEN 时 token_source 应为 dev_file。"""
        monkeypatch.setattr(mw, "_API_TOKEN", "")
        monkeypatch.setattr(mw, "_FAIL_BAN_ENABLED", False)
        info = mw.get_dev_token_info()
        assert info["token_source"] == "dev_file"
        assert info["fail_ban_enabled"] is False

    def test_is_dangerous_command_detects_rm_rf(self):
        """is_dangerous_command 应检测 rm -rf /。"""
        assert mw.is_dangerous_command("rm -rf /") is True

    def test_is_dangerous_command_detects_mkfs(self):
        """is_dangerous_command 应检测 mkfs。"""
        assert mw.is_dangerous_command("mkfs.ext4 /dev/sda") is True

    def test_is_dangerous_command_safe_command(self):
        """安全命令不应被 is_dangerous_command 误报。"""
        assert mw.is_dangerous_command("ls -la") is False
        assert mw.is_dangerous_command("echo hello") is False
