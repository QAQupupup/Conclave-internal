# 全链路追踪 ID 测试：验证 request_id 从入口到日志/事件/LLM 调用的关联
from __future__ import annotations

import asyncio

from app.context import (
    get_meeting_id,
    get_request_id,
    get_trace_context,
    new_request_id,
    reset_request_id,
    reset_meeting_id,
    set_request_id,
    set_meeting_id,
)


# ---------- contextvars 基础测试 ----------

def test_request_id_default():
    """默认 request_id 为 '-'（未设置时）"""
    assert get_request_id() == "-"


def test_meeting_id_default():
    """默认 meeting_id 为 '-'（未设置时）"""
    assert get_meeting_id() == "-"


def test_set_and_get_request_id():
    """设置 request_id 后能正确读取"""
    token = set_request_id("req-test-123")
    assert get_request_id() == "req-test-123"
    assert get_trace_context()["request_id"] == "req-test-123"
    reset_request_id(token)
    assert get_request_id() == "-"


def test_new_request_id_format():
    """new_request_id 生成正确格式"""
    rid = new_request_id()
    assert rid.startswith("req-")
    assert len(rid) == 16  # req- + 12 hex


def test_trace_context_snapshot():
    """get_trace_context 返回完整快照"""
    tok1 = set_request_id("req-abc")
    set_meeting_id("mtg-xyz")
    ctx = get_trace_context()
    assert ctx["request_id"] == "req-abc"
    assert ctx["meeting_id"] == "mtg-xyz"
    reset_request_id(tok1)


# ---------- 日志注入测试 ----------

def test_log_injects_request_id(caplog):
    """日志自动注入 request_id（通过 LogRecord 属性验证）"""
    import logging as _logging
    from app.logging_config import TraceContextFilter

    # 给 caplog handler 添加追踪过滤器
    caplog.handler.addFilter(TraceContextFilter())
    _logging.getLogger("app").setLevel(_logging.INFO)
    _logging.getLogger("app.test").setLevel(_logging.INFO)
    caplog.set_level(_logging.INFO, logger="app.test")

    token = set_request_id("req-log-test")
    logger = _logging.getLogger("app.test")
    logger.info("测试日志注入")

    # 检查 LogRecord 是否被注入了 request_id 属性
    records = [r for r in caplog.records if "测试日志注入" in r.message]
    assert len(records) > 0
    assert hasattr(records[0], "request_id"), "LogRecord 应有 request_id 属性"
    assert records[0].request_id == "req-log-test", \
        f"request_id 应为 req-log-test, 实际: {records[0].request_id}"
    reset_request_id(token)


def test_log_injects_meeting_id(caplog):
    """日志自动注入 meeting_id（通过 LogRecord 属性验证）"""
    import logging as _logging
    from app.logging_config import TraceContextFilter

    caplog.handler.addFilter(TraceContextFilter())
    _logging.getLogger("app").setLevel(_logging.INFO)
    _logging.getLogger("app.test2").setLevel(_logging.INFO)
    caplog.set_level(_logging.INFO, logger="app.test2")

    tok1 = set_request_id("req-123")
    tok2 = set_meeting_id("mtg-456")
    logger = _logging.getLogger("app.test2")
    logger.info("会议日志测试")

    records = [r for r in caplog.records if "会议日志测试" in r.message]
    assert len(records) > 0
    assert hasattr(records[0], "meeting_id"), "LogRecord 应有 meeting_id 属性"
    assert records[0].meeting_id == "mtg-456", \
        f"meeting_id 应为 mtg-456, 实际: {records[0].meeting_id}"
    reset_meeting_id(tok2)
    reset_request_id(tok1)


# ---------- HTTP 请求追踪测试 ----------

def test_http_response_has_request_id(client):
    """HTTP 响应头包含 X-Request-Id"""
    resp = client.get("/health")
    assert resp.status_code == 200
    assert "x-request-id" in resp.headers or "X-Request-Id" in resp.headers


def test_http_request_id_unique_per_request(client):
    """每个请求的 request_id 唯一"""
    resp1 = client.get("/health")
    resp2 = client.get("/health")
    rid1 = resp1.headers.get("x-request-id", resp1.headers.get("X-Request-Id", ""))
    rid2 = resp2.headers.get("x-request-id", resp2.headers.get("X-Request-Id", ""))
    assert rid1 != rid2, "不同请求的 request_id 应不同"
    assert rid1.startswith("req-")
    assert rid2.startswith("req-")


def test_http_inherits_request_id_from_header(client):
    """客户端传入 X-Request-Id 时服务端继承"""
    custom_rid = "req-custom-from-client"
    resp = client.get("/health", headers={"X-Request-Id": custom_rid})
    rid = resp.headers.get("x-request-id", resp.headers.get("X-Request-Id", ""))
    assert rid == custom_rid, "服务端应继承客户端传入的 X-Request-Id"


# ---------- 事件 trace_id 关联测试 ----------

def test_event_has_trace_id(client):
    """会议事件自动携带 trace_id（关联到 request_id）"""
    resp = client.post("/meetings", json={"topic": "trace_id 测试"})
    meeting_id = resp.json()["meeting_id"]

    # 获取创建会议的 request_id
    resp.headers.get("x-request-id", resp.headers.get("X-Request-Id", ""))

    # 运行会议
    from app.orchestrator import runner as runner_mod
    from app.models import MeetingStatus
    from app.orchestrator.runner import Runner

    state = runner_mod.get_state(meeting_id)
    state.status = MeetingStatus.RUNNING
    state = asyncio.run(Runner().run(state))
    runner_mod.set_state(state)

    # 检查事件都有 trace_id
    from app.events import bus
    events = bus.history(meeting_id)
    assert len(events) > 0
    for ev in events:
        assert ev.trace_id is not None, f"事件 {ev.type} 缺少 trace_id"
        assert ev.trace_id.startswith("req-"), f"trace_id 应为 req- 格式, 实际: {ev.trace_id}"


def test_events_endpoint_returns_trace_id(client):
    """GET /events 返回的事件包含 trace_id 字段"""
    resp = client.post("/meetings", json={"topic": "events trace 测试"})
    meeting_id = resp.json()["meeting_id"]

    from app.orchestrator import runner as runner_mod
    from app.models import MeetingStatus
    from app.orchestrator.runner import Runner

    state = runner_mod.get_state(meeting_id)
    state.status = MeetingStatus.RUNNING
    state = asyncio.run(Runner().run(state))
    runner_mod.set_state(state)

    resp = client.get(f"/meetings/{meeting_id}/events")
    assert resp.status_code == 200
    data = resp.json()
    for ev in data["events"]:
        assert "trace_id" in ev
        assert ev["trace_id"] is not None
