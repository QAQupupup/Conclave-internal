"""插件系统上下文工具：便捷 ContextVar 访问与 plugin_name 上下文管理器。"""
from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from contextvars import Token

from app.context import (
    get_plugin_name,
    reset_plugin_name,
    set_plugin_name,
)

__all__ = [
    "get_plugin_name",
    "plugin_scope",
    "reset_plugin_name",
    "set_plugin_name",
]


@contextmanager
def plugin_scope(name: str) -> Generator[Token[str], None, None]:
    """在插件钩子调用期间设置 plugin_name ContextVar。

    用法::

        with plugin_scope("auth"):
            result = await plugin.on_startup(ctx)
    """
    token = set_plugin_name(name)
    try:
        yield token
    finally:
        reset_plugin_name(token)
