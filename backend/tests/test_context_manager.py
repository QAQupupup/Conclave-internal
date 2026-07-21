"""测试 ContextManager 的上下文预算、分层选择与裁剪。

不调用真实 LLM。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.orchestrator.context_manager import ContextBudget, ContextManager


@dataclass
class FakeState:
    meeting_id: str = "mtg-test"
    topic: str = "开发一个 FastAPI + React 的 Wiki 系统"
    charter: dict[str, Any] = field(default_factory=dict)
    conclusion_chain: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    messages: list[dict[str, Any]] = field(default_factory=list)


def test_context_priority_keeps_charter_and_conclusions():
    mgr = ContextManager(ContextBudget(max_tokens=4000))
    state = FakeState(
        charter={"topic": "重要宪章", "goals": ["目标1", "目标2"]},
        conclusion_chain=[{"stage": "clarify", "summary": "已锁定结论"}],
        messages=[{"stage": "intra_team", "role": "engineer", "content": "x" * 2000}],
    )
    slice_ = mgr.prepare(state, "intra_team", "engineer")
    assert slice_.charter
    assert len(slice_.locked_conclusions) == 1


def test_context_trims_long_messages():
    mgr = ContextManager(ContextBudget(max_tokens=2000))
    long_content = "中" * 4000  # 约 2667 tokens
    state = FakeState(
        charter={"topic": "T"},
        messages=[{"stage": "intra_team", "role": "engineer", "content": long_content} for _ in range(10)],
    )
    slice_ = mgr.prepare(state, "intra_team", "engineer")
    assert slice_.token_estimate <= mgr.budget.available_tokens
    assert len(slice_.recent_messages) < 10


def test_evidence_stage_keeps_full_evidence():
    mgr = ContextManager(ContextBudget(max_tokens=3000))
    state = FakeState(
        charter={"topic": "T"},
        evidence=[{"quote": f"证据{i}", "source": "doc"} for i in range(10)],
    )
    slice_ = mgr.prepare(state, "evidence_check", "engineer")
    assert len(slice_.evidence) == 10


def test_non_evidence_stage_trims_evidence():
    mgr = ContextManager(ContextBudget(max_tokens=3000))
    state = FakeState(
        charter={"topic": "T"},
        evidence=[{"quote": f"证据{i}", "source": "doc"} for i in range(10)],
    )
    slice_ = mgr.prepare(state, "arbitrate", "engineer")
    assert len(slice_.evidence) <= 3
