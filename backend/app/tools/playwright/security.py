# SSRF 防护 + URL 安全校验
#
# [P1 修复] 统一到 app.network_security.validate_url 单一可信来源：
# - 数字型 IP 变体归一化拦截（http://2130706433/ → 127.0.0.1）
# - DNS 解析校验（异步入口，防 DNS rebinding 初始检查）
# - 黑名单主机名（localhost / 云元数据端点）+ userinfo 绕过检测
# 本文件保留旧函数签名以兼容既有调用与测试，不再维护独立校验逻辑。
from __future__ import annotations

from app.network_security import validate_url, validate_url_async


def _is_safe_url(url: str) -> tuple[bool, str]:
    """校验 URL 安全性（同步静态检查，不做 DNS 解析）。

    检查项：scheme 白名单（仅 http/https）、私网/保留 IP（含数字型
    变体）、黑名单主机名、userinfo 绕过。
    异步上下文（如页面抓取前校验）请用 _is_safe_url_async()，
    它额外做 DNS 解析校验（防 DNS rebinding 初始检查）。
    """
    return validate_url(url, resolve_dns=False)


async def _is_safe_url_async(url: str) -> tuple[bool, str]:
    """校验 URL 安全性（含 DNS 解析校验，防 DNS rebinding 初始检查）。

    DNS 解析在线程池中执行，不阻塞事件循环。
    """
    return await validate_url_async(url, resolve_dns=True)
