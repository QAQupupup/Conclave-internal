"""基于历史数据的端到端回归测试。

目标：
- 验证 Manager + Scheduler + ContextManager + AgentRuntime 能协同工作
- 不调用真实 LLM（stub compute）
- 使用历史会议议题作为输入，验证输出结构
"""
from __future__ import annotations

from typing import Any

import pytest

from app.agents import compute as compute_mod
from app.agents.compute import ThinkRequest, ThinkResponse
from app.models import MeetingState
from app.orchestrator.manager import MeetingManager


class WikiStubCompute:
    """模拟一个完整 Wiki 会议的 LLM 响应"""

    async def think(self, req: ThinkRequest) -> ThinkResponse:
        stage = req.stage
        if stage == "clarify":
            return ThinkResponse(success=True, result={
                "clarified_topic": "基于 FastAPI 和 React 的个人 Wiki 系统",
                "key_questions": ["如何支持 Markdown？", "权限模型是什么？"],
                "team_config": [
                    {"role": "product_architect", "stance": "重业务价值"},
                    {"role": "engineer", "stance": "重可行性"},
                ],
                "complexity": "full",
            })
        if stage == "intra_team":
            return ThinkResponse(success=True, result={
                "claims": [{"claim": "需要 Markdown 编辑", "type": "constraint"}],
            })
        if stage == "cross_team":
            return ThinkResponse(success=True, result={
                "conflicts": [],
                "consensus": "一致通过",
            })
        if stage == "evidence_check":
            return ThinkResponse(success=True, result={"evidence_set": []})
        if stage == "arbitrate":
            return ThinkResponse(success=True, result={
                "decisions": [],
                "adopted_claims": [],
                "action_brief": "无需仲裁",
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

    manager = MeetingManager(max_recursion_depth=0, compatibility_mode=False)
    state = MeetingState(meeting_id="mtg-e2e", topic=sample_wiki_topic)

    # clarify 阶段：应返回 MeetingState 并设置 charter
    state = await manager.run_stage(state, "clarify")
    assert isinstance(state, MeetingState)
    assert state.clarified_topic is not None
    assert state.charter is not None

    # intra_team 阶段：应产生 claims
    state = await manager.run_stage(state, "intra_team")
    assert len(state.claims) > 0
    assert len(state.messages) > 0

    # produce 阶段：应生成 artifact
    state = await manager.run_stage(state, "produce")
    assert state.artifact is not None
    assert "prd" in state.artifact


@pytest.mark.asyncio
async def test_e2e_stock_analysis_selects_right_baseline(sample_stock_topic):
    manager = MeetingManager()
    baseline = manager.select_baseline(sample_stock_topic)
    assert baseline.domain == "stock_analysis"
    assert any(a.name == "investment_report" for a in baseline.required_artifacts)
