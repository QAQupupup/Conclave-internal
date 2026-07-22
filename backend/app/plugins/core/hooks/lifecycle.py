"""生命周期、路由、中间件 Mixin 协议。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from fastapi import FastAPI

if TYPE_CHECKING:
    from app.plugins.core.types import PluginContext, PluginHealth


@runtime_checkable
class LifecycleMixin(Protocol):
    """插件生命周期钩子。CORE/CROSSCUTTING/OPTIONAL 均可实现。"""

    async def on_startup(self, ctx: PluginContext) -> None:
        """插件启动。CORE 抛异常阻止启动；CROSSCUTTING 抛异常标 DEGRADED；OPTIONAL 抛异常标 DISABLED。"""
        ...

    async def on_shutdown(self, ctx: PluginContext) -> None:
        """插件关闭。异常仅记录 WARNING，不阻止其他插件关闭。"""
        ...

    async def health_check(self) -> PluginHealth:
        """健康检查，返回 PluginHealth(healthy=bool, message=str)。"""
        ...


@runtime_checkable
class RouterMixin(Protocol):
    """插件提供 FastAPI 路由。"""

    def register_routers(self, app: FastAPI) -> None:
        """将插件路由挂载到 app（app.include_router(...)）。"""
        ...


@runtime_checkable
class MiddlewareMixin(Protocol):
    """插件提供 HTTP 中间件。"""

    def register_middlewares(self, app: FastAPI) -> None:
        """注册中间件到 app（app.middleware(...) 或 add_middleware）。"""
        ...
