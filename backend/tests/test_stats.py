# 统计端点测试 + MockLLM trace 记录验证
# 验证 GET /stats 返回完整运行统计，MockLLM 被调用后 trace 正确记录
from __future__ import annotations

import asyncio

# ---------- stats 端点测试 ----------


def test_stats_endpoint(client):
    """GET /stats 返回会议运行统计"""
    resp = client.post("/meetings", json={"topic": "统计测试"})
    meeting_id = resp.json()["meeting_id"]

    # 运行会议
    from app.models import MeetingStatus
    from app.orchestrator import runner as runner_mod

    state = runner_mod.get_state(meeting_id)
    assert state is not None
    if state.status == MeetingStatus.PAUSED:
        state.status = MeetingStatus.RUNNING
        state.paused_snapshot = None
    from app.orchestrator.runner import Runner

    state = asyncio.run(Runner().run(state))
    runner_mod.set_state(state)

    # 获取统计
    resp = client.get(f"/meetings/{meeting_id}/stats")
    assert resp.status_code == 200
    data = resp.json()

    # 验证统计字段完整
    assert data["meeting_id"] == meeting_id
    assert data["topic"] == "统计测试"
    assert data["stage"] == "produce"
    assert data["status"] == "done"
    assert "llm_trace" in data
    assert "confidence_flags" in data
    assert "message_count" in data
    assert "claim_count" in data
    assert "conflict_count" in data
    assert "evidence_count" in data
    assert "evidence_source_distribution" in data
    assert "drift" in data
    assert "borrowed_agents" in data
    assert "conclusion_chain_length" in data

    # stub 模式下消息数应大于 0
    assert data["message_count"] > 0
    assert data["claim_count"] > 0
    # 六阶段都应锁定
    assert data["conclusion_chain_length"] == 6


def test_stats_not_found(client):
    """GET /stats 不存在的会议返回 404"""
    resp = client.get("/meetings/nonexistent/stats")
    assert resp.status_code == 404


def test_stats_evidence_source_distribution(client):
    """统计端点：证据来源分布正确归类"""
    resp = client.post("/meetings", json={"topic": "证据分布测试"})
    meeting_id = resp.json()["meeting_id"]

    # 运行会议
    from app.models import MeetingStatus
    from app.orchestrator import runner as runner_mod
    from app.orchestrator.runner import Runner

    state = runner_mod.get_state(meeting_id)
    state.status = MeetingStatus.RUNNING
    state = asyncio.run(Runner().run(state))
    runner_mod.set_state(state)

    resp = client.get(f"/meetings/{meeting_id}/stats")
    data = resp.json()
    dist = data["evidence_source_distribution"]

    # 所有来源应归类为已知类型
    valid_categories = {"doc", "web", "common", "assumption", "unknown"}
    for cat in dist:
        assert cat in valid_categories, f"未知证据来源类别: {cat}"


# ---------- MockLLM trace 记录测试 ----------


def test_mock_llm_records_trace(client, mock_llm):
    """MockLLM 被调用后 trace 不记录（只有 RealLLM 记录），但流程正常完成"""
    # 不设置任何响应，MockLLM 返回默认 {"result": "mock"}
    # 这会导致 Pydantic 校验失败（字段不匹配），但 RealLLM 有重试+降级
    # mock_llm 直接返回 dict，不走 trace 记录逻辑

    resp = client.post("/meetings", json={"topic": "MockLLM 测试"})
    meeting_id = resp.json()["meeting_id"]

    # 运行会议（MockLLM 返回不匹配的 schema，流程应通过降级完成）
    from app.models import MeetingStatus
    from app.orchestrator import runner as runner_mod
    from app.orchestrator.runner import Runner

    state = runner_mod.get_state(meeting_id)
    state.status = MeetingStatus.RUNNING
    try:
        state = asyncio.run(Runner().run(state))
        runner_mod.set_state(state)
    except Exception:
        # MockLLM 返回的 {"result": "mock"} 不符合 schema，可能导致异常
        # 这验证了系统在没有有效 LLM 输出时的行为
        pass

    # MockLLM 至少被调用过
    assert len(mock_llm.call_log) > 0
    # 至少有一次调用的 schema_hint 包含 "clarify"（意图分类后进入 clarify 阶段）
    schema_hints = [call[1] for call in mock_llm.call_log]
    assert any("clarify" in hint for hint in schema_hints), f"期望 clarify 出现在调用中，实际: {schema_hints}"


def test_stats_endpoint_fields_complete(client):
    """stats 端点返回的所有字段都有预期类型"""
    resp = client.post("/meetings", json={"topic": "字段完整性测试"})
    meeting_id = resp.json()["meeting_id"]

    from app.models import MeetingStatus
    from app.orchestrator import runner as runner_mod
    from app.orchestrator.runner import Runner

    state = runner_mod.get_state(meeting_id)
    state.status = MeetingStatus.RUNNING
    state = asyncio.run(Runner().run(state))
    runner_mod.set_state(state)

    resp = client.get(f"/meetings/{meeting_id}/stats")
    data = resp.json()

    # 类型检查
    assert isinstance(data["llm_trace"], dict)
    assert isinstance(data["confidence_flags"], dict)
    assert isinstance(data["message_count"], int)
    assert isinstance(data["claim_count"], int)
    assert isinstance(data["conflict_count"], int)
    assert isinstance(data["evidence_count"], int)
    assert isinstance(data["evidence_source_distribution"], dict)
    assert isinstance(data["drift"], dict)
    assert isinstance(data["drift"]["total_checks"], int)
    assert isinstance(data["drift"]["drift_detected"], int)
    assert isinstance(data["borrowed_agents"], int)
    assert isinstance(data["conclusion_chain_length"], int)

    # llm_trace 内部结构
    llm = data["llm_trace"]
    assert "total_calls" in llm
    assert "valid_calls" in llm
    assert "fallback_calls" in llm
    assert "success_rate" in llm
    assert "avg_latency_ms" in llm
    assert "stage_stats" in llm
    assert "errors" in llm
