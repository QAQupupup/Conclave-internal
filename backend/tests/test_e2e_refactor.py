"""基于历史数据的端到端回归测试。

目标：
- 验证 Manager + Scheduler + ContextManager + AgentRuntime 能协同工作
- 不调用真实 LLM（stub compute）
- 使用历史会议议题作为输入，验证输出结构
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from app.agents import compute as compute_mod
from app.agents.compute import ThinkRequest, ThinkResponse
from app.orchestrator.manager import MeetingManager


@dataclass
class FakeState:
    meeting_id: str = "mtg-e2e"
    topic: str = ""
    charter: dict[str, Any] = field(default_factory=dict)
    conclusion_chain: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    messages: list[dict[str, Any]] = field(default_factory=list)


class WikiStubCompute:
    """模拟一个完整 Wiki 会议的 LLM 响应"""

    async def think(self, req: ThinkRequest) -> ThinkResponse:
        stage = req.stage
        if stage == "clarify":
            return ThinkResponse(success=True, result={
                "clarified_topic": req.prompt[-80:],
                "key_questions": ["Q1", "Q2"],
                "team_config": [{"role": "product_architect"}, {"role": "engineer"}],
                "complexity": "full",
            })
        if stage == "intra_team":
            return ThinkResponse(success=True, result={
                "claims": [{"claim": "需要 Markdown 编辑", "type": "constraint"}],
            })
        if stage == "produce":
            return ThinkResponse(success=True, result={
                "prd": {"title": "Wiki 系统", "goal": "个人知识管理"},
                "openapi": "openapi: 3.0.0",
            })
        return ThinkResponse(success=True, result={})

    async def think_batch(self, requests: list[ThinkRequest]) -> list[ThinkResponse]:
        return [await self.think(req) for req in requests]


@pytest.fixture(autouse=True)
def reset_compute():
    compute_mod.reset_compute()
    yield
    compute_mod.reset_compute()


@pytest.mark.asyncio
async def test_e2e_wiki_meeting_runs_without_real_llm(monkeypatch, sample_wiki_topic):
    monkeypatch.setattr(compute_mod, "_compute", WikiStubCompute())

    manager = MeetingManager(max_recursion_depth=0)
    state = FakeState(topic=sample_wiki_topic)

    # clarify 阶段
    clarify_results = await manager.run_stage(state, "clarify")
    assert any("clarified_topic" in r.get("payload", {}) for r in clarify_results.values())

    # intra_team 阶段
    intra_results = await manager.run_stage(state, "intra_team")
    assert any("claims" in r.get("payload", {}) for r in intra_results.values())

    # produce 阶段
    produce_results = await manager.run_stage(state, "produce")
    assert any("prd" in r.get("payload", {}) for r in produce_results.values())


@pytest.mark.asyncio
async def test_e2e_stock_analysis_selects_right_baseline(sample_stock_topic):
    manager = MeetingManager()
    baseline = manager.select_baseline(sample_stock_topic)
    assert baseline.domain == "stock_analysis"
    assert any(a.name == "investment_report" for a in baseline.required_artifacts)
