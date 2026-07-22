"""PluginRegistry 生命周期和热开关测试。"""

from __future__ import annotations

import pytest

from app.plugins.core.types import PluginHealth, PluginState, PluginTier


async def test_on_startup_called_in_order(empty_registry, make_mock_plugin, tmp_ctx, call_recorder):
    a = make_mock_plugin(name="a")
    b = make_mock_plugin(name="b", dependencies=["a"])
    empty_registry.register(a)
    empty_registry.register(b)
    await empty_registry.resolve_and_load(tmp_ctx)
    assert call_recorder.names_for("on_startup") == ["a", "b"]
    assert empty_registry.ready_plugins() == ["a", "b"]


async def test_on_shutdown_reverse_order(empty_registry, make_mock_plugin, tmp_ctx, call_recorder):
    a = make_mock_plugin(name="a")
    b = make_mock_plugin(name="b", dependencies=["a"])
    empty_registry.register(a)
    empty_registry.register(b)
    await empty_registry.resolve_and_load(tmp_ctx)
    call_recorder.reset()
    await empty_registry.shutdown_all(tmp_ctx)
    assert call_recorder.names_for("on_shutdown") == ["b", "a"]


async def test_core_plugin_startup_failure_raises(empty_registry, make_mock_plugin, tmp_ctx):
    p = make_mock_plugin(name="core", tier=PluginTier.CORE, startup_raise=RuntimeError("boom"))
    empty_registry.register(p)
    with pytest.raises(RuntimeError, match="boom"):
        await empty_registry.resolve_and_load(tmp_ctx)


async def test_crosscutting_startup_failure_degraded(empty_registry, make_mock_plugin, tmp_ctx):
    p = make_mock_plugin(name="cross", tier=PluginTier.CROSSCUTTING, startup_raise=RuntimeError("fail"))
    empty_registry.register(p)
    await empty_registry.resolve_and_load(tmp_ctx)  # 不抛
    entry = empty_registry._entries["cross"]
    assert entry.state == PluginState.DEGRADED
    assert entry.health.healthy is False


async def test_optional_startup_failure_disabled(empty_registry, make_mock_plugin, tmp_ctx):
    p = make_mock_plugin(name="opt", tier=PluginTier.OPTIONAL, startup_raise=RuntimeError("fail"))
    empty_registry.register(p)
    await empty_registry.resolve_and_load(tmp_ctx)
    entry = empty_registry._entries["opt"]
    assert entry.state == PluginState.DISABLED


async def test_disable_enable_plugin(empty_registry, make_mock_plugin, tmp_ctx):
    a = make_mock_plugin(name="a")
    empty_registry.register(a)
    await empty_registry.resolve_and_load(tmp_ctx)
    assert empty_registry.ready_plugins() == ["a"]

    empty_registry.disable_plugin("a")
    assert empty_registry.is_disabled("a")
    assert empty_registry._entries["a"].state == PluginState.DISABLED

    empty_registry.enable_plugin("a")
    assert not empty_registry.is_disabled("a")


async def test_core_plugin_cannot_be_disabled(empty_registry, make_mock_plugin, tmp_ctx):
    a = make_mock_plugin(name="a", tier=PluginTier.CORE)
    empty_registry.register(a)
    await empty_registry.resolve_and_load(tmp_ctx)
    empty_registry.disable_plugin("a")
    # CORE 不会被禁用
    assert not empty_registry.is_disabled("a")


async def test_shutdown_exception_isolated(empty_registry, make_mock_plugin, tmp_ctx, call_recorder):
    a = make_mock_plugin(name="a", shutdown_raise=RuntimeError("x"))
    b = make_mock_plugin(name="b")
    empty_registry.register(a)
    empty_registry.register(b)
    await empty_registry.resolve_and_load(tmp_ctx)
    call_recorder.reset()
    # 不抛异常，b 仍被关闭
    await empty_registry.shutdown_all(tmp_ctx)
    assert call_recorder.names_for("on_shutdown") == ["b", "a"]


async def test_initialize_all_convenience(empty_registry, make_mock_plugin, tmp_path):
    """initialize_all 无 app 时不注册路由/中间件，不报错。"""
    p = make_mock_plugin(name="a")
    empty_registry.register(p)
    await empty_registry.initialize_all()
    assert empty_registry.ready_plugins() == ["a"]
    await empty_registry.shutdown_all()


async def test_health_snapshot(empty_registry, make_mock_plugin, tmp_ctx):
    p = make_mock_plugin(name="a", health_result=PluginHealth(healthy=True, message="ok"))
    empty_registry.register(p)
    await empty_registry.resolve_and_load(tmp_ctx)
    snap = empty_registry.get_health_snapshot()
    assert "a" in snap
    assert snap["a"]["healthy"] is True
    assert snap["a"]["tier"] == "optional"
