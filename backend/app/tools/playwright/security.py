# SSRF 防护 + URL 安全校验
from __future__ import annotations

import ipaddress
from urllib.parse import urlparse

# P0-1: 完整 SSRF 校验（Claude 交叉评审指出 redirect-hop + DNS rebinding 风险）
_BLOCKED_SCHEMES = {"file", "data", "javascript", "vbscript", "about", "blob"}


def _is_safe_url(url: str) -> tuple[bool, str]:
    """校验 URL 安全性（初始 URL 检查）

    检查项：
    1. scheme 必须是 http/https（拒绝 file://、data: 等）
    2. 拒绝私网 IP / localhost / 元数据端点
    3. 检测 userinfo 绕过（http://allowed@evil.com）

    注意：此函数仅检查初始 URL，redirect-hop 验证在 goto 后用 response.url 再次调用。
    """
    try:
        parsed = urlparse(url)
    except Exception:
        return False, "URL 解析失败"

    if parsed.scheme not in ("http", "https"):
        return False, f"scheme '{parsed.scheme}' 不允许（仅 http/https）"

    if parsed.scheme in _BLOCKED_SCHEMES:
        return False, f"scheme '{parsed.scheme}' 被禁止"

    hostname = parsed.hostname or ""
    if not hostname:
        return False, "URL 缺少 hostname"

    # 私网 IP 拒绝
    try:
        ip = ipaddress.ip_address(hostname)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            return False, f"私网/保留地址 '{hostname}' 被拒绝"
    except ValueError:
        if hostname in ("localhost", "metadata.google.internal", "metadata"):
            return False, f"内网/元数据端点 '{hostname}' 被拒绝"

    # userinfo 绕过检测
    if "@" in (parsed.netloc or ""):
        userinfo_part = parsed.netloc.rsplit("@", 1)[0]
        if userinfo_part:
            return False, "URL 包含 userinfo 部分，疑似绕过攻击"

    return True, "ok"
