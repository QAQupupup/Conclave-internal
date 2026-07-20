"""Auth CORE 插件主类。

职责：
- on_startup：初始化用户表、JWT secret、加载用户缓存、setup 流程
- register_routers：挂载 /auth/* 和 /setup/*
- register_middlewares：挂载认证+CSRF 中间件
- health_check：检查 DB 连通性
"""
from __future__ import annotations

import logging

from fastapi import FastAPI

from app.plugins.core.hooks import LifecycleMixin, MiddlewareMixin, RouterMixin
from app.plugins.core.types import PluginContext, PluginHealth, PluginTier

from app.plugins.builtin.auth import middleware as auth_mw
from app.plugins.builtin.auth import router as auth_router_mod
from app.plugins.builtin.auth import setup as setup_mod

logger = logging.getLogger(__name__)


class AuthPlugin(LifecycleMixin, RouterMixin, MiddlewareMixin):
    """认证 CORE 插件。"""

    name = "auth"
    version = "1.0.0"
    tier = PluginTier.CORE
    dependencies: list[str] = []
    priority = 0  # 最先加载

    def __init__(self) -> None:
        self._users_count: int = 0

    async def on_startup(self, ctx: PluginContext) -> None:
        """初始化认证系统：复用 app.auth.init_auth() 建表+默认管理员，然后处理 setup token。"""
        from app.auth import init_auth as _init_auth, _users_cache

        # 1. 建表 + 加载用户 + JWT secret + 默认管理员创建
        await _init_auth()
        self._users_count = len(_users_cache)

        # 2. Setup token 逻辑（仅当无任何用户时生成，正常情况 init_auth 已创建默认管理员）
        from app.plugins.builtin.auth.setup import (
            generate_setup_token,
            is_setup_needed,
            mark_admin_created,
        )

        if self._users_count > 0:
            mark_admin_created()
        else:
            # 极端情况：init_auth 未能创建默认管理员（如被禁用），生成 setup token
            token = generate_setup_token()
            logger.warning(
                "=" * 60 + "\n"
                "系统未检测到任何用户，请访问 /setup 端点创建管理员。\n"
                "Setup Token (24h 内有效，一次性使用): %s\n"
                "也可通过环境变量 CONCLAVE_SETUP_ADMIN_PASSWORD 设置密码后重启。\n"
                + "=" * 60,
                token,
            )

    async def on_shutdown(self, ctx: PluginContext) -> None:
        pass

    async def health_check(self) -> PluginHealth:
        try:
            from app.db.engine import async_session_factory
            from sqlalchemy import text

            async with async_session_factory() as s:
                await s.execute(text("SELECT 1"))
            return PluginHealth(healthy=True, message=f"users={self._users_count}")
        except Exception as e:
            return PluginHealth(healthy=False, message=str(e))

    def register_routers(self, app: FastAPI) -> None:
        app.include_router(auth_router_mod.router)
        app.include_router(setup_mod.router)

    def register_middlewares(self, app: FastAPI) -> None:
        auth_mw.setup_auth_middleware(app, self)
