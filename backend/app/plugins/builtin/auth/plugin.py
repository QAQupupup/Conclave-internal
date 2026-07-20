"""Auth CORE 插件主类。

职责：
- on_startup：初始化用户表、JWT secret、加载用户缓存、setup 流程
- register_routers：挂载 /auth/* 和 /setup/*
- register_middlewares：挂载认证+CSRF 中间件
- health_check：检查 DB 连通性
"""
from __future__ import annotations

import logging
from typing import ClassVar

from fastapi import FastAPI

from app.plugins.builtin.auth import middleware as auth_mw
from app.plugins.builtin.auth import router as auth_router_mod
from app.plugins.builtin.auth import setup as setup_mod
from app.plugins.core.hooks import LifecycleMixin, MiddlewareMixin, RouterMixin
from app.plugins.core.types import PluginContext, PluginHealth, PluginTier

logger = logging.getLogger(__name__)


class AuthPlugin(LifecycleMixin, RouterMixin, MiddlewareMixin):
    """认证 CORE 插件。"""

    name = "auth"
    version = "1.0.0"
    tier = PluginTier.CORE
    dependencies: ClassVar[list[str]] = []
    priority = 0  # 最先加载

    def __init__(self) -> None:
        self._users_count: int = 0

    async def on_startup(self, ctx: PluginContext) -> None:
        """初始化认证系统：建表+默认管理员，然后初始化多租户。"""
        from app.auth import _load_users_from_db, _users_cache
        from app.auth import init_auth as _init_auth
        from app.tenants import (
            create_default_tenant_for_existing_users,
            ensure_business_tables_tenant_id,
            ensure_tenants_table,
        )

        # 1. 先建 users 表（_init_users_table 中 CREATE TABLE 已包含 tenant_id 列）
        #    以及 JWT secret、加载用户、创建默认管理员
        await _init_auth()

        # 2. 建 tenants 表 + users.tenant_id 外键约束（users 表已存在）
        await ensure_tenants_table()

        # 3. 创建默认租户并将所有无 tenant_id 的用户关联到默认租户
        await create_default_tenant_for_existing_users()

        # 4. 为核心业务表添加 tenant_id 列并回填默认租户
        await ensure_business_tables_tenant_id()

        # 5. 重新加载用户缓存（确保 tenant_id 字段已填充）
        await _load_users_from_db()
        self._users_count = len(_users_cache)

        # 6. Setup token 逻辑
        from app.plugins.builtin.auth.setup import (
            generate_setup_token,
            mark_admin_created,
        )

        if self._users_count > 0:
            mark_admin_created()
        else:
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
            from sqlalchemy import text

            from app.db.engine import async_session_factory

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
