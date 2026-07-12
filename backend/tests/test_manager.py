"""测试 MeetingManager 的调度与治理入口。

使用 monkeypatch 替换 compute 层，避免真实 LLM 调用。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from app.agents import compute as compute_mod
from app.agents.compute import ThinkRequest, ThinkResponse
from app.agents.task_baseline import SOFTWARE_DEV_BASELINE
from app.orchestrator.manager import MeetingManager


@dataclass
class FakeState:
    meeting_id: str = "mtg-test"
    topic: str = "开发一个 FastAPI + React 的 Wiki 系统"
    charter: dict[str, Any] = field(default_factory=dict)
    conclusion_chain: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    messages: list[dict[str, Any]] = field(default_factory=list)


class FakeCompute:
    def __init__(self, response_payload: dict[str, Any]):
        self.response_payload = response_payload

    async def think(self, req: ThinkRequest) -> ThinkResponse:
        return ThinkResponse(success=True, result=self.response_payload, latency_ms=10)

    async def think_batch(self, requests: list[ThinkRequest]) -> list[ThinkResponse]:
        return [await self.think(req) for req in requests]


@pytest.fixture(autouse=True)
def reset_compute():
    """每个测试前重置全局 compute 实例"""
    compute_mod.reset_compute()
    yield
    compute_mod.reset_compute()


@pytest.mark.asyncio
async def test_run_stage_with_stub_compute(monkeypatch):
    """Manager 应能通过 stub compute 运行一个阶段而不调用真实 LLM"""
    monkeypatch.setattr(compute_mod, "_compute", FakeCompute({"claims": []}))

    manager = MeetingManager(max_recursion_depth=0)
    state = FakeState(topic="开发一个 FastAPI + React 的 Wiki 系统")
    results = await manager.run_stage(state, "intra_team", baseline=SOFTWARE_DEV_BASELINE)

    # 软件基线定义了 4 个角色，应产生 4 个结果
    assert len(results) == 4
    for role in ["product_architect", "engineer", "qa_engineer", "ui_designer"]:
        key = f"intra_team:{role}"
        assert key in results
        assert results[key]["success"] is True


@pytest.mark.asyncio
async def test_manager_selects_baseline():
    manager = MeetingManager()
    baseline = manager.select_baseline("帮我分析一只股票", "")
    assert baseline.domain == "stock_analysis"
    baseline2 = manager.select_baseline("开发系统", "")
    assert baseline2.domain == "software_dev"
