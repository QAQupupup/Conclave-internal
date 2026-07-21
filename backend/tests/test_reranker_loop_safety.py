"""验证 SiliconFlowReranker 的 asyncio 循环感知。

参照 test_embedding_loop_safety.py，验证 reranker._get_client() 在跨循环
场景下自动重建 client，而非报 'got Future attached to a different loop'。

背景：AGENTS.md §4.1 要求持有 asyncio 原语的单例 getter 必须循环感知。
SiliconFlowEmbedding 已修复，本测试验证 SiliconFlowReranker 同样修复。
"""

from __future__ import annotations

import asyncio

import httpx

from app.rag.store import SiliconFlowReranker


def _run_in_fresh_loop(coro):
    """在全新的事件循环中运行协程，运行后循环被关闭。"""
    return asyncio.run(coro)


def test_reranker_get_client_creates_on_first_call():
    """首次调用 _get_client 应创建 client 并记录 loop。"""
    rr = SiliconFlowReranker()

    async def _go():
        client = rr._get_client()
        assert client is not None
        assert rr._client_loop is not None
        assert rr._client_loop is asyncio.get_running_loop()

    _run_in_fresh_loop(_go())


def test_reranker_get_client_reuses_within_same_loop():
    """同一循环内多次调用应复用同一 client。"""
    rr = SiliconFlowReranker()

    async def _go():
        c1 = rr._get_client()
        c2 = rr._get_client()
        assert c1 is c2

    _run_in_fresh_loop(_go())


def test_reranker_get_client_rebuilds_on_loop_change():
    """跨循环调用应重建 client，而非报 'attached to a different loop'。"""
    rr = SiliconFlowReranker()

    async def _first():
        c1 = rr._get_client()
        assert c1 is not None
        return c1

    async def _second():
        c2 = rr._get_client()
        assert c2 is not None
        return c2

    c1 = _run_in_fresh_loop(_first())
    c2 = _run_in_fresh_loop(_second())
    assert c1 is not c2


def test_reranker_get_client_handles_closed_loop():
    """旧循环 is_closed() 后应重建。"""
    rr = SiliconFlowReranker()

    async def _first():
        rr._get_client()
        assert rr._client_loop is not None
        assert not rr._client_loop.is_closed()

    _run_in_fresh_loop(_first())
    assert rr._client_loop is not None
    assert rr._client_loop.is_closed()

    async def _second():
        c = rr._get_client()
        assert c is not None
        assert rr._client_loop is asyncio.get_running_loop()
        assert not rr._client_loop.is_closed()

    _run_in_fresh_loop(_second())


def test_reranker_does_not_crash_across_loops():
    """端到端验证：跨循环调用 reranker._get_client 不崩溃。"""
    rr = SiliconFlowReranker()

    async def _first():
        rr._get_client()

    asyncio.run(_first())

    async def _second():
        client = rr._get_client()
        assert isinstance(client, httpx.AsyncClient)

    asyncio.run(_second())
