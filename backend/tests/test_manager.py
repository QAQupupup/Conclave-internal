"""测试 MeetingManager 的调度与治理入口。

使用 monkeypatch 替换 compute 层，避免真实 LLM 调用。
"""
from __future__ import annotations


import pytest

from app.agents import compute as compute_mod
from app.agents.compute import ThinkRequest, ThinkResponse
from app.models import MeetingState, Stage
from app.orchestrator.manager import MeetingManager


class StageAwareStubCompute:
    """根据 req.stage / schema_hint 返回不同结构化的结果。

    同时满足：
    - AgentRuntime 直接调用（通过 think）
    - 旧节点函数内 build_xxx_prompt 调用
    """

    async def think(self, req: ThinkRequest) -> ThinkResponse:
        stage = req.stage
        if stage == "clarify":
            return ThinkResponse(success=True, result={
                "clarified_topic": "开发一个 FastAPI + React 的 Wiki 系统",
                "key_questions": ["如何支持 Markdown？", "权限模型是什么？"],
                "team_config": [
                    {"role": "product_architect", "stance": "重价值与边界"},
                    {"role": "engineer", "stance": "重可行性与风险"},
                ],
                "complexity": "full",
            })
        if stage == "intra_team":
            return ThinkResponse(success=True, result={
                "claims": [{"claim": "需要 Markdown 编辑支持", "confidence": 0.9, "evidence": "Wiki 核心功能"}],
            })
        if stage == "cross_team":
            return ThinkResponse(success=True, result={
                "conflicts": [],
                "consensus": "一致同意需要 Markdown 支持",
            })
        if stage == "evidence_check":
            return ThinkResponse(success=True, result={
                "evidence_set": [],
            })
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
    """每个测试前重置全局 compute 实例"""
    compute_mod.reset_compute()
    yield
    compute_mod.reset_compute()


@pytest.fixture
def fresh_state(sample_wiki_topic) -> MeetingState:
    return MeetingState(meeting_id="mtg-test", topic=sample_wiki_topic)


@pytest.mark.asyncio
async def test_run_stage_returns_meeting_state(monkeypatch, fresh_state):
    """run_stage 应返回更新后的 MeetingState"""
    monkeypatch.setattr(compute_mod, "_compute", StageAwareStubCompute())

    manager = MeetingManager(max_recursion_depth=0)
    state = await manager.run_stage(fresh_state, "clarify")

    assert isinstance(state, MeetingState)
    assert state.clarified_topic is not None
    assert state.charter is not None
    assert "clarify" in state.confidence_flags


@pytest.mark.asyncio
async def test_run_stage_intra_team(monkeypatch, fresh_state):
    """intra_team 应产生 claims 与 messages"""
    monkeypatch.setattr(compute_mod, "_compute", StageAwareStubCompute())

    # 先运行 clarify 拿到 team_config
    manager = MeetingManager(max_recursion_depth=0)
    state = await manager.run_stage(fresh_state, "clarify")
    assert state.team_config

    state = await manager.run_stage(state, "intra_team")
    assert isinstance(state, MeetingState)
    assert len(state.claims) > 0
    assert len(state.messages) > 0
    assert "intra_team" in state.confidence_flags


@pytest.mark.asyncio
async def test_run_stage_full_pipeline(monkeypatch, fresh_state):
    """依次跑 clarify -> intra_team -> cross_team -> produce"""
    monkeypatch.setattr(compute_mod, "_compute", StageAwareStubCompute())

    manager = MeetingManager(max_recursion_depth=0)
    state = fresh_state

    state = await manager.run_stage(state, "clarify")
    assert state.stage == Stage.INTRA_TEAM

    state = await manager.run_stage(state, "intra_team")
    assert len(state.claims) > 0

    state = await manager.run_stage(state, "cross_team")

    state = await manager.run_stage(state, "produce")
    assert state.artifact is not None
    assert "prd" in state.artifact


def test_manager_selects_baseline():
    manager = MeetingManager()
    baseline = manager.select_baseline("帮我分析一只股票", "")
    assert baseline.domain == "stock_analysis"
    baseline2 = manager.select_baseline("开发系统", "")
    assert baseline2.domain == "software_dev"


def test_select_baseline_with_explicit_domain_hint():
    manager = MeetingManager()
    baseline = manager.select_baseline("任意话题", domain_hint="software_dev")
    assert baseline.domain == "software_dev"
