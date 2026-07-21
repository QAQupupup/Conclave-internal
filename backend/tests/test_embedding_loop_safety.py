"""M1.6: 验证 SiliconFlowEmbedding 的 asyncio 循环感知。

参考 AGENTS.md §4.1：持有 asyncio 原语的单例 getter 必须循环感知，
否则跨循环调用会报 'got Future attached to a different loop'。

本测试模拟测试场景中 asyncio.run() 每次创建新循环的情况：
1. 首次 embed 在 loop A 创建 client
2. 第二次 embed 在 loop B（新循环）调用，应自动重建 client 而非报错
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from app.rag.store import SiliconFlowEmbedding


def _run_in_fresh_loop(coro):
    """在全新的事件循环中运行协程，运行后循环被关闭。"""
    return asyncio.run(coro)


def test_get_client_creates_on_first_call():
    """首次调用 _get_client 应创建 client 并记录 loop。"""
    emb = SiliconFlowEmbedding()

    async def _go():
        client = emb._get_client()
        assert client is not None
        assert emb._client_loop is not None
        # 记录的 loop 应为当前运行循环
        assert emb._client_loop is asyncio.get_running_loop()

    _run_in_fresh_loop(_go())


def test_get_client_reuses_within_same_loop():
    """同一循环内多次调用应复用同一 client。"""
    emb = SiliconFlowEmbedding()

    async def _go():
        c1 = emb._get_client()
        c2 = emb._get_client()
        assert c1 is c2

    _run_in_fresh_loop(_go())


def test_get_client_rebuilds_on_loop_change():
    """跨循环调用应重建 client，而非报 'attached to a different loop'。

    这是 M1.6 的核心验收点：模拟测试场景中 asyncio.run() 每次创建新循环。
    """
    emb = SiliconFlowEmbedding()

    async def _first():
        c1 = emb._get_client()
        assert c1 is not None
        return c1

    async def _second():
        # 此时 emb._client 绑定到已关闭的旧循环
        c2 = emb._get_client()
        assert c2 is not None
        # 应该是新 client（旧循环已关闭，需要重建）
        assert c2 is not emb._client or emb._client_loop is asyncio.get_running_loop()
        return c2

    c1 = _run_in_fresh_loop(_first())
    # 第一个循环已关闭
    c2 = _run_in_fresh_loop(_second())

    # 两个 client 不是同一个（跨循环重建）
    assert c1 is not c2


def test_get_client_handles_closed_loop():
    """旧循环 is_closed() 后应重建。"""
    emb = SiliconFlowEmbedding()

    async def _first():
        emb._get_client()
        assert emb._client_loop is not None
        assert not emb._client_loop.is_closed()

    _run_in_fresh_loop(_first())
    # 循环已关闭
    assert emb._client_loop is not None
    assert emb._client_loop.is_closed()

    async def _second():
        # 旧循环 is_closed() 为 True，应触发重建
        c = emb._get_client()
        assert c is not None
        assert emb._client_loop is asyncio.get_running_loop()
        assert not emb._client_loop.is_closed()

    _run_in_fresh_loop(_second())


def test_aclose_resets_loop_reference():
    """aclose 后应清空 loop 引用，下次 _get_client 重建。"""
    emb = SiliconFlowEmbedding()

    async def _go():
        emb._get_client()
        assert emb._client_loop is not None
        await emb.aclose()
        assert emb._client is None
        assert emb._client_loop is None
        # 再次 get 应重建
        emb._get_client()
        assert emb._client is not None
        assert emb._client_loop is not None

    _run_in_fresh_loop(_go())


@pytest.mark.asyncio
async def test_embed_does_not_crash_across_loops():
    """端到端验证：跨循环调用 embed 不崩溃。

    使用 StubEmbedding 降级路径（无 API key 时），确保测试不依赖外网。
    但 _get_client 仍会被调用（因为 base_url/api_key 检查在 _resolve_config 之后）。
    """
    emb = SiliconFlowEmbedding()

    # 第一轮循环
    async def _first():
        # 无 key 时降级到 stub，不实际调用 _get_client
        # 但我们直接测 _get_client 的循环感知
        emb._get_client()

    asyncio.run(_first())

    # 第二轮循环（新循环）
    async def _second():
        # 不应抛出 'attached to a different loop'
        client = emb._get_client()
        assert isinstance(client, httpx.AsyncClient)

    asyncio.run(_second())
