"""PluginRegistry 拓扑排序测试。"""
from __future__ import annotations

import pytest

from app.plugins.core.exceptions import PluginDependencyError
from app.plugins.core.types import PluginTier


async def test_register_and_query(empty_registry, make_mock_plugin):
    p = make_mock_plugin(name="a")
    empty_registry.register(p)
    assert empty_registry.is_registered("a")
    assert empty_registry.get_plugin("a") is p
    assert empty_registry.loaded_count() == 1


def test_register_duplicate_raises(empty_registry, make_mock_plugin):
    empty_registry.register(make_mock_plugin(name="a"))
    with pytest.raises(PluginDependencyError):
        empty_registry.register(make_mock_plugin(name="a"))


async def test_topo_sort_linear_dependency(empty_registry, make_mock_plugin, tmp_ctx):
    """b 依赖 a，c 依赖 b，启动顺序 a->b->c。"""
    a = make_mock_plugin(name="a")
    b = make_mock_plugin(name="b", dependencies=["a"])
    c = make_mock_plugin(name="c", dependencies=["b"])
    empty_registry.register(c)
    empty_registry.register(a)
    empty_registry.register(b)
    await empty_registry.resolve_and_load(tmp_ctx)
    # recorder 记录 on_startup 顺序
    startups = a.recorder.names_for("on_startup")
    assert startups == ["a", "b", "c"]


async def test_topo_sort_hard_dependency_missing_raises(empty_registry, make_mock_plugin, tmp_ctx):
    a = make_mock_plugin(name="a", dependencies=["nonexistent"])
    empty_registry.register(a)
    with pytest.raises(PluginDependencyError, match="硬依赖缺失"):
        await empty_registry.resolve_and_load(tmp_ctx)


async def test_topo_sort_soft_dependency_missing_warns(empty_registry, make_mock_plugin, tmp_ctx, caplog):
    """软依赖缺失仅 WARNING，不阻断。"""
    import logging

    caplog.set_level(logging.WARNING)
    a = make_mock_plugin(name="a", dependencies=["missing?"])
    empty_registry.register(a)
    await empty_registry.resolve_and_load(tmp_ctx)
    assert empty_registry.ready_plugins() == ["a"]
    assert any("软依赖缺失" in rec.message for rec in caplog.records)


async def test_circular_dependency_raises(empty_registry, make_mock_plugin, tmp_ctx):
    a = make_mock_plugin(name="a", dependencies=["b"])
    b = make_mock_plugin(name="b", dependencies=["a"])
    empty_registry.register(a)
    empty_registry.register(b)
    with pytest.raises(PluginDependencyError, match="循环依赖"):
        await empty_registry.resolve_and_load(tmp_ctx)


async def test_tier_ordering(empty_registry, make_mock_plugin, tmp_ctx):
    """CORE 先于 CROSSCUTTING 先于 OPTIONAL（无依赖时）。"""
    opt = make_mock_plugin(name="opt", tier=PluginTier.OPTIONAL, priority=1)
    core = make_mock_plugin(name="core", tier=PluginTier.CORE, priority=100)
    cross = make_mock_plugin(name="cross", tier=PluginTier.CROSSCUTTING, priority=50)
    for p in [opt, cross, core]:
        empty_registry.register(p)
    await empty_registry.resolve_and_load(tmp_ctx)
    startups = opt.recorder.names_for("on_startup")
    assert startups.index("core") < startups.index("cross") < startups.index("opt")


async def test_priority_within_same_tier(empty_registry, make_mock_plugin, tmp_ctx):
    """同 tier 内 priority 小的先启动。"""
    a = make_mock_plugin(name="a", priority=200)
    b = make_mock_plugin(name="b", priority=10)
    c = make_mock_plugin(name="c", priority=50)
    for p in [a, b, c]:
        empty_registry.register(p)
    await empty_registry.resolve_and_load(tmp_ctx)
    startups = a.recorder.names_for("on_startup")
    assert startups == ["b", "c", "a"]


async def test_validate_plugin_missing_name():
    from app.plugins.core.registry import PluginRegistry

    class Bad:
        tier = PluginTier.OPTIONAL
        version = "1"

    r = PluginRegistry()
    with pytest.raises(PluginDependencyError):
        r.register(Bad())
