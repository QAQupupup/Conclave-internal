"""网络安全：SSRF 防护与 URL 白名单。

[CON-14 修复] 旧版对外部 URL（用户提供的图片 URL、evidence 来源等）缺少 SSRF 防护。
   攻击场景：用户提交 `http://169.254.169.254/latest/meta-data/` 可读取云元数据。
   本模块提供：
   1. 内网 IP 段黑名单（RFC 1918、链路本地、回环、IPv6 link-local 等）
   2. URL 解析 + DNS 解析 + IP 校验三层防御
   3. 用户可配置允许的域名白名单
"""
from __future__ import annotations

import ipaddress
import socket
from typing import Optional
from urllib.parse import urlparse

# ---- 黑名单：禁止访问的 IP 段 ----
# RFC 1918 私有网段、loopback、link-local、metadata 服务、IPv6 私网/回环
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),          # loopback
    ipaddress.ip_network("10.0.0.0/8"),           # private class A
    ipaddress.ip_network("172.16.0.0/12"),        # private class B
    ipaddress.ip_network("192.168.0.0/16"),       # private class C
    ipaddress.ip_network("169.254.0.0/16"),       # link-local (含云元数据 169.254.169.254)
    ipaddress.ip_network("100.64.0.0/10"),        # CGNAT
    ipaddress.ip_network("0.0.0.0/8"),             # 任意地址
    ipaddress.ip_network("::1/128"),              # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),             # IPv6 ULA
    ipaddress.ip_network("fe80::/10"),            # IPv6 link-local
    ipaddress.ip_network("::ffff:0:0/96"),        # IPv4-mapped IPv6
]

# ---- 允许的协议 ----
ALLOWED_SCHEMES = frozenset({"http", "https"})


def _is_blocked_ip(ip_str: str) -> bool:
    """判断 IP 是否在内网黑名单中"""
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True  # 无效 IP 视为不安全
    return any(ip in net for net in _BLOCKED_NETWORKS)


def validate_url(
    url: str,
    *,
    allowed_domains: Optional[set[str]] = None,
    resolve_dns: bool = True,
) -> tuple[bool, str]:
    """验证 URL 是否安全可访问。

    Args:
        url: 待验证的 URL
        allowed_domains: 可选白名单（域名字符串集合）。为 None 时不限制域名但禁止内网 IP。
        resolve_dns: 是否解析 DNS 检查解析后的 IP（防 DNS rebinding）。

    Returns:
        (ok, reason): ok=True 表示通过，False 表示拒绝并附原因。
    """
    if not url:
        return False, "URL 为空"

    # 1) 协议检查
    try:
        parsed = urlparse(url)
    except Exception as e:
        return False, f"URL 解析失败: {e}"

    if parsed.scheme not in ALLOWED_SCHEMES:
        return False, f"协议 {parsed.scheme!r} 不在白名单（仅 http/https）"

    if not parsed.hostname:
        return False, "URL 缺少主机名"

    # 2) 域名白名单检查
    if allowed_domains is not None:
        host = parsed.hostname.lower()
        if not any(host == d.lower() or host.endswith("." + d.lower()) for d in allowed_domains):
            return False, f"域名 {host!r} 不在白名单"

    # 3) 主机名 → IP 检查（直接给 IP 的情况）
    try:
        # 如果是纯 IP 字符串
        ipaddress.ip_address(parsed.hostname)
        if _is_blocked_ip(parsed.hostname):
            return False, f"目标 IP {parsed.hostname} 在内网黑名单中"
    except ValueError:
        # 不是 IP 而是域名
        pass

    # 4) DNS 解析后检查所有返回 IP（防 DNS rebinding）
    if resolve_dns:
        try:
            infos = socket.getaddrinfo(parsed.hostname, None)
        except socket.gaierror as e:
            return False, f"DNS 解析失败: {e}"
        seen_ips: set[str] = set()
        for family, _type, _proto, _canon, sockaddr in infos:
            ip_str = sockaddr[0]
            if ip_str in seen_ips:
                continue
            seen_ips.add(ip_str)
            if _is_blocked_ip(ip_str):
                return False, f"DNS 解析到内网 IP: {ip_str}"

    return True, "ok"


def safe_fetch(
    url: str,
    *,
    allowed_domains: Optional[set[str]] = None,
    timeout: float = 5.0,
    max_bytes: int = 5 * 1024 * 1024,
) -> tuple[bool, str]:
    """带 SSRF 防护的 HTTP GET。

    Args:
        url: 目标 URL
        allowed_domains: 可选域名白名单
        timeout: 超时（秒）
        max_bytes: 最大下载字节数（防止大文件 OOM）

    Returns:
        (ok, content_or_reason): ok=True 时 content_or_reason 是 body，False 时是错误原因。
    """
    ok, reason = validate_url(url, allowed_domains=allowed_domains)
    if not ok:
        return False, reason

    try:
        import httpx

        with httpx.Client(timeout=timeout, follow_redirects=False) as client:
            resp = client.get(url)
            # 重定向到内网也拒绝
            if resp.status_code in (301, 302, 303, 307, 308):
                loc = resp.headers.get("location", "")
                if loc:
                    loc_ok, loc_reason = validate_url(loc, allowed_domains=allowed_domains)
                    if not loc_ok:
                        return False, f"重定向到不安全的 URL: {loc_reason}"
            content = resp.content[:max_bytes]
            return True, content.decode("utf-8", errors="replace")
    except Exception as e:
        return False, f"请求失败: {e}"
