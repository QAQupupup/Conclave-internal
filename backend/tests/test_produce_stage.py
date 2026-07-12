"""Produce 阶段收尾逻辑的专项测试。

覆盖：
- produce_node 在关键字段为空时降级 confidence
- run_produce 正确设置终态、扫描附件、发布降级事件

所有测试使用 monkeypatch 替换 compute / 事件总线，避免真实 LLM 与数据库依赖。
"""
from __future__ import annotations

from typing import Any

import pytest

from app.agents import compute as compute_mod
from app.agents.compute import ThinkRequest, ThinkResponse
from app.config import Settings
from app.events import bus
from app.models import MeetingState, MeetingStatus, Stage
from app.orchestrator.nodes.produce import produce_node
from app.orchestrator.stage_runners import run_produce


class EmptyResultStubCompute:
    """始终返回空结果的 compute 存根，用于触发 produce 内容完整性降级。"""

    async def think(self, req: ThinkRequest) -> ThinkResponse:
        return ThinkResponse(success=True, result={})

    async def think_batch(self, requests: list[ThinkRequest]) -> list[ThinkResponse]:
        return [await self.think(req) for req in requests]


@pytest.fixture(autouse=True)
def reset_compute():
    """每个测试前重置全局 compute 实例。"""
    compute_mod.reset_compute()
    yield
    compute_mod.reset_compute()


@pytest.mark.asyncio
async def test_produce_node_downgrades_confidence_when_prd_openapi_empty(monkeypatch):
    """prd_openapi 产出缺少 prd 和 openapi 时，confidence 应被降级为 low。"""
    monkeypatch.setattr(compute_mod, "_compute", EmptyResultStubCompute())

    state = MeetingState(
        meeting_id="mtg-produce-degrade",
        topic="设计一个空产出系统",
        deliverable_type="prd_openapi",
    )
    state = await produce_node(state)

    assert state.status == MeetingStatus.DONE
    assert state.stage == Stage.PRODUCE
    assert state.confidence_flags.get("produce") == "low"
    assert state.artifact is not None
    assert state.artifact.get("prd") == {}
    assert state.artifact.get("openapi") == ""


@pytest.mark.asyncio
async def test_run_produce_finalizes_state_and_scans_attachments(monkeypatch, tmp_path):
    """run_produce 设置 DONE、扫描代码附件，并保持 artifact 结构完整。"""
    import app.config as config_mod

    monkeypatch.setattr(
        config_mod,
        "settings",
        Settings(workspace_root=str(tmp_path), memory_enabled=False),
    )

    meeting_id = "mtg-produce-attach"
    meeting_dir = tmp_path / meeting_id
    meeting_dir.mkdir(parents=True)
    (meeting_dir / "solution.py").write_text("print('hello')", encoding="utf-8")
    (meeting_dir / "notes.md").write_text("# notes", encoding="utf-8")
    (meeting_dir / "skip.pyc").write_text("binary", encoding="utf-8")

    state = MeetingState(
        meeting_id=meeting_id,
        topic="生成可运行代码",
        deliverable_type="code_analysis",
    )
    state.artifact = {
        "meeting_id": meeting_id,
        "deliverable_type": "code_analysis",
        "code_analysis": {"code": "print('hello')"},
    }

    final_state = await run_produce(state, confidence="high")

    assert final_state.status == MeetingStatus.DONE
    assert final_state.stage == Stage.PRODUCE
    assert final_state.confidence_flags.get("produce") == "high"

    attachments = final_state.artifact.get("attachments", [])
    filenames = {a["filename"] for a in attachments}
    assert "solution.py" in filenames
    assert "notes.md" in filenames
    assert "skip.pyc" not in filenames

    for attachment in attachments:
        assert attachment["meeting_id"] == meeting_id
        assert "path" in attachment
        assert "size" in attachment
        assert attachment["size"] >= 0


@pytest.mark.asyncio
async def test_run_produce_emits_fallback_warning(monkeypatch):
    """存在 fallback 阶段时，应发布 meeting.fallback_warning 事件。"""
    events: list[dict[str, Any]] = []

    async def _capture(event) -> None:
        events.append({"type": event.type, "payload": event.payload})

    monkeypatch.setattr(bus, "publish", _capture)

    state = MeetingState(
        meeting_id="mtg-produce-fallback",
        topic="fallback 测试",
        deliverable_type="prd_openapi",
    )
    state.artifact = {"prd": {"title": "t"}, "openapi": ""}
    state.confidence_flags["clarify"] = "fallback"

    await run_produce(state, confidence="high")

    warning = next((e for e in events if e["type"] == "meeting.fallback_warning"), None)
    assert warning is not None
    assert "clarify" in warning["payload"]["fallback_stages"]
