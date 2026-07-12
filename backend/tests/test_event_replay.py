# 事件总线增强测试：seq 自增、增量回放、GET /events 端点、WS from_seq 参数
from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from app.events import bus, make_event
from app.main import create_app
from app.models import MeetingStatus
from app.orchestrator import runner as runner_mod
from app.orchestrator.runner import Runner
from app.routers import meetings as meetings_mod


# ---------- fixtures ----------

@pytest.fixture()
def client():
    """构造测试客户端"""
    app = create_app()
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _reset_state():
    """每个测试前清理进程级单例状态，保证隔离"""
    runner_mod._states.clear()
    meetings_mod._running_tasks.clear()
    bus._subs.clear()
    bus._history.clear()
    yield
    runner_mod._states.clear()
    meetings_mod._running_tasks.clear()
    bus._subs.clear()
    bus._history.clear()


def _run_to_done(meeting_id: str):
    """同步运行会议到完成（绕过异步 run 端点，供测试使用）"""
    state = runner_mod.get_state(meeting_id)
    assert state is not None
    # 从暂停态恢复
    if state.status == MeetingStatus.PAUSED:
        state.status = MeetingStatus.RUNNING
        state.paused_snapshot = None
    runner = Runner()
    state = asyncio.run(runner.run(state))
    runner_mod.set_state(state)
    return state


# ---------- 事件总线单元测试 ----------

def test_event_seq_auto_increment():
    """seq 自动递增：发布3个事件，验证 seq 为 0,1,2"""
    meeting_id = "mtg-seq-test"
    for i in range(3):
        asyncio.run(bus.publish(make_event("test.event", meeting_id, {"index": i})))
    events = bus.history(meeting_id)
    assert len(events) == 3
    assert [e.seq for e in events] == [0, 1, 2]


def test_replay_from_seq():
    """增量回放：发布5个事件，replay(from_seq=2) 返回 seq>2 的事件（3和4）"""
    meeting_id = "mtg-replay-test"
    for i in range(5):
        asyncio.run(bus.publish(make_event("test.event", meeting_id, {"index": i})))
    new_events = bus.replay(meeting_id, from_seq=2)
    assert len(new_events) == 2
    assert [e.seq for e in new_events] == [3, 4]


def test_last_seq():
    """last_seq：无事件返回0，有事件返回最后一条的 seq"""
    # 无事件
    assert bus.last_seq("mtg-empty") == 0
    # 有事件
    meeting_id = "mtg-lastseq-test"
    for i in range(3):
        asyncio.run(bus.publish(make_event("test.event", meeting_id, {"index": i})))
    assert bus.last_seq(meeting_id) == 2


# ---------- GET /meetings/{id}/events 端点测试 ----------

def test_events_endpoint(client):
    """GET /events：创建会议 → run → 返回事件列表"""
    resp = client.post("/meetings", json={"topic": "事件端点测试"})
    assert resp.status_code == 200
    meeting_id = resp.json()["meeting_id"]
    _run_to_done(meeting_id)

    resp = client.get(f"/meetings/{meeting_id}/events")
    assert resp.status_code == 200
    data = resp.json()
    assert data["meeting_id"] == meeting_id
    assert data["from_seq"] == 0
    assert data["last_seq"] > 0
    assert data["count"] > 0
    assert len(data["events"]) == data["count"]
    # 每条事件都应包含 seq 字段
    for ev in data["events"]:
        assert "seq" in ev
    # 验证关键事件类型存在
    event_types = {ev["type"] for ev in data["events"]}
    assert "meeting.created" in event_types
    assert "stage.changed" in event_types


def test_events_endpoint_incremental(client):
    """GET /events?from_seq=2：只返回 seq>2 的事件"""
    resp = client.post("/meetings", json={"topic": "增量事件端点测试"})
    meeting_id = resp.json()["meeting_id"]
    _run_to_done(meeting_id)

    # 先取全部事件，确认有足够事件做增量
    resp_all = client.get(f"/meetings/{meeting_id}/events")
    all_data = resp_all.json()
    last_seq = all_data["last_seq"]
    assert last_seq > 2

    # 取增量事件
    resp = client.get(f"/meetings/{meeting_id}/events?from_seq=2")
    assert resp.status_code == 200
    data = resp.json()
    assert data["from_seq"] == 2
    assert data["last_seq"] == last_seq
    # 所有返回事件的 seq 都应 > 2
    for ev in data["events"]:
        assert ev["seq"] > 2


def test_events_not_found(client):
    """GET /events：不存在的会议返回 404"""
    resp = client.get("/meetings/nonexistent/events")
    assert resp.status_code == 404


# ---------- WebSocket from_seq 增量回放测试 ----------

def test_ws_incremental_replay(client):
    """WS 增量回放：带 from_seq 参数，只推增量事件，不推 snapshot"""
    resp = client.post("/meetings", json={"topic": "WS 增量回放测试"})
    meeting_id = resp.json()["meeting_id"]
    _run_to_done(meeting_id)

    last_seq = bus.last_seq(meeting_id)
    assert last_seq > 2  # 确保有足够事件做增量回放

    # 带 from_seq=2 连接，只推 seq > 2 的事件
    with client.websocket_connect(f"/ws/meetings/{meeting_id}?from_seq=2") as ws:
        messages: list[dict] = []
        for _ in range(100):
            raw = ws.receive_text()
            msg = json.loads(raw)
            messages.append(msg)
            if msg.get("type") == "replay.done":
                break

    # 不应推送 snapshot（增量回放跳过快照）
    types = [m["type"] for m in messages]
    assert "snapshot" not in types

    # replay.done 应包含 from_seq 和 last_seq
    replay_done = messages[-1]
    assert replay_done["type"] == "replay.done"
    assert replay_done["from_seq"] == 2
    assert replay_done["last_seq"] == last_seq

    # 所有领域事件（非 replay.done 控制帧）的 seq 都应 > 2
    for msg in messages:
        if msg["type"] != "replay.done":
            assert msg.get("seq", 0) > 2


def test_ws_full_replay_default(client):
    """WS 完整回放：不带 from_seq，推 snapshot + replay.done（历史事件已聚合在快照中）"""
    resp = client.post("/meetings", json={"topic": "WS 完整回放测试"})
    meeting_id = resp.json()["meeting_id"]
    _run_to_done(meeting_id)

    last_seq = bus.last_seq(meeting_id)

    # 不带 from_seq 连接（默认 0），应推 snapshot，随后直接 replay.done
    with client.websocket_connect(f"/ws/meetings/{meeting_id}") as ws:
        messages: list[dict] = []
        for _ in range(100):
            raw = ws.receive_text()
            msg = json.loads(raw)
            messages.append(msg)
            if msg.get("type") == "replay.done":
                break

    # 第一条应是 snapshot
    assert messages[0]["type"] == "snapshot"
    assert messages[0]["meeting_id"] == meeting_id

    # 完整回放跳过历史事件，避免与快照重复
    types = [m["type"] for m in messages]
    assert "stage.changed" not in types
    assert "agent.spoke" not in types

    # replay.done 应包含 from_seq=0 和 last_seq
    replay_done = messages[-1]
    assert replay_done["type"] == "replay.done"
    assert replay_done["from_seq"] == 0
    assert replay_done["last_seq"] == last_seq
