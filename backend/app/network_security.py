"""网络安全：SSRF 防护与 URL 白名单。

[H-03 修复] safe_fetch 改为异步 httpx.AsyncClient（不再阻塞事件循环），
使用模块级连接池复用，多跳重定向限制（最多 5 跳，每跳 SSRF 校验）。

[M-08 修复] 原实现 follow_redirects=False 后只检查第一跳 Location 头，
既不跟随也不校验后续跳；改为手动跟随重定向，每一跳都做协议/DNS/IP 校验，
防止攻击者通过 302 -> 302 -> 内网 多跳绕过 SSRF 检查。
"""

from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import logging
import socket
from typing import TYPE_CHECKING
from urllib.parse import urljoin, urlparse

from app.lazy_asyncio import LazyLock

if TYPE_CHECKING:
    import httpx

logger = logging.getLogger("network_security")

# ---- 黑名单：禁止访问的 IP 段 ----
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),  # loopback
    ipaddress.ip_network("10.0.0.0/8"),  # private class A
    ipaddress.ip_network("172.16.0.0/12"),  # private class B
    ipaddress.ip_network("192.168.0.0/16"),  # private class C
    ipaddress.ip_network("169.254.0.0/16"),  # link-local (含云元数据 169.254.169.254)
    ipaddress.ip_network("100.64.0.0/10"),  # CGNAT
    ipaddress.ip_network("0.0.0.0/8"),  # 任意地址
    ipaddress.ip_network("::/128"),  # IPv6 unspecified
    ipaddress.ip_network("::1/128"),  # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),  # IPv6 ULA
    ipaddress.ip_network("fe80::/10"),  # IPv6 link-local
    ipaddress.ip_network("::ffff:0:0/96"),  # IPv4-mapped IPv6
]

# 显式禁止的主机名（云元数据端点等）
_BLOCKED_HOSTNAMES = {
    "localhost",
    "metadata.google.internal",
    "metadata",
    "169.254.169.254",
    "fd00:ec2::254",  # AWS IMDSv6
}

ALLOWED_SCHEMES = frozenset({"http", "https"})
MAX_REDIRECTS = 5
DEFAULT_MAX_BYTES = 5 * 1024 * 1024
DEFAULT_TIMEOUT = 10.0

# 模块级 AsyncClient 连接池（lazy 初始化）
_async_client: httpx.AsyncClient | None = None
_client_lock = LazyLock()


def _is_blocked_ip(ip_str: str) -> bool:
    """判断 IP 是否在内网/保留黑名单中（失败关闭：无法解析一律拒绝）"""
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True
    # 标志位兜底：覆盖黑名单网段未显式列出的保留类别（multicast/reserved/unspecified 等）
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
        return True
    return any(ip in net for net in _BLOCKED_NETWORKS)


def parse_numeric_ip(hostname: str) -> str | None:
    """按 inet_aton 语义解析数字型 IP 变体，归一化为标准点分十进制。

    Chromium 等浏览器导航时按 inet_aton 语义解析主机名，例如：
    - ``http://2130706433/``   → 127.0.0.1（单个 32 位十进制数）
    - ``http://0x7f000001/``   → 127.0.0.1（十六进制）
    - ``http://0177.0.0.1/``   → 127.0.0.1（0 前缀段按八进制）
    - ``http://127.1/``        → 127.0.0.1（两段缩写，末段承载 24 位）

    Python 的 ``ipaddress`` 不认这些形式（抛 ValueError），若不归一化，
    它们会被当作普通域名绕过私网检查（SSRF 数字型变体绕过）。

    Returns:
        归一化后的标准 IPv4 字符串；不是数字型 IP 时返回 None。
    """
    if not hostname or ":" in hostname or "[" in hostname:
        return None  # IPv6 / 非法形式不走数字解析
    parts = hostname.split(".")
    if len(parts) > 4:
        return None
    values: list[int] = []
    for part in parts:
        if not part:
            return None
        try:
            if part.lower().startswith("0x"):
                value = int(part, 16)
            elif len(part) > 1 and part.startswith("0") and all(c in "01234567" for c in part):
                value = int(part, 8)
            else:
                value = int(part, 10)
        except ValueError:
            return None
        values.append(value)
    # inet_aton 分段位宽：末段承载剩余所有位
    bit_widths = {1: [32], 2: [8, 24], 3: [8, 8, 16], 4: [8, 8, 8, 8]}[len(values)]
    packed = 0
    for value, width in zip(values, bit_widths, strict=True):
        if value < 0 or value >= (1 << width):
            return None
        packed = (packed << width) | value
    return str(ipaddress.IPv4Address(packed))


def _resolve_and_check_dns(hostname: str) -> tuple[bool, str]:
    """DNS 解析并检查所有返回 IP 是否命中内网黑名单（防 DNS rebinding 初始检查）。

    注意：这是阻塞调用，异步上下文请使用 validate_url_async()。
    预检无法完全消除 DNS rebinding 的 TOCTOU（攻击者可在预检后切换解析），
    需配合 redirect-hop 复检拦截后续攻击路径。
    """
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as e:
        return False, f"DNS 解析失败: {e}"
    seen_ips: set[str] = set()
    for _family, _type, _proto, _canon, sockaddr in infos:
        ip_str = str(sockaddr[0])
        if ip_str in seen_ips:
            continue
        seen_ips.add(ip_str)
        if _is_blocked_ip(ip_str):
            return False, f"DNS 解析到内网 IP: {ip_str}"
    return True, "ok"


def validate_url(
    url: str,
    *,
    allowed_domains: set[str] | None = None,
    resolve_dns: bool = True,
) -> tuple[bool, str]:
    """验证 URL 是否安全可访问（全项目 SSRF 校验单一入口）。

    检查项：
    1. scheme 仅 http/https
    2. 拒绝 userinfo 绕过（http://evil.com@allowed.com）
    3. 黑名单主机名（localhost / 云元数据端点）
    4. 域名白名单（如提供）
    5. IP 字面量黑名单（含数字型变体：http://2130706433/ → 127.0.0.1）
    6. DNS 解析后所有 IP 黑名单（防 DNS rebinding 初始检查）

    注意：DNS 解析是阻塞调用。异步上下文请用 validate_url_async()。

    Args:
        url: 待验证的 URL
        allowed_domains: 可选白名单（域名字符串集合，子域名自动匹配）。
            为 None 时不限制域名但禁止内网 IP。
        resolve_dns: 是否解析 DNS 检查解析后的 IP（防 DNS rebinding）。

    Returns:
        (ok, reason): ok=True 表示通过，False 表示拒绝并附原因。
    """
    if not url:
        return False, "URL 为空"

    try:
        parsed = urlparse(url)
    except Exception as e:
        return False, f"URL 解析失败: {e}"

    if parsed.scheme not in ALLOWED_SCHEMES:
        return False, f"协议 {parsed.scheme!r} 不在白名单（仅 http/https）"

    if not parsed.hostname:
        return False, "URL 缺少主机名 (hostname)"

    hostname = parsed.hostname

    # 禁止 userinfo@hostname 形式绕过（http://evil.com@allowed.com 实际访问 evil.com）
    if parsed.username or parsed.password:
        return False, "URL 不允许包含 userinfo（防止绕过域名检查）"

    # 显式黑名单主机名
    if hostname.lower() in _BLOCKED_HOSTNAMES:
        return False, f"主机名 {hostname!r} 在禁止列表中"

    # 域名白名单检查
    if allowed_domains is not None:
        host_lower = hostname.lower()
        if not any(host_lower == d.lower() or host_lower.endswith("." + d.lower()) for d in allowed_domains):
            return False, f"域名 {host_lower!r} 不在白名单"

    # 主机名 → IP 检查（直接给 IP 字面量的情况）
    is_ip_literal = False
    try:
        ipaddress.ip_address(hostname)
        is_ip_literal = True
        if _is_blocked_ip(hostname):
            return False, f"私网/保留地址 '{hostname}' 被拒绝（内网黑名单）"
    except ValueError:
        # 数字型 IP 变体（十进制/八进制/十六进制，inet_aton 语义）
        # Chromium 会把 http://2130706433/ 解析为 127.0.0.1，必须归一化后校验
        numeric_ip = parse_numeric_ip(hostname)
        if numeric_ip is not None:
            is_ip_literal = True
            if _is_blocked_ip(numeric_ip):
                return False, f"数字型 IP 变体 {hostname!r} 归一化为 {numeric_ip}，在内网黑名单中"

    # DNS 解析后检查所有返回 IP（防 DNS rebinding 初始检查）
    # IP 字面量（含数字型变体）已在上一步判定，无需再解析
    if resolve_dns and not is_ip_literal:
        ok, reason = _resolve_and_check_dns(hostname)
        if not ok:
            return False, reason

    return True, "ok"


async def validate_url_async(
    url: str,
    *,
    allowed_domains: set[str] | None = None,
    resolve_dns: bool = True,
) -> tuple[bool, str]:
    """validate_url 的异步版本：DNS 解析放入线程池，避免阻塞事件循环。

    静态检查（scheme/黑名单/白名单/数字型 IP）同步完成；
    仅 DNS 解析部分经 asyncio.to_thread 执行（P1 异步事件循环纪律）。
    """
    ok, reason = validate_url(url, allowed_domains=allowed_domains, resolve_dns=False)
    if not ok or not resolve_dns:
        return ok, reason
    hostname = (urlparse(url).hostname or "").lower()
    # IP 字面量（含数字型变体）已在静态检查中判定，无需 DNS
    try:
        ipaddress.ip_address(hostname)
        return True, "ok"
    except ValueError:
        pass
    if parse_numeric_ip(hostname) is not None:
        return True, "ok"
    return await asyncio.to_thread(_resolve_and_check_dns, hostname)


async def _get_async_client() -> httpx.AsyncClient:
    """获取或创建模块级 AsyncClient 连接池"""
    global _async_client
    if _async_client is not None:
        return _async_client
    async with _client_lock:
        if _async_client is not None:
            return _async_client
        import httpx

        _async_client = httpx.AsyncClient(
            timeout=httpx.Timeout(DEFAULT_TIMEOUT, connect=5.0),
            follow_redirects=False,  # 我们手动跟随，以便每跳做 SSRF 校验
            max_redirects=0,
            trust_env=False,  # 不使用系统代理（防代理绕过 SSRF）
            headers={"User-Agent": "Conclave-SafeFetch/1.0"},
        )
        return _async_client


async def shutdown_async_client() -> None:
    """关闭模块级 AsyncClient（在应用关闭时调用）"""
    global _async_client
    async with _client_lock:
        if _async_client is not None:
            with contextlib.suppress(Exception):
                await _async_client.aclose()
            _async_client = None


async def safe_fetch(
    url: str,
    *,
    allowed_domains: set[str] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    max_bytes: int = DEFAULT_MAX_BYTES,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    max_redirects: int = MAX_REDIRECTS,
) -> tuple[bool, str | bytes]:
    """带 SSRF 防护的异步 HTTP 请求。

    [H-03 修复] 使用 httpx.AsyncClient 异步客户端，不阻塞事件循环。
    [M-08 修复] 手动跟随重定向，每一跳都做 SSRF 校验，最多 max_redirects 跳。

    Args:
        url: 目标 URL
        allowed_domains: 可选域名白名单
        timeout: 单次请求超时（秒）
        max_bytes: 最大响应字节数（防止大文件 OOM）
        method: HTTP 方法（默认 GET）
        headers: 额外请求头
        max_redirects: 最大重定向跳数

    Returns:
        (ok, content_or_reason): ok=True 时返回 bytes 内容，False 时返回错误原因字符串。
    """
    import httpx

    current_url = url
    seen_urls: set[str] = set()

    for hop in range(max_redirects + 1):
        # 每跳都做 SSRF 校验（异步版本：DNS 解析不阻塞事件循环）
        ok, reason = await validate_url_async(current_url, allowed_domains=allowed_domains)
        if not ok:
            # 审计：SSRF 阻断
            try:
                from app.observability.audit import audit

                audit(
                    "security.ssrf_blocked",
                    "blocked",
                    {
                        "url": current_url[:500],
                        "original_url": url[:500],
                        "hop": hop + 1,
                        "reason": reason,
                    },
                )
            except Exception as e:
                logger.debug("记录 SSRF 阻断审计日志失败: %s", e)
            return False, f"SSRF 检查失败（第{hop + 1}跳）: {reason}"

        # 防止循环重定向
        if current_url in seen_urls:
            return False, f"检测到重定向循环: {current_url}"
        seen_urls.add(current_url)

        try:
            client = await _get_async_client()
            req_headers = {"Accept": "*/*"}
            if headers:
                req_headers.update(headers)
            resp = await client.request(
                method if hop == 0 else "GET",
                current_url,
                headers=req_headers,
                timeout=httpx.Timeout(timeout, connect=5.0),
            )
        except httpx.TimeoutException:
            return False, f"请求超时（第{hop + 1}跳）"
        except httpx.ConnectError as e:
            return False, f"连接失败（第{hop + 1}跳）: {e}"
        except Exception as e:
            return False, f"请求失败（第{hop + 1}跳）: {type(e).__name__}: {e}"

        # 处理重定向
        if resp.status_code in (301, 302, 303, 307, 308):
            if hop >= max_redirects:
                return False, f"重定向次数超过限制（{max_redirects} 跳）"
            loc = resp.headers.get("location", "")
            if not loc:
                return False, f"重定向响应缺少 Location 头（状态码 {resp.status_code}）"
            # 解析相对 URL
            current_url = urljoin(current_url, loc)
            # 消耗响应体（连接复用）
            await resp.aclose()
            continue

        # 非重定向响应：读取并限制大小
        # 注意：不要用 resp.aread() 一次性读入（无大小限制），用流式读取
        chunks: list[bytes] = []
        total = 0
        try:
            async for chunk in resp.aiter_bytes(chunk_size=65536):
                total += len(chunk)
                if total > max_bytes:
                    await resp.aclose()
                    return False, f"响应超过大小限制（{max_bytes} 字节）"
                chunks.append(chunk)
        except Exception as e:
            return False, f"读取响应失败: {type(e).__name__}: {e}"
        finally:
            await resp.aclose()

        body = b"".join(chunks)
        return True, body

    return False, "重定向次数超限（不应到达此处）"


async def safe_fetch_text(
    url: str,
    *,
    allowed_domains: set[str] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    max_bytes: int = DEFAULT_MAX_BYTES,
    encoding: str = "utf-8",
) -> tuple[bool, str]:
    """safe_fetch 的文本便捷封装"""
    ok, result = await safe_fetch(
        url,
        allowed_domains=allowed_domains,
        timeout=timeout,
        max_bytes=max_bytes,
    )
    if not ok:
        return False, result  # type: ignore[return-value]
    assert isinstance(result, bytes)
    return True, result.decode(encoding, errors="replace")
