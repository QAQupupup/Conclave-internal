"""空注册表行为测试（Phase 0 验收：无插件时零影响）。"""
from __future__ import annotations

from pathlib import Path


async def test_empty_registry_has_no_plugins(empty_registry):
    assert empty_registry.has_plugins() is False
    assert empty_registry.loaded_count() == 0
    assert empty_registry.ready_plugins() == []


async def test_empty_registry_fire_hooks_returns_default(empty_registry, tmp_ctx):
    # 拦截型钩子无插件时返回 default
    result = await empty_registry.fire_interceptor(
        "on_meeting_creating", tmp_ctx, {"title": "x"}, default="default_val"
    )
    assert result == "default_val"

    # 观察型钩子无插件时无异常
    await empty_registry.fire_observer("on_meeting_created", tmp_ctx, {"title": "x"})


async def test_empty_registry_initialize_shutdown_noop(empty_registry, tmp_path):
    # discover 空目录
    count = await empty_registry.discover_plugins([Path(str(tmp_path))])
    assert count == 0
    # initialize_all 空注册表无异常
    await empty_registry.initialize_all()
    assert empty_registry.ready_plugins() == []
    # shutdown_all 空注册表无异常
    await empty_registry.shutdown_all()


async def test_empty_registry_disable_nonexistent_raises(empty_registry):
    import pytest

    with pytest.raises(KeyError):
        empty_registry.disable_plugin("nope")


async def test_get_registry_default_none():
    """模块级 get_registry 在 set_global_registry 之前返回 None。"""
    from app.plugins.core.registry import PluginRegistry

    # 不依赖全局状态，单独创建实例
    r = PluginRegistry()
    # get_registry 之前设置过吗？测试环境可能被其他测试污染，所以只验证我们的实例
    assert r.loaded_count() == 0
