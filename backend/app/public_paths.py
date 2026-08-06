"""认证公开路径常量（零依赖，避免循环导入）。

集中管理免认证路径，防止在多个 middleware 文件中重复定义导致遗漏。
app/middleware.py 和 app/plugins/builtin/auth/middleware.py 都应从此处导入。
"""

from __future__ import annotations

# 免认证路径（精确匹配 + 子路径前缀匹配）
# 新增公开路径时只需要修改此处
PUBLIC_PATHS: frozenset[str] = frozenset(
    {
        "/health",
        "/healthz",
        "/metrics",
        "/docs",
        "/redoc",
        "/openapi.json",
        "/debug/auth-info",
        "/auth/login",
        "/auth/refresh",
        "/auth/csrf-token",
        "/setup",
        "/setup/status",
        "/api/captcha",
    }
)

# WebSocket 路径（query 参数传 token，跳过 header 认证）
WS_PATHS: frozenset[str] = frozenset({"/ws"})


def is_public_path(normalized_path: str) -> bool:
    """判断规范化后的路径是否为公开路径。

    支持精确匹配（/health）和子路径前缀匹配（/docs/swagger 也公开）。
    """
    for p in PUBLIC_PATHS:
        if normalized_path == p:
            return True
        if normalized_path.startswith(p + "/"):
            return True
    return False
