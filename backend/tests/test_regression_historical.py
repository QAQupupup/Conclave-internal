"""基于历史会议数据的端到端回归测试。

目标：
- 使用典型历史议题（Wiki 系统、股票分析）跑通完整六阶段管线
- 不调用真实 LLM（stub compute）
- 断言最终产物结构、结论链完整性、置信度标记等关键回归指标
"""
from __future__ import annotations

from typing import Any

import pytest

from app.agents import compute as compute_mod
from app.agents.compute import ThinkRequest, ThinkResponse
from app.models import MeetingState, MeetingStatus, Stage
from app.orchestrator import runner as runner_mod
from app.orchestrator.runner import Runner


class HistoricalStubCompute:
    """模拟一个典型 Wiki 项目会议的完整 LLM 响应序列。

    覆盖六阶段：clarify -> intra_team -> cross_team -> arbitrate -> produce。
    """

    async def think(self, req: ThinkRequest) -> ThinkResponse:
        stage = req.stage
        if stage == "clarify":
            return ThinkResponse(success=True, result={
                "clarified_topic": "基于 FastAPI 和 React 的个人 Wiki 知识管理系统",
                "key_questions": [
                    "如何支持 Markdown 与富文本编辑？",
                    "权限模型采用公开/私有还是 RBAC？",
                    "是否支持全文检索与标签体系？",
                ],
                "team_config": [
                    {"role": "product_architect", "stance": "重价值与边界"},
                    {"role": "engineer", "stance": "重可行性与可维护性"},
                    {"role": "ux_designer", "stance": "重用户体验"},
                ],
                "complexity": "full",
            })
        if stage == "intra_team":
            return ThinkResponse(success=True, result={
                "claims": [
                    {"claim": "采用 Markdown 作为默认编辑格式", "confidence": 0.9, "evidence": "Wiki 核心需求"},
                    {"claim": "权限模型先支持公开/私有两种", "confidence": 0.8, "evidence": "MVP 范围控制"},
                ],
            })
        if stage == "cross_team":
            return ThinkResponse(success=True, result={
                "conflicts": [],
                "consensus": "团队一致认为应优先 Markdown + 公开/私有权限",
            })
        if stage == "evidence_check":
            return ThinkResponse(success=True, result={
                "evidence_set": [],
            })
        if stage == "arbitrate":
            return ThinkResponse(success=True, result={
                "decisions": [
                    {"summary": "采用 Markdown 编辑", "verdict": "采纳"},
                    {"summary": "公开/私有权限模型", "verdict": "采纳"},
                ],
                "adopted_claims": ["claim-1", "claim-2"],
            })
        if stage == "produce":
            return ThinkResponse(success=True, result={
                "prd": {
                    "title": "个人 Wiki 系统",
                    "goal": "提供轻量级个人知识管理",
                    "api_endpoints": [
                        {"path": "/pages", "method": "GET"},
                        {"path": "/pages", "method": "POST"},
                    ],
                },
                "openapi": "openapi: 3.0.0\ninfo:\n  title: 个人 Wiki 系统",
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
async def test_regression_wiki_full_meeting_historical(monkeypatch):
    """历史 Wiki 议题完整回归：验证产物、结论链、终态无退化"""
    monkeypatch.setattr(compute_mod, "_compute", HistoricalStubCompute())
    async def _deep_think(_q: str) -> str:
        return "deep_think"

    monkeypatch.setattr(runner_mod, "classify_intent_async", _deep_think)

    state = MeetingState(
        meeting_id="mtg-regression-wiki",
        topic="帮我设计一个个人 Wiki 系统",
        flow_plan="full",
    )
    runner = Runner()
    final_state = await runner.run(state)

    assert final_state.status == MeetingStatus.DONE
    assert final_state.stage == Stage.PRODUCE
    assert final_state.clarified_topic is not None
    assert final_state.charter is not None
    assert len(final_state.claims) > 0
    assert final_state.artifact is not None
    assert "prd" in final_state.artifact
    assert "openapi" in final_state.artifact
    assert len(final_state.conclusion_chain.conclusions) >= 3
    assert "clarify" in final_state.confidence_flags
    assert "produce" in final_state.confidence_flags


class ConflictStubCompute(HistoricalStubCompute):
    """在 cross_team 阶段产生冲突，触发 evidence_check 阶段"""

    async def think(self, req: ThinkRequest) -> ThinkResponse:
        if req.stage == "cross_team":
            return ThinkResponse(success=True, result={
                "conflicts": [
                    {
                        "id": "conflict-1",
                        "type": "preference",
                        "summary": "前端框架选择：React vs Vue",
                        "sides": [
                            {"claim_id": "claim-1", "text": "使用 React", "role": "product_architect"},
                            {"claim_id": "claim-2", "text": "使用 Vue", "role": "engineer"},
                        ],
                    }
                ],
                "consensus": "",
            })
        if req.stage == "evidence_check":
            return ThinkResponse(success=True, result={
                "evidence_set": [
                    {
                        "claim_id": "claim-1",
                        "assessments": [{"supports": "supports", "source": "社区活跃度", "summary": "React 社区更大"}],
                    }
                ],
            })
        return await super().think(req)


@pytest.mark.asyncio
async def test_regression_manager_non_compat_path(monkeypatch):
    """非兼容路径下 Manager.run_stage 也能完成 clarify -> produce"""
    from app.orchestrator.manager import MeetingManager

    monkeypatch.setattr(compute_mod, "_compute", HistoricalStubCompute())

    manager = MeetingManager(max_recursion_depth=0, compatibility_mode=False)
    state = MeetingState(meeting_id="mtg-regression-noncompat", topic="个人 Wiki 系统")

    state = await manager.run_stage(state, "clarify")
    assert state.clarified_topic is not None
    assert state.charter is not None

    state = await manager.run_stage(state, "intra_team")
    assert len(state.claims) > 0

    state = await manager.run_stage(state, "cross_team")

    state = await manager.run_stage(state, "arbitrate")
    assert state.decision_record is not None

    state = await manager.run_stage(state, "produce")
    assert state.artifact is not None
    assert "prd" in state.artifact


@pytest.mark.asyncio
async def test_regression_with_conflict_triggers_evidence_check(monkeypatch):
    """存在冲突时，管线应自动进入 evidence_check 阶段"""
    from app.orchestrator.manager import MeetingManager

    monkeypatch.setattr(compute_mod, "_compute", ConflictStubCompute())

    manager = MeetingManager(max_recursion_depth=0, compatibility_mode=False)
    state = MeetingState(meeting_id="mtg-conflict", topic="个人 Wiki 系统", flow_plan="full")

    state = await manager.run_stage(state, "clarify")
    state = await manager.run_stage(state, "intra_team")
    state = await manager.run_stage(state, "cross_team")

    assert len(state.conflicts) > 0
    assert state.stage.value == "evidence_check"

    state = await manager.run_stage(state, "evidence_check")
    assert "evidence_check" in state.confidence_flags
    assert len(state.evidence_set) > 0

    state = await manager.run_stage(state, "arbitrate")
    state = await manager.run_stage(state, "produce")
    assert state.artifact is not None
