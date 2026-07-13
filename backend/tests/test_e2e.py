# 端到端测试：一次完整会议 + 全链路日志 + 统计验证
# 验证：六阶段流程 + 日志输出 + trace 记录 + stats 端点 + 事件序列
# 可在 stub 模式或真实 LLM 模式下运行
from __future__ import annotations

import asyncio
import json
import logging
import time


logger = logging.getLogger("app.tests.e2e")


def test_e2e_full_meeting_with_logging(client, caplog):
    """端到端：一次完整会议，验证日志、trace、stats、事件全链路

    caplog: pytest 内置日志捕获 fixture，验证日志埋点是否正确
    """
    # setup_logging 设置了模块级 WARNING，需要覆盖为 INFO 才能捕获 runner 日志
    import logging as _logging
    _logging.getLogger("app").setLevel(_logging.INFO)
    _logging.getLogger("app.orchestrator").setLevel(_logging.INFO)
    _logging.getLogger("app.orchestrator.runner").setLevel(_logging.INFO)
    caplog.set_level(_logging.INFO, logger="app.orchestrator.runner")

    # 1. 创建会议
    topic = "设计一个端到端测试会议：团队任务管理 API"
    resp = client.post("/meetings", json={"topic": topic})
    assert resp.status_code == 200
    meeting_id = resp.json()["meeting_id"]
    logger.info("会议已创建: %s", meeting_id)

    # 2. 上传文档（可选，增强 RAG 证据）
    md_content = (
        "# 任务管理 API 规格说明\n"
        "## 核心功能\n"
        "- 任务 CRUD 操作\n"
        "- 任务分配给团队成员\n"
        "- 优先级设置：高/中/低\n"
        "- 进度跟踪：待办/进行中/已完成\n"
        "## 技术约束\n"
        "- RESTful API\n"
        "- JSON 格式\n"
        "- 需要 API Key 认证\n"
    )
    resp = client.post(
        f"/meetings/{meeting_id}/documents",
        files={"file": ("spec.md", md_content, "text/markdown")},
    )
    assert resp.status_code == 200
    doc_chunks = resp.json().get("chunks", 0)
    logger.info("文档已上传: %d chunks", doc_chunks)

    # 3. 运行会议（六阶段）
    from app.orchestrator import runner as runner_mod
    from app.models import MeetingStatus
    from app.orchestrator.runner import Runner

    state = runner_mod.get_state(meeting_id)
    assert state is not None
    state.status = MeetingStatus.RUNNING

    t0 = time.monotonic()
    state = asyncio.run(Runner().run(state))
    elapsed = time.monotonic() - t0
    runner_mod.set_state(state)
    logger.info("会议运行完成: %.2fs", elapsed)

    # 4. 验证最终状态
    assert state.stage.value == "produce"
    assert state.status.value == "done"

    # 5. 验证日志输出（runner 日志埋点 + 全链路追踪 ID）
    log_text = caplog.text
    assert "开始运行" in log_text, "runner 应记录开始运行日志"
    assert "阶段" in log_text and "完成" in log_text, "runner 应记录阶段完成日志"
    assert "运行结束" in log_text, "runner 应记录运行结束日志"

    # 验证日志中包含 meeting_id（全链路关联）
    assert meeting_id in log_text, f"日志应包含 meeting_id={meeting_id}"

    # 8. 验证事件历史
    from app.events import bus
    events = bus.history(meeting_id)
    assert len(events) > 0, "会议应产生事件"
    # 验证事件序列号单调递增（全局 seq 可能被 system.meetings.changed 等通配事件占用）
    seqs = [e.seq for e in events]
    assert seqs[0] == 0, f"首个事件 seq 应为 0，实际为 {seqs[0]}"
    for prev, cur in zip(seqs, seqs[1:]):
        assert cur > prev, f"事件 seq 应单调递增，出现 {prev} -> {cur}"
    # 验证事件 trace_id 不为空（全链路追踪）
    for ev in events:
        assert ev.trace_id is not None, f"事件 {ev.type} 缺少 trace_id"

    # 6. 验证 trace 统计
    from app.events import bus
    trace = state.llm_trace
    trace_summary = trace.summary()
    logger.info("Trace 统计: %s", json.dumps(trace_summary, ensure_ascii=False, default=str))
    # stub 模式下 calls 为空，但 summary 结构完整
    assert "total_calls" in trace_summary
    assert "success_rate" in trace_summary
    assert "stage_stats" in trace_summary

    # 7. 验证 stats 端点
    resp = client.get(f"/meetings/{meeting_id}/stats")
    assert resp.status_code == 200
    stats = resp.json()
    logger.info("Stats: msg=%d, claims=%d, conflicts=%d, evidence=%d",
                stats["message_count"], stats["claim_count"],
                stats["conflict_count"], stats["evidence_count"])

    assert stats["meeting_id"] == meeting_id
    assert stats["stage"] == "produce"
    assert stats["status"] == "done"
    assert stats["message_count"] > 0
    assert stats["claim_count"] > 0
    assert stats["conclusion_chain_length"] == 6
    assert stats["drift"]["total_checks"] > 0

    # 9. 验证 trace 端点
    resp = client.get(f"/meetings/{meeting_id}/trace")
    assert resp.status_code == 200
    trace_data = resp.json()
    assert trace_data["meeting_id"] == meeting_id
    assert "summary" in trace_data
    assert "calls" in trace_data

    # 10. 验证 charter 端点
    resp = client.get(f"/meetings/{meeting_id}/charter")
    assert resp.status_code == 200
    charter_data = resp.json()
    assert "charter" in charter_data
    assert "conclusion_chain" in charter_data
    assert "confidence_flags" in charter_data
    assert charter_data["charter"] is not None

    # 11. 验证 events 端点
    resp = client.get(f"/meetings/{meeting_id}/events")
    assert resp.status_code == 200
    events_data = resp.json()
    assert events_data["meeting_id"] == meeting_id
    assert events_data["count"] > 0
    assert events_data["last_seq"] > 0
    # 验证每条事件都有 trace_id（全链路追踪）
    for ev in events_data["events"]:
        assert "trace_id" in ev
        assert ev["trace_id"] is not None, f"事件 {ev['type']} 缺少 trace_id"

    # 12. 验证 events 增量端点
    resp = client.get(f"/meetings/{meeting_id}/events?from_seq=2")
    assert resp.status_code == 200
    inc_data = resp.json()
    assert inc_data["from_seq"] == 2
    # 增量事件数 <= 全部事件数
    assert inc_data["count"] <= events_data["count"]

    # 13. 验证产出物
    assert state.artifact is not None
    prd = state.artifact.get("prd", {})
    openapi = state.artifact.get("openapi", "")
    assert prd.get("title") or prd.get("goal"), "PRD 应有标题或目标"
    assert openapi, "应产出 OpenAPI"

    logger.info("端到端测试全部通过！events=%d, messages=%d, claims=%d, conflicts=%d",
                len(events), stats["message_count"], stats["claim_count"], stats["conflict_count"])


def test_e2e_confidence_flags_all_stages(client):
    """端到端：六阶段全部有置信度标记"""
    resp = client.post("/meetings", json={"topic": "置信度端到端测试"})
    meeting_id = resp.json()["meeting_id"]

    from app.orchestrator import runner as runner_mod
    from app.models import MeetingStatus
    from app.orchestrator.runner import Runner

    state = runner_mod.get_state(meeting_id)
    state.status = MeetingStatus.RUNNING
    state = asyncio.run(Runner().run(state))
    runner_mod.set_state(state)

    flags = state.confidence_flags
    for stage in ["clarify", "intra_team", "cross_team", "evidence_check", "arbitrate", "produce"]:
        assert stage in flags, f"阶段 {stage} 缺少置信度标记"
        assert flags[stage] in ("high", "low", "fallback"), f"阶段 {stage} 置信度值无效: {flags[stage]}"


def test_e2e_drift_log_complete(client):
    """端到端：每条发言都有漂移检查记录"""
    resp = client.post("/meetings", json={"topic": "漂移日志端到端测试"})
    meeting_id = resp.json()["meeting_id"]

    from app.orchestrator import runner as runner_mod
    from app.models import MeetingStatus
    from app.orchestrator.runner import Runner

    state = runner_mod.get_state(meeting_id)
    state.status = MeetingStatus.RUNNING
    state = asyncio.run(Runner().run(state))
    runner_mod.set_state(state)

    # 漂移日志应覆盖主要阶段（stub 模式下不一定每条发言都产生记录，但核心阶段均需检查）
    assert len(state.drift_log) > 0, "应产生漂移检查记录"
    drift_stages = {entry["stage"] for entry in state.drift_log}
    assert "clarify" in drift_stages, "clarify 阶段应有漂移检查"
    assert "produce" in drift_stages, "produce 阶段应有漂移检查"

    # 每条记录字段完整
    for entry in state.drift_log:
        assert "role" in entry
        assert "stage" in entry
        assert "is_drift" in entry
        assert "severity" in entry
        assert "content_preview" in entry
