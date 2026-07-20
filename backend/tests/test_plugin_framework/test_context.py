"""plugin_scope ContextVar 单元测试。"""
from __future__ import annotations

import asyncio

import pytest

from app.context import get_plugin_name
from app.plugins.core.context import plugin_scope


async def test_plugin_scope_sets_and_resets():
    assert get_plugin_name() == "-"
    with plugin_scope("auth"):
        assert get_plugin_name() == "auth"
        with plugin_scope("billing"):
            assert get_plugin_name() == "billing"
        assert get_plugin_name() == "auth"
    assert get_plugin_name() == "-"


async def test_plugin_scope_on_exception_resets():
    with pytest.raises(ValueError), plugin_scope("audit"):
        assert get_plugin_name() == "audit"
        raise ValueError("x")
    assert get_plugin_name() == "-"


async def test_concurrent_tasks_isolation():
    """不同 asyncio Task 的 ContextVar 互不影响。"""

    async def task(name: str, out: dict) -> None:
        with plugin_scope(name):
            await asyncio.sleep(0.01)
            out[name] = get_plugin_name()

    out: dict = {}
    await asyncio.gather(task("a", out), task("b", out))
    assert out == {"a": "a", "b": "b"}
    assert get_plugin_name() == "-"
