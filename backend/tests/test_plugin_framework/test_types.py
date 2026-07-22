"""插件核心类型单元测试。"""

from __future__ import annotations

from app.plugins.core.types import (
    Fallback,
    LLMFallback,
    LLMOverride,
    Next,
    Override,
    PluginHealth,
    PluginState,
    PluginTier,
)


def test_plugin_tier_values():
    assert PluginTier.CORE.value == "core"
    assert PluginTier.CROSSCUTTING.value == "crosscutting"
    assert PluginTier.OPTIONAL.value == "optional"


def test_plugin_state_values():
    assert PluginState.READY.value == "ready"
    assert PluginState.DISABLED.value == "disabled"
    assert PluginState.FAILED.value == "failed"


def test_plugin_health_defaults():
    h = PluginHealth(healthy=True)
    assert h.healthy is True
    assert h.message == ""
    assert h.last_check is None
    assert h.details == {}


def test_override_next_fallback():
    o = Override(value=42)
    assert o.value == 42

    n = Next()
    assert n is not None

    fb = Fallback(reason="denied", code="X", status_code=403)
    assert fb.reason == "denied"
    assert fb.status_code == 403


def test_llm_override_fallback():
    lo = LLMOverride(model="gpt-4")
    assert lo.model == "gpt-4"
    assert lo.api_key is None

    lf = LLMFallback(reason="key exhausted")
    assert lf.reason == "key exhausted"
