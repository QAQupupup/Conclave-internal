"""Conclave 插件系统。

Phase 0: 提供插件框架地基（PluginRegistry、Mixin 协议、钩子调度、EventBus）。
Phase 1a/1b: 填充内置插件（auth/billing/audit/team）。

使用方式：
    from app.plugins import get_registry
    registry = get_registry()
"""
from __future__ import annotations

from app.plugins.core.registry import PluginRegistry, get_registry, set_global_registry

__all__ = [
    "PluginRegistry",
    "get_registry",
    "set_global_registry",
]
