"""CostTracker 跨循环安全单元测试。

验证 CostTracker 使用 LazyLock 而非直接持有 asyncio.Lock，
从而避免在导入时/不同事件循环中创建锁导致的 RuntimeError。
"""

from __future__ import annotations

import asyncio

import pytest

from app.lazy_asyncio import LazyLock
from app.observability.cost_tracker import CostTracker, get_cost_tracker

pytestmark = pytest.mark.asyncio(loop_scope="function")


class TestLazyLockCrossLoop:
    """验证 LazyLock 在不同事件循环中可以安全使用。"""

    def test_lazy_lock_does_not_bind_loop_at_init(self) -> None:
        """LazyLock 初始化时不应绑定任何事件循环。"""
        lock = LazyLock()
        # _primitive 在首次使用时才创建，初始化时为 None
        assert lock._primitive is None, "LazyLock 初始化时不应创建内部 _primitive"

    def test_lazy_lock_works_across_loops(self) -> None:
        """同一个 LazyLock 实例可在不同事件循环中使用（核心修复验证）。"""
        lock = LazyLock()
        results = []

        async def use_lock():
            async with lock:
                results.append(id(asyncio.get_running_loop()))

        loop1 = asyncio.new_event_loop()
        try:
            loop1.run_until_complete(use_lock())
        finally:
            loop1.close()

        loop2 = asyncio.new_event_loop()
        try:
            loop2.run_until_complete(use_lock())
        finally:
            loop2.close()

        assert len(results) == 2
        assert results[0] != results[1], "两个循环应有不同的 id"


class TestCostTrackerLockSafety:
    """验证 CostTracker 锁机制的跨循环安全性。"""

    def test_cost_tracker_uses_lazy_lock(self) -> None:
        """CostTracker 必须使用 LazyLock（而非直接 asyncio.Lock()）。"""
        ct = CostTracker()
        assert isinstance(ct._lock, LazyLock), "CostTracker._lock 必须是 LazyLock 实例"

    async def test_record_llm_updates_totals(self) -> None:
        """record_llm 正确记录 token 和成本。"""
        ct = CostTracker()
        # 清空可能的已有记录
        ct._records.clear()
        await ct.record_llm(
            node="test_node",
            model="gpt-4o",
            input_tokens=100,
            output_tokens=50,
            latency_ms=100,
        )

        assert len(ct._records) == 1
        rec = ct._records[0]
        assert rec.input_tokens == 100
        assert rec.output_tokens == 50
        assert rec.total_tokens == 150
        assert rec.cost_usd > 0

    async def test_record_tool_adds_record(self) -> None:
        """record_tool 正确记录工具调用。"""
        ct = CostTracker()
        ct._records.clear()
        await ct.record_tool(
            node="test_node",
            tool_name="web_search",
            latency_ms=500,
        )

        assert len(ct._records) == 1
        assert ct._records[0].tool_name == "web_search"


class TestCostTrackerConcurrentAccess:
    """并发访问测试。"""

    async def test_concurrent_record_llm(self) -> None:
        """并发 record_llm 不丢失记录。"""
        ct = CostTracker()
        ct._records.clear()

        async def worker(n: int) -> None:
            for _ in range(n):
                await ct.record_llm(
                    node="test",
                    model="gpt-4o",
                    input_tokens=10,
                    output_tokens=5,
                    latency_ms=1,
                )

        await asyncio.gather(*[worker(50) for _ in range(10)])

        assert len(ct._records) == 500


class TestCostTrackerSingleton:
    """全局单例测试。"""

    def test_get_cost_tracker_returns_same_instance(self) -> None:
        """get_cost_tracker() 返回全局单例。"""
        ct1 = get_cost_tracker()
        ct2 = get_cost_tracker()
        assert ct1 is ct2
