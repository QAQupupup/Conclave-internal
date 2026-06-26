# 端到端测试：创建会议 → 上传文档 → run → 断言六阶段、PRD、OpenAPI、事件广播
from __future__ import annotations

import json
import os

import pytest
from fastapi.testclient import TestClient

from app.events import bus
from app.main import create_app
from app.orchestrator import runner as runner_mod
from app.rag.chunker import chunk_markdown
from app.rag.store import StubEmbedding, cosine_similarity, InMemoryVectorStore


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
    bus._subs.clear()
    bus._history.clear()
    from app.rag import store as store_mod
    store_mod._stores.clear()
    yield
    runner_mod._states.clear()
    bus._subs.clear()
    bus._history.clear()
    store_mod._stores.clear()


# ---------- 基础工具测试 ----------

def test_chunker_splits_by_heading():
    """切块器：按 # / ## 切分"""
    md = (
        "# 用户调研\n"
        "目标用户为中小团队\n"
        "## 架构\n"
        "系统应支持异步任务处理\n"
        "## 范围\n"
        "MVP 不应引入额外中间件\n"
    )
    chunks = chunk_markdown(md, "research")
    assert len(chunks) >= 2
    sections = [c.section for c in chunks]
    assert "用户调研" in sections
    assert "架构" in sections
    assert "范围" in sections
    # 每块都有 char_start/char_end
    for c in chunks:
        assert c.char_end > c.char_start
        assert c.source.startswith("research:")


def test_stub_embedding_deterministic():
    """桩嵌入：相同文本得到相同向量"""
    emb = StubEmbedding(dim=32)
    a = emb.embed("hello world")
    b = emb.embed("hello world")
    assert a == b
    # 不同文本相似度不为 1
    c = emb.embed("totally different")
    assert cosine_similarity(a, c) < 1.0


def test_vector_store_search():
    """向量库：检索 top_k"""
    md = "# 架构\n系统应支持异步任务处理以解耦耗时操作"
    chunks = chunk_markdown(md, "doc")
    store = InMemoryVectorStore()
    store.add_chunks(chunks)
    results = store.search("异步任务", top_k=1)
    assert len(results) == 1
    chunk, score = results[0]
    assert chunk.section == "架构"
    # StubEmbedding 是确定性伪向量，相似度可正可负，只要能返回浮点排序即可
    assert isinstance(score, float)
    # top_k 截断正确
    results2 = store.search("架构", top_k=5)
    assert len(results2) >= 1


# ---------- 端到端会议流程测试 ----------

def test_health(client):
    """健康检查"""
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_full_meeting_flow(client):
    """完整会议：创建 → 上传文档 → run → 断言六阶段、PRD、OpenAPI、事件"""
    # 1. 创建会议
    resp = client.post("/meetings", json={"topic": "设计一个会议决策系统"})
    assert resp.status_code == 200, resp.text
    created = resp.json()
    meeting_id = created["meeting_id"]
    assert created["stage"] == "clarify"
    assert created["status"] == "running"

    # 2. 上传 Markdown 文档
    md_content = (
        "# 用户调研\n"
        "目标用户为中小团队，核心价值在于降低决策成本\n"
        "## 架构\n"
        "系统应支持异步任务处理以解耦耗时操作\n"
        "## 范围\n"
        "短期 MVP 不应引入额外中间件\n"
        "## 约束\n"
        "接口需保持幂等以支持重试\n"
    )
    resp = client.post(
        f"/meetings/{meeting_id}/documents",
        files={"file": ("research.md", md_content, "text/markdown")},
    )
    assert resp.status_code == 200, resp.text
    doc = resp.json()
    assert doc["chunks"] >= 2
    assert "用户调研" in doc["sections"]

    # 3. 触发完整流程
    resp = client.post(f"/meetings/{meeting_id}/run")
    assert resp.status_code == 200, resp.text
    run_result = resp.json()
    assert run_result["status"] == "done"
    assert run_result["stage"] == "produce"
    assert run_result["artifact"] is not None
    assert run_result["messages_count"] > 0

    # 4. 断言产出物 PRD 与 OpenAPI
    artifact = run_result["artifact"]
    assert "prd" in artifact
    assert "openapi" in artifact
    prd = artifact["prd"]
    assert prd["title"]
    assert prd["goal"]
    assert len(prd["api_endpoints"]) > 0
    assert len(prd["open_questions"]) > 0
    openapi = artifact["openapi"]
    assert "openapi" in openapi.lower() or "paths" in openapi.lower()

    # 5. 取会议详情断言六阶段
    resp = client.get(f"/meetings/{meeting_id}")
    assert resp.status_code == 200
    detail = resp.json()
    # 发言记录覆盖的阶段
    message_stages = set(m["stage"] for m in detail["messages"])
    assert "clarify" in message_stages
    assert "intra_team" in message_stages
    assert "cross_team" in message_stages
    assert "arbitrate" in message_stages
    # 冲突与证据
    assert len(detail["conflicts"]) > 0
    assert len(detail["evidence_set"]) > 0
    assert detail["decision_record"] is not None
    assert len(detail["decision_record"]["decisions"]) > 0
    # 产物
    assert detail["artifact"] is not None
    assert detail["artifact"]["prd"]["title"]

    # 6. 断言事件被广播
    events = bus.history(meeting_id)
    event_types = set(e.type for e in events)
    assert "meeting.created" in event_types
    assert "stage.changed" in event_types
    assert "agent.spoke" in event_types
    assert "evidence.attached" in event_types
    assert "artifact.generated" in event_types

    # 7. 断言六阶段都通过 stage.changed 覆盖
    stage_events = [e for e in events if e.type == "stage.changed"]
    reached = set(e.payload["to"] for e in stage_events)
    expected = {"clarify", "intra_team", "cross_team", "evidence_check", "arbitrate", "produce"}
    assert expected.issubset(reached), f"缺失阶段: {expected - reached}"


def test_control_pause_resume_abort(client):
    """控场信号：pause / resume / abort"""
    # 创建会议
    resp = client.post("/meetings", json={"topic": "测试控场信号"})
    meeting_id = resp.json()["meeting_id"]

    # 暂停（会议尚未 run，状态为 running，可暂停）
    resp = client.post(f"/meetings/{meeting_id}/control", json={"signal": "pause"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "paused"
    assert resp.json()["signal"] == "pause"

    # run 时会自动恢复
    resp = client.post(f"/meetings/{meeting_id}/run")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "done"


def test_control_abort(client):
    """abort 终止会议"""
    resp = client.post("/meetings", json={"topic": "测试终止"})
    meeting_id = resp.json()["meeting_id"]

    # 终止
    resp = client.post(f"/meetings/{meeting_id}/control", json={"signal": "abort"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "aborted"

    # 再次 run 应报错
    resp = client.post(f"/meetings/{meeting_id}/run")
    assert resp.status_code == 400


def test_control_inject(client):
    """inject 注入消息"""
    resp = client.post("/meetings", json={"topic": "测试注入"})
    meeting_id = resp.json()["meeting_id"]

    resp = client.post(
        f"/meetings/{meeting_id}/control",
        json={"signal": "inject", "payload": {"message": "补充约束：需支持离线模式"}},
    )
    assert resp.status_code == 200
    assert resp.json()["signal"] == "inject"


def test_meeting_not_found(client):
    """404：不存在的会议"""
    resp = client.get("/meetings/nonexistent")
    assert resp.status_code == 404


def test_run_without_creation(client):
    """404：未创建就 run"""
    resp = client.post("/meetings/nonexistent/run")
    assert resp.status_code == 404


def test_list_meetings(client):
    """列出会议"""
    client.post("/meetings", json={"topic": "会议A"})
    client.post("/meetings", json={"topic": "会议B"})
    resp = client.get("/meetings")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 2


# ---------- WebSocket 测试 ----------

def test_websocket_snapshot_and_events(client):
    """WS：连接回放快照 + 推送事件"""
    # 先创建并 run 完一场会议
    resp = client.post("/meetings", json={"topic": "WS 测试会议"})
    meeting_id = resp.json()["meeting_id"]
    client.post(f"/meetings/{meeting_id}/run")

    # 连接 WS：应回放快照 + 历史事件
    with client.websocket_connect(f"/ws/meetings/{meeting_id}") as ws:
        # 第一条是快照
        msg = json.loads(ws.receive_text())
        assert msg["type"] == "snapshot"
        assert msg["meeting_id"] == meeting_id
        # 快照里有 artifact（已 run 完）
        assert msg["payload"].get("artifact") is not None
        # 循环接收历史事件，直到 replay.done
        received_types: set[str] = set()
        for _ in range(50):
            raw = ws.receive_text()
            msg = json.loads(raw)
            received_types.add(msg.get("type", ""))
            if msg.get("type") == "replay.done":
                break
        # 至少覆盖到关键事件类型
        assert "stage.changed" in received_types or "agent.spoke" in received_types
        assert "artifact.generated" in received_types
        assert "replay.done" in received_types
