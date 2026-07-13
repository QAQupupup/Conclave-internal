# 旁路日志系统测试：LogBus + 多 Sink + 因果链追踪
from __future__ import annotations

import asyncio
import json
import os
import tempfile

from app.observability.log_bus import LogBus
from app.observability.sinks import ConsoleSink, JSONFileSink, RemoteGRPCSink
from app.context import (
    set_request_id,
    set_meeting_id,
    set_runner_session_id,
    reset_request_id,
    reset_meeting_id,
    reset_runner_session_id,
    new_runner_session_id,
)


# ---------- LogBus 基础测试 ----------

class CaptureSink:
    """测试用 sink：捕获所有日志事件到内存列表"""

    def __init__(self):
        self.events: list[dict] = []

    def write(self, event: dict) -> None:
        self.events.append(event)

    def clear(self):
        self.events.clear()


def test_log_bus_emit_to_multiple_sinks():
    """LogBus 分发到多个 sink"""
    sink1 = CaptureSink()
    sink2 = CaptureSink()
    bus = LogBus()
    bus.clear_sinks()
    bus.add_sink(sink1)
    bus.add_sink(sink2)

    bus.info("测试消息", logger="test")
    assert len(sink1.events) == 1
    assert len(sink2.events) == 1
    assert sink1.events[0]["message"] == "测试消息"
    assert sink2.events[0]["message"] == "测试消息"
    assert sink1.events[0]["logger"] == "test"


def test_log_bus_injects_trace_context():
    """LogBus 自动注入追踪上下文（request_id, meeting_id, runner_session_id）"""
    sink = CaptureSink()
    bus = LogBus()
    bus.clear_sinks()
    bus.add_sink(sink)

    tok1 = set_request_id("req-abc")
    tok2 = set_meeting_id("mtg-xyz")
    tok3 = set_runner_session_id("rs-123")
    bus.info("关联测试", logger="test")
    reset_runner_session_id(tok3)
    reset_meeting_id(tok2)
    reset_request_id(tok1)

    assert len(sink.events) == 1
    event = sink.events[0]
    assert event["request_id"] == "req-abc"
    assert event["meeting_id"] == "mtg-xyz"
    assert event["runner_session_id"] == "rs-123"


def test_log_bus_levels():
    """LogBus 支持 4 个日志级别"""
    sink = CaptureSink()
    bus = LogBus()
    bus.clear_sinks()
    bus.add_sink(sink)

    bus.debug("D")
    bus.info("I")
    bus.warning("W")
    bus.error("E")

    assert len(sink.events) == 4
    assert sink.events[0]["level"] == "DEBUG"
    assert sink.events[1]["level"] == "INFO"
    assert sink.events[2]["level"] == "WARNING"
    assert sink.events[3]["level"] == "ERROR"


def test_log_bus_sink_exception_safety():
    """sink 异常不影响主流程和其他 sink"""
    class BadSink:
        def write(self, event):
            raise RuntimeError("sink 故障")

    sink_good = CaptureSink()
    bus = LogBus()
    bus.clear_sinks()
    bus.add_sink(BadSink())
    bus.add_sink(sink_good)

    bus.info("容错测试")  # 不应抛异常
    assert len(sink_good.events) == 1  # 好 sink 仍然收到事件


def test_log_bus_extra_field():
    """LogBus 的 extra 字段被正确传递"""
    sink = CaptureSink()
    bus = LogBus()
    bus.clear_sinks()
    bus.add_sink(sink)

    bus.info("带扩展字段", logger="test", extra={"stage": "clarify", "latency_ms": 150})
    event = sink.events[0]
    assert event["extra"]["stage"] == "clarify"
    assert event["extra"]["latency_ms"] == 150


# ---------- Sink 实现测试 ----------

def test_console_sink_writes_stdout(capsys):
    """ConsoleSink 输出到 stdout"""
    sink = ConsoleSink()
    sink.write({
        "timestamp": "2026-01-01T00:00:00",
        "level": "INFO",
        "request_id": "req-1",
        "meeting_id": "mtg-1",
        "runner_session_id": "rs-1",
        "logger": "test",
        "message": "控制台测试",
        "extra": {},
    })
    captured = capsys.readouterr()
    assert "控制台测试" in captured.out
    assert "req-1" in captured.out
    assert "mtg-1" in captured.out
    assert "rs-1" in captured.out


def test_json_file_sink_writes_json_lines():
    """JSONFileSink 每行一个 JSON 对象"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False, encoding="utf-8") as f:
        path = f.name

    sink = JSONFileSink(path)
    sink.write({
        "timestamp": "2026-01-01T00:00:00",
        "level": "INFO",
        "request_id": "req-1",
        "meeting_id": "mtg-1",
        "runner_session_id": "rs-1",
        "logger": "test",
        "message": "JSON文件测试",
        "extra": {"key": "value"},
    })
    sink.close()

    with open(path, encoding="utf-8") as f:
        lines = f.readlines()
    assert len(lines) == 1
    data = json.loads(lines[0])
    assert data["message"] == "JSON文件测试"
    assert data["extra"]["key"] == "value"

    os.unlink(path)


def test_remote_grpc_sink_buffer():
    """RemoteGRPCSink 缓冲日志，达到阈值时 flush"""
    sink = RemoteGRPCSink(endpoint="localhost:50051", batch_size=3)
    for i in range(3):
        sink.write({"message": f"日志{i}"})
    # 达到阈值后 buffer 被清空
    assert len(sink._buffer) == 0
    sink.close()


# ---------- 因果链测试 ----------

def test_runner_session_id_format():
    """runner_session_id 格式正确"""
    rsid = new_runner_session_id()
    assert rsid.startswith("rs-")
    assert len(rsid) == 15  # rs- + 12 hex


def test_trace_context_includes_runner_session():
    """get_trace_context 包含 runner_session_id"""
    from app.context import get_trace_context
    tok = set_runner_session_id("rs-test")
    ctx = get_trace_context()
    assert ctx["runner_session_id"] == "rs-test"
    reset_runner_session_id(tok)
    assert get_trace_context()["runner_session_id"] == "-"


def test_causation_chain_end_to_end(client):
    """端到端因果链：用户请求 → API → Runner session → 事件 trace_id

    验证：一个会议从创建到运行，所有日志和事件都能通过
    request_id + meeting_id + runner_session_id 关联。
    """
    # 1. 创建会议（HTTP 请求分配 request_id）
    resp = client.post("/meetings", json={"topic": "因果链测试"})
    meeting_id = resp.json()["meeting_id"]
    create_rid = resp.headers.get("x-request-id", resp.headers.get("X-Request-Id", ""))
    assert create_rid.startswith("req-")

    # 2. 运行会议
    from app.orchestrator import runner as runner_mod
    from app.models import MeetingStatus
    from app.orchestrator.runner import Runner

    state = runner_mod.get_state(meeting_id)
    state.status = MeetingStatus.RUNNING
    state = asyncio.run(Runner().run(state))
    runner_mod.set_state(state)

    # 3. 验证事件都有 trace_id（关联到 request_id 或 runner 分配的 request_id）
    from app.events import bus
    events = bus.history(meeting_id)
    assert len(events) > 0
    for ev in events:
        assert ev.trace_id is not None
        assert ev.trace_id.startswith("req-")

    # 4. 验证 trace 中 LLM 调用记录有 meeting_id（stub 模式下 calls 为空，但结构存在）
    trace = state.llm_trace
    assert trace.meeting_id == meeting_id


def test_llm_call_record_has_runner_session_id():
    """LLMCallRecord 包含 runner_session_id 字段"""
    from app.agents.trace import LLMCallRecord
    record = LLMCallRecord(
        call_id="call-test",
        timestamp="2026-01-01T00:00:00",
        stage="clarify",
        model="test",
    )
    assert hasattr(record, "runner_session_id")
    assert record.runner_session_id == ""  # 默认空
