"""PluginRegistry 钩子调度测试（拦截型 + 观察型）。"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.plugins.core.types import (
    Fallback,
    Next,
    Override,
    PluginTier,
)


async def test_interceptor_override_stops_chain(empty_registry, make_interceptor, tmp_ctx, call_recorder):
    """Override 终止拦截链，后面的插件不执行。"""
    first = make_interceptor(name="first", tier=PluginTier.CORE, hook_result=Override(value="CUSTOM"))
    second = make_interceptor(name="second", tier=PluginTier.CORE, hook_result=Next())
    empty_registry.register(first)
    empty_registry.register(second)
    await empty_registry.resolve_and_load(tmp_ctx)
    call_recorder.reset()
    result = await empty_registry.fire_interceptor(
        "on_meeting_creating", tmp_ctx, {"title": "x"}, default="DEFAULT"
    )
    assert result == "CUSTOM"
    # second 不应被调用
    assert call_recorder.names_for("on_meeting_creating") == ["first"]


async def test_interceptor_default_when_all_next(empty_registry, make_interceptor, tmp_ctx):
    """所有插件返回 Next/None 时返回 default。"""
    a = make_interceptor(name="a", hook_result=Next())
    b = make_interceptor(name="b", hook_result=None)
    empty_registry.register(a)
    empty_registry.register(b)
    await empty_registry.resolve_and_load(tmp_ctx)
    result = await empty_registry.fire_interceptor(
        "on_meeting_creating", tmp_ctx, {}, default="DEF"
    )
    assert result == "DEF"


async def test_interceptor_fallback_raises_http(empty_registry, make_interceptor, tmp_ctx):
    p = make_interceptor(name="p", hook_result=Fallback(reason="no", status_code=403))
    empty_registry.register(p)
    await empty_registry.resolve_and_load(tmp_ctx)
    with pytest.raises(HTTPException) as ei:
        await empty_registry.fire_interceptor("on_meeting_creating", tmp_ctx, {})
    assert ei.value.status_code == 403


async def test_interceptor_raise_fallback_class(empty_registry, make_interceptor, tmp_ctx):
    """插件通过 raise Fallback(...) 方式也应触发拦截。"""
    p = make_interceptor(name="p", hook_raise=Fallback(reason="nope", status_code=403))
    empty_registry.register(p)
    await empty_registry.resolve_and_load(tmp_ctx)
    with pytest.raises(HTTPException) as ei:
        await empty_registry.fire_interceptor("on_meeting_creating", tmp_ctx, {})
    assert ei.value.status_code == 403


async def test_interceptor_non_standard_return_is_override(empty_registry, make_interceptor, tmp_ctx):
    """返回非 Override/Next/Fallback/None 的值视为 Override。"""
    p = make_interceptor(name="p", hook_result="raw_value")
    empty_registry.register(p)
    await empty_registry.resolve_and_load(tmp_ctx)
    result = await empty_registry.fire_interceptor("on_meeting_creating", tmp_ctx, {})
    assert result == "raw_value"


async def test_interceptor_timeout_skipped(empty_registry, make_interceptor, tmp_ctx):
    """钩子超时（hook_timeout=50ms，sleep 1s）视为弃权。"""
    slow = make_interceptor(name="slow", hook_sleep=1.0)
    fast = make_interceptor(name="fast", priority=10, hook_result=Override(value="FAST"))
    empty_registry.register(slow)
    empty_registry.register(fast)
    await empty_registry.resolve_and_load(tmp_ctx)
    result = await empty_registry.fire_interceptor("on_meeting_creating", tmp_ctx, {})
    assert result == "FAST"


async def test_interceptor_optional_exception_isolated(empty_registry, make_interceptor, tmp_ctx):
    """OPTIONAL 插件钩子异常不阻断链。"""
    bad = make_interceptor(name="bad", hook_raise=RuntimeError("x"))
    good = make_interceptor(name="good", hook_result=Override(value="OK"))
    empty_registry.register(bad)
    empty_registry.register(good)
    await empty_registry.resolve_and_load(tmp_ctx)
    result = await empty_registry.fire_interceptor("on_meeting_creating", tmp_ctx, {})
    assert result == "OK"


async def test_interceptor_core_exception_raises(empty_registry, make_interceptor, tmp_ctx):
    """CORE 插件钩子异常直接上抛。"""
    bad = make_interceptor(name="bad", tier=PluginTier.CORE, hook_raise=RuntimeError("core boom"))
    empty_registry.register(bad)
    await empty_registry.resolve_and_load(tmp_ctx)
    with pytest.raises(RuntimeError, match="core boom"):
        await empty_registry.fire_interceptor("on_meeting_creating", tmp_ctx, {})


async def test_observer_all_called(empty_registry, make_observer, tmp_ctx, call_recorder):
    a = make_observer(name="a")
    b = make_observer(name="b")
    empty_registry.register(a)
    empty_registry.register(b)
    await empty_registry.resolve_and_load(tmp_ctx)
    call_recorder.reset()
    payload = {"x": 1}
    await empty_registry.fire_observer("on_meeting_created", tmp_ctx, payload)
    names = call_recorder.names_for("on_meeting_created")
    assert set(names) == {"a", "b"}
    assert b.last_payload == payload


async def test_observer_exception_isolated(empty_registry, make_observer, tmp_ctx, call_recorder):
    bad = make_observer(name="bad", hook_raise=RuntimeError("x"))
    good = make_observer(name="good")
    empty_registry.register(bad)
    empty_registry.register(good)
    await empty_registry.resolve_and_load(tmp_ctx)
    call_recorder.reset()
    # 不抛
    await empty_registry.fire_observer("on_meeting_created", tmp_ctx, {})
    assert "good" in call_recorder.names_for("on_meeting_created")


async def test_observer_timeout_skipped(empty_registry, make_observer, tmp_ctx, call_recorder):
    slow = make_observer(name="slow", hook_sleep=1.0)
    fast = make_observer(name="fast")
    empty_registry.register(slow)
    empty_registry.register(fast)
    await empty_registry.resolve_and_load(tmp_ctx)
    call_recorder.reset()
    await empty_registry.fire_observer("on_meeting_created", tmp_ctx, {})
    # fast 被调用，slow 超时但不抛
    assert "fast" in call_recorder.names_for("on_meeting_created")


async def test_observer_concurrent(empty_registry, make_observer, tmp_ctx, call_recorder):
    a = make_observer(name="a", hook_sleep=0.01)
    b = make_observer(name="b", hook_sleep=0.01)
    empty_registry.register(a)
    empty_registry.register(b)
    await empty_registry.resolve_and_load(tmp_ctx)
    call_recorder.reset()
    await empty_registry.fire_observer("on_meeting_created", tmp_ctx, {}, concurrent=True)
    assert set(call_recorder.names_for("on_meeting_created")) == {"a", "b"}


async def test_disabled_plugin_skipped_in_hooks(empty_registry, make_interceptor, tmp_ctx):
    a = make_interceptor(name="a", hook_result=Override(value="A"))
    b = make_interceptor(name="b", hook_result=Override(value="B"))
    empty_registry.register(a)
    empty_registry.register(b)
    await empty_registry.resolve_and_load(tmp_ctx)
    empty_registry.disable_plugin("b")
    result = await empty_registry.fire_interceptor("on_meeting_creating", tmp_ctx, {})
    assert result == "A"
