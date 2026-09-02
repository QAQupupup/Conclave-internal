"""network_security SSRF 防护专项测试。

测试范围（P1 修复：数字型 IP 变体绕过 + DNS 解析校验 + 双实现合并）：
- parse_numeric_ip()     inet_aton 语义数字型 IP 归一化（十进制/十六进制/八进制/缩写段）
- _is_blocked_ip()        内网/保留 IP 黑名单（失败关闭）
- validate_url()          静态校验（scheme/黑名单/白名单/IP 字面量/userinfo）
- validate_url_async()    异步校验（DNS 解析在线程池，mock getaddrinfo 不依赖外网）
- playwright/security 兼容 shim 回归（原漏洞入口）

非正向用例覆盖：数字型变体绕过、DNS 解析到内网、DNS 解析失败、
userinfo 绕过、危险 scheme、白名单不匹配、非法输入。

运行方式：
    cd backend
    pytest tests/test_network_security.py -v
"""

from __future__ import annotations

import socket
from unittest.mock import patch

import pytest

from app.network_security import (
    _is_blocked_ip,
    parse_numeric_ip,
    validate_url,
    validate_url_async,
)

# ============================================================================
# 1. parse_numeric_ip() — inet_aton 语义数字型 IP 归一化
# ============================================================================


class TestParseNumericIp:
    """数字型 IP 变体解析（SSRF 绕过攻击的核心归一化函数）。"""

    def test_decimal_single_32bit(self):
        """单个 32 位十进制数：2130706433 → 127.0.0.1（审计报告中的原始绕过形式）"""
        assert parse_numeric_ip("2130706433") == "127.0.0.1"

    def test_hex_single(self):
        """十六进制：0x7f000001 → 127.0.0.1"""
        assert parse_numeric_ip("0x7f000001") == "127.0.0.1"

    def test_hex_uppercase(self):
        """十六进制大小写不敏感"""
        assert parse_numeric_ip("0X7F000001") == "127.0.0.1"

    def test_octal_leading_zero(self):
        """0 前缀段按八进制：0177.0.0.1 → 127.0.0.1"""
        assert parse_numeric_ip("0177.0.0.1") == "127.0.0.1"

    def test_two_part_shorthand(self):
        """两段缩写，末段承载 24 位：127.1 → 127.0.0.1"""
        assert parse_numeric_ip("127.1") == "127.0.0.1"

    def test_three_part_shorthand(self):
        """三段缩写，末段承载 16 位：192.168.1 → 192.168.0.1"""
        assert parse_numeric_ip("192.168.1") == "192.168.0.1"

    def test_normal_dotted_quad(self):
        """标准点分十进制原样归一化"""
        assert parse_numeric_ip("192.168.1.1") == "192.168.1.1"

    def test_zero(self):
        """单个 0 → 0.0.0.0"""
        assert parse_numeric_ip("0") == "0.0.0.0"

    def test_mixed_hex_and_decimal(self):
        """混合进制：0x7f.0.0.1 → 127.0.0.1"""
        assert parse_numeric_ip("0x7f.0.0.1") == "127.0.0.1"

    # ---- 非正向：不应解析的形式 ----

    def test_regular_hostname_not_parsed(self):
        """普通域名不是数字型 IP"""
        assert parse_numeric_ip("example.com") is None

    def test_out_of_range_octet(self):
        """段值超位宽：256.0.0.1 非法"""
        assert parse_numeric_ip("256.0.0.1") is None

    def test_two_part_last_overflow(self):
        """两段缩写末段超 24 位：127.16777216 非法"""
        assert parse_numeric_ip("127.16777216") is None

    def test_too_many_parts(self):
        """超过 4 段非法"""
        assert parse_numeric_ip("1.2.3.4.5") is None

    def test_ipv6_not_parsed(self):
        """IPv6 字面量不走数字解析"""
        assert parse_numeric_ip("::1") is None
        assert parse_numeric_ip("[::1]") is None

    def test_empty_string(self):
        """空字符串"""
        assert parse_numeric_ip("") is None

    def test_empty_octet(self):
        """空段非法：127..0.1"""
        assert parse_numeric_ip("127..0.1") is None

    def test_octal_with_non_octal_digit(self):
        """0 前缀但含 8/9 数字（非八进制），按十进制回退：018 → 18"""
        assert parse_numeric_ip("018.0.0.1") == "18.0.0.1"


# ============================================================================
# 2. _is_blocked_ip() — 内网/保留 IP 黑名单
# ============================================================================


class TestIsBlockedIp:
    def test_loopback_blocked(self):
        assert _is_blocked_ip("127.0.0.1") is True

    def test_private_class_a_blocked(self):
        assert _is_blocked_ip("10.1.2.3") is True

    def test_private_class_c_blocked(self):
        assert _is_blocked_ip("192.168.1.1") is True

    def test_link_local_metadata_blocked(self):
        """云元数据端点 169.254.169.254"""
        assert _is_blocked_ip("169.254.169.254") is True

    def test_cgnat_blocked(self):
        assert _is_blocked_ip("100.64.0.1") is True

    def test_ipv6_loopback_blocked(self):
        assert _is_blocked_ip("::1") is True

    def test_ipv4_mapped_ipv6_blocked(self):
        """IPv4-mapped IPv6（::ffff:127.0.0.1）不能绕过"""
        assert _is_blocked_ip("::ffff:127.0.0.1") is True

    def test_public_ip_allowed(self):
        assert _is_blocked_ip("8.8.8.8") is False
        assert _is_blocked_ip("93.184.216.34") is False

    def test_unparseable_fail_closed(self):
        """失败关闭：无法解析的一律拒绝"""
        assert _is_blocked_ip("not-an-ip") is True


# ============================================================================
# 3. validate_url() — 静态校验（不做 DNS）
# ============================================================================


class TestValidateUrlStatic:
    """resolve_dns=False 的静态校验（不触网）。"""

    def test_public_https_ok(self):
        ok, reason = validate_url("https://docs.python.org/3/", resolve_dns=False)
        assert ok is True
        assert reason == "ok"

    def test_public_ip_literal_ok(self):
        ok, _ = validate_url("http://8.8.8.8/", resolve_dns=False)
        assert ok is True

    # ---- 非正向：scheme ----

    def test_file_scheme_rejected(self):
        ok, reason = validate_url("file:///etc/passwd", resolve_dns=False)
        assert ok is False
        assert "file" in reason

    def test_javascript_scheme_rejected(self):
        ok, _ = validate_url("javascript:alert(1)", resolve_dns=False)
        assert ok is False

    def test_empty_url_rejected(self):
        ok, _ = validate_url("", resolve_dns=False)
        assert ok is False

    # ---- 非正向：内网 IP 字面量 ----

    def test_loopback_rejected(self):
        ok, _ = validate_url("http://127.0.0.1:8080/api", resolve_dns=False)
        assert ok is False

    def test_metadata_ip_rejected(self):
        ok, _ = validate_url("http://169.254.169.254/latest/meta-data/", resolve_dns=False)
        assert ok is False

    # ---- 非正向：数字型 IP 变体（P1 核心回归）----

    def test_numeric_decimal_variant_rejected(self):
        """http://2130706433/ → 127.0.0.1，必须拦截（审计报告原始用例）"""
        ok, reason = validate_url("http://2130706433/", resolve_dns=False)
        assert ok is False
        assert "2130706433" in reason or "127.0.0.1" in reason

    def test_numeric_hex_variant_rejected(self):
        ok, _ = validate_url("http://0x7f000001/", resolve_dns=False)
        assert ok is False

    def test_numeric_octal_variant_rejected(self):
        ok, _ = validate_url("http://0177.0.0.1/", resolve_dns=False)
        assert ok is False

    def test_numeric_two_part_variant_rejected(self):
        ok, _ = validate_url("http://127.1/", resolve_dns=False)
        assert ok is False

    def test_numeric_variant_of_private_rejected(self):
        """十进制变体指向 192.168.1.1（3232235777）同样拦截"""
        ok, _ = validate_url("http://3232235777/", resolve_dns=False)
        assert ok is False

    # ---- 非正向：黑名单主机名 ----

    def test_localhost_rejected(self):
        ok, _ = validate_url("http://localhost:8000/admin", resolve_dns=False)
        assert ok is False

    def test_metadata_hostname_rejected(self):
        ok, _ = validate_url("http://metadata.google.internal/computeMetadata/v1/", resolve_dns=False)
        assert ok is False

    # ---- 非正向：userinfo 绕过 ----

    def test_userinfo_rejected(self):
        ok, _ = validate_url("http://trusted@evil.com/admin", resolve_dns=False)
        assert ok is False

    def test_user_pass_rejected(self):
        ok, _ = validate_url("https://user:pass@example.com/", resolve_dns=False)
        assert ok is False

    # ---- 域名白名单 ----

    def test_allowed_domain_exact_match(self):
        ok, _ = validate_url("https://example.com/page", allowed_domains={"example.com"}, resolve_dns=False)
        assert ok is True

    def test_allowed_domain_subdomain_match(self):
        ok, _ = validate_url("https://api.example.com/v1", allowed_domains={"example.com"}, resolve_dns=False)
        assert ok is True

    def test_allowed_domain_mismatch_rejected(self):
        ok, reason = validate_url("https://evil.com/page", allowed_domains={"example.com"}, resolve_dns=False)
        assert ok is False
        assert "白名单" in reason

    def test_allowed_domain_suffix_trick_rejected(self):
        """notexample.com 不能匹配 example.com（防后缀伪造）"""
        ok, _ = validate_url("https://notexample.com/page", allowed_domains={"example.com"}, resolve_dns=False)
        assert ok is False


# ============================================================================
# 4. validate_url_async() — 异步校验（DNS 解析走线程池，mock 不触网）
# ============================================================================


def _fake_addrinfo(*ips: str):
    """构造 socket.getaddrinfo 风格的返回值"""

    def _resolver(hostname, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 80)) for ip in ips]

    return _resolver


class TestValidateUrlAsync:
    async def test_ip_literal_skips_dns(self):
        """IP 字面量无需 DNS 解析（公网 IP 直接放行）"""
        with patch("app.network_security.socket.getaddrinfo") as mock_dns:
            ok, _ = await validate_url_async("http://8.8.8.8/")
            assert ok is True
            mock_dns.assert_not_called()

    async def test_numeric_variant_rejected_without_dns(self):
        """数字型变体在静态检查即拦截，不走 DNS"""
        with patch("app.network_security.socket.getaddrinfo") as mock_dns:
            ok, _ = await validate_url_async("http://2130706433/")
            assert ok is False
            mock_dns.assert_not_called()

    async def test_dns_resolving_to_internal_rejected(self):
        """DNS 解析到内网 IP → 拦截（防 DNS rebinding 初始检查）"""
        with patch("app.network_security.socket.getaddrinfo", _fake_addrinfo("127.0.0.1")):
            ok, reason = await validate_url_async("https://rebind.attacker.com/")
            assert ok is False
            assert "127.0.0.1" in reason

    async def test_dns_multi_record_any_internal_rejected(self):
        """多 A 记录中任一解析到内网即拦截"""
        with patch(
            "app.network_security.socket.getaddrinfo",
            _fake_addrinfo("93.184.216.34", "10.0.0.1"),
        ):
            ok, _ = await validate_url_async("https://mixed.attacker.com/")
            assert ok is False

    async def test_dns_resolving_to_public_ok(self):
        """DNS 解析到公网 IP → 放行"""
        with patch("app.network_security.socket.getaddrinfo", _fake_addrinfo("93.184.216.34")):
            ok, _ = await validate_url_async("https://example.com/")
            assert ok is True

    async def test_dns_failure_fail_closed(self):
        """DNS 解析失败 → 失败关闭"""

        def _raise(hostname, port, *args, **kwargs):
            raise socket.gaierror("Name or service not known")

        with patch("app.network_security.socket.getaddrinfo", _raise):
            ok, reason = await validate_url_async("https://nonexistent.invalid/")
            assert ok is False
            assert "DNS" in reason

    async def test_resolve_dns_false_skips_resolution(self):
        """resolve_dns=False 时不做 DNS 解析"""
        with patch("app.network_security.socket.getaddrinfo") as mock_dns:
            ok, _ = await validate_url_async("https://example.com/", resolve_dns=False)
            assert ok is True
            mock_dns.assert_not_called()


# ============================================================================
# 5. 兼容 shim 回归（playwright/security.py，原漏洞入口）
# ============================================================================


class TestPlaywrightSecurityShim:
    """playwright/security.py 已委托 network_security，行为必须一致。"""

    def test_shim_rejects_numeric_variant(self):
        """原漏洞回归：_is_safe_url 必须拦截数字型 IP 变体"""
        from app.tools.playwright.security import _is_safe_url

        ok, _ = _is_safe_url("http://2130706433/")
        assert ok is False

    def test_shim_rejects_private_ip(self):
        from app.tools.playwright.security import _is_safe_url

        ok, _ = _is_safe_url("http://192.168.1.1/admin")
        assert ok is False

    def test_shim_accepts_public_url(self):
        from app.tools.playwright.security import _is_safe_url

        ok, _ = _is_safe_url("https://docs.python.org/3/")
        assert ok is True

    async def test_shim_async_dns_check(self):
        """异步 shim 执行 DNS 校验"""
        from app.tools.playwright.security import _is_safe_url_async

        with patch("app.network_security.socket.getaddrinfo", _fake_addrinfo("169.254.169.254")):
            ok, _ = await _is_safe_url_async("https://rebind.attacker.com/")
            assert ok is False


# ============================================================================
# 6. browser_tool 委托回归（_is_url_allowed 异步化）
# ============================================================================


class TestBrowserToolDelegation:
    """browser_tool._is_url_allowed 已委托 validate_url_async。"""

    async def test_browser_tool_rejects_numeric_variant(self):
        from app.tools.browser_tool import _is_url_allowed

        ok, _ = await _is_url_allowed("http://2130706433/")
        assert ok is False

    async def test_browser_tool_rejects_file_scheme(self):
        from app.tools.browser_tool import _is_url_allowed

        ok, _ = await _is_url_allowed("file:///etc/passwd")
        assert ok is False

    async def test_browser_tool_accepts_public_url(self):
        from app.tools.browser_tool import _is_url_allowed

        with patch("app.network_security.socket.getaddrinfo", _fake_addrinfo("93.184.216.34")):
            ok, _ = await _is_url_allowed("https://example.com/")
            assert ok is True

    def test_wildcard_allowed_domains_normalized(self):
        """通配符白名单 *.github.com 归一化为 github.com"""
        from unittest.mock import patch as _patch

        from app.tools import browser_tool

        with _patch.object(browser_tool, "ALLOWED_DOMAINS", ["*.github.com", "example.com"]):
            assert browser_tool._normalized_allowed_domains() == {"github.com", "example.com"}

    def test_empty_allowed_domains_returns_none(self):
        from unittest.mock import patch as _patch

        from app.tools import browser_tool

        with _patch.object(browser_tool, "ALLOWED_DOMAINS", []):
            assert browser_tool._normalized_allowed_domains() is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
