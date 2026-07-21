"""Auth CORE 插件：JWT 认证 + HttpOnly Cookie + CSRF + Setup 流程。

Phase 1a 实现：
- 复用 app/auth.py 底层 JWT/密码哈希函数（不删除旧代码）
- 认证中间件：同时支持 Cookie（新）和 Authorization Bearer（旧），过渡期兼容
- CSRF double-submit cookie 防护
- /setup 首次部署管理员创建流程
- /auth/login、/auth/logout、/auth/me、/auth/refresh 路由
"""

from __future__ import annotations

from app.plugins.builtin.auth.plugin import AuthPlugin

__all__ = ["AuthPlugin"]
