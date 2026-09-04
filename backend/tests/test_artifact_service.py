"""产物服务层单元测试（ADR-017 Phase 1）。

覆盖：
- extract_artifact_summary：顶层字段 / 嵌套结构 / 空产物（正向 + 边界）
- publish_meeting_artifact：正常发布 / 无产出跳过 / 大产物分流 /
  循环引用降级 / 血缘与版本链传递 / 标题截断（正向 + 多个非正向）
- get_lineage：根不存在 / 线性链 / 菱形血缘 / 成环终止 /
  深度上限截断 / 缺失上游静默跳过（正向 + 多个非正向）
- publish_and_notify：发布异常不阻断终态 / 成功广播事件（降级路径）

DAO 层通过 monkeypatch 替换为内存 fake store，不依赖真实数据库；
事件总线 bus.publish 同样被替换，避免触发 PostgreSQL 写入。
"""

from __future__ import annotations

from typing import Any

import pytest

from app.dao import artifact_dao
from app.domain.meeting import MeetingState
from app.events import bus
from app.services.artifact_service import (
    LARGE_ARTIFACT_BYTES,
    MAX_LINEAGE_DEPTH,
    extract_artifact_summary,
    get_lineage,
    publish_and_notify,
    publish_meeting_artifact,
)

# ---------- fake DAO ----------


class FakeArtifactStore:
    """内存版 artifact_dao：签名与真实 DAO 对齐，记录调用供断言。"""

    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self.publish_calls: list[dict[str, Any]] = []
        self._seq = 0

    async def next_version(self, meeting_id: str, artifact_type: str) -> tuple[int, str | None]:
        versions = [
            (r["version"], r["id"])
            for r in self.rows.values()
            if r["meeting_id"] == meeting_id and r["type"] == artifact_type
        ]
        if not versions:
            return 1, None
        version, latest_id = max(versions, key=lambda v: v[0])
        return version + 1, latest_id

    async def publish_artifact(self, **kwargs: Any) -> dict[str, Any]:
        self.publish_calls.append(kwargs)
        self._seq += 1
        row = {
            "id": f"art-fake-{self._seq:03d}",
            "meeting_id": kwargs["meeting_id"],
            "type": kwargs["artifact_type"],
            "version": kwargs["version"],
            "title": kwargs.get("title"),
            "summary": kwargs.get("summary"),
            "content": kwargs.get("content"),
            "content_ref": kwargs.get("content_ref"),
            "parent_id": kwargs.get("parent_id"),
            "source_artifact_ids": kwargs.get("source_artifact_ids") or [],
            "created_at": "2026-09-04T00:00:00",
        }
        self.rows[row["id"]] = row
        return dict(row)

    async def get_artifact(self, artifact_id: str) -> dict[str, Any] | None:
        row = self.rows.get(artifact_id)
        return dict(row) if row else None

    async def get_artifacts_by_ids(self, artifact_ids: list[str]) -> list[dict[str, Any]]:
        return [dict(self.rows[i]) for i in artifact_ids if i in self.rows]

    def seed(self, artifact_id: str, sources: list[str] | None = None, **fields: Any) -> dict[str, Any]:
        """直接预置一条血缘用产物行。"""
        row = {
            "id": artifact_id,
            "meeting_id": fields.get("meeting_id", "mtg-lineage"),
            "type": fields.get("type", "adr"),
            "version": fields.get("version", 1),
            "title": fields.get("title"),
            "created_at": "2026-09-04T00:00:00",
            "source_artifact_ids": sources or [],
        }
        self.rows[artifact_id] = row
        return row


@pytest.fixture
def fake_store(monkeypatch: pytest.MonkeyPatch) -> FakeArtifactStore:
    store = FakeArtifactStore()
    monkeypatch.setattr(artifact_dao, "next_version", store.next_version)
    monkeypatch.setattr(artifact_dao, "publish_artifact", store.publish_artifact)
    monkeypatch.setattr(artifact_dao, "get_artifact", store.get_artifact)
    monkeypatch.setattr(artifact_dao, "get_artifacts_by_ids", store.get_artifacts_by_ids)
    return store


def _state(**overrides: Any) -> MeetingState:
    base: dict[str, Any] = {
        "meeting_id": "mtg-pub-1",
        "topic": "产物发布测试议题",
        "deliverable_type": "adr",
        "artifact": {"title": "决策记录", "summary": "采用方案 A"},
    }
    base.update(overrides)
    return MeetingState(**base)


# ---------- extract_artifact_summary ----------


def test_summary_from_top_level_fields():
    """顶层 title/summary/verdict 按顺序拼接"""
    artifact = {"title": "T", "summary": "S", "verdict": "可行"}
    assert extract_artifact_summary(artifact) == "T | S | 可行"


def test_summary_from_nested_new_types():
    """三种新产出类型的嵌套结构也能提取摘要"""
    for key in ("feasibility_report", "adr", "test_suite"):
        artifact = {key: {"title": f"{key} 标题", "summary": f"{key} 摘要"}}
        assert extract_artifact_summary(artifact) == f"{key} 标题 | {key} 摘要"


def test_summary_none_artifact_returns_placeholder():
    """空产物返回占位文本（边界）"""
    assert extract_artifact_summary(None) == "（无产出）"
    assert extract_artifact_summary({}) == "（无产出）"


def test_summary_no_extractable_fields():
    """无可提取字段时返回无摘要占位（边界）"""
    assert extract_artifact_summary({"foo": "bar"}) == "（无产出摘要）"


# ---------- publish_meeting_artifact ----------


async def test_publish_happy_path(fake_store: FakeArtifactStore):
    """正常发布：内容/摘要/标题/血缘入库，版本号为 1"""
    state = _state(source_artifact_ids=["art-up-1"])
    published = await publish_meeting_artifact(state)

    assert published is not None
    assert published["version"] == 1
    assert published["parent_id"] is None
    call = fake_store.publish_calls[0]
    assert call["meeting_id"] == "mtg-pub-1"
    assert call["artifact_type"] == "adr"
    assert call["content"] == state.artifact  # 小产物写 content 列
    assert call["content_ref"] is None
    assert call["source_artifact_ids"] == ["art-up-1"]
    assert call["title"] == "决策记录"
    assert call["summary"] == "决策记录 | 采用方案 A"


async def test_publish_version_chain(fake_store: FakeArtifactStore):
    """同会议同类型二次发布：版本递增且 parent_id 指向上一版"""
    first = await publish_meeting_artifact(_state())
    second = await publish_meeting_artifact(_state())
    assert first is not None and second is not None
    assert second["version"] == 2
    assert second["parent_id"] == first["id"]


async def test_publish_skips_when_no_artifact(fake_store: FakeArtifactStore):
    """会议无产出时不发布、不触 DAO（非正向）"""
    assert await publish_meeting_artifact(_state(artifact=None)) is None
    assert fake_store.publish_calls == []


async def test_publish_skips_non_dict_artifact(fake_store: FakeArtifactStore):
    """artifact 非 dict（异常数据）时不发布（非正向）"""
    state = _state()
    # 构造后赋值绕过 Pydantic 构造校验，模拟历史序列化 payload 恢复出的脏数据
    state.artifact = ["not", "a", "dict"]
    assert await publish_meeting_artifact(state) is None
    assert fake_store.publish_calls == []


async def test_publish_large_artifact_stores_ref_only(fake_store: FakeArtifactStore):
    """大产物红线：超阈值不写 content 列，只存 content_ref（边界）"""
    huge = {"title": "大产物", "blob": "x" * (LARGE_ARTIFACT_BYTES + 1)}
    await publish_meeting_artifact(_state(artifact=huge))
    call = fake_store.publish_calls[0]
    assert call["content"] is None
    assert call["content_ref"] == "mtg-pub-1/"


async def test_publish_circular_artifact_treated_as_large(fake_store: FakeArtifactStore):
    """循环引用无法序列化 → 按大产物降级处理而非抛错（异常路径）"""
    circular: dict[str, Any] = {"title": "环"}
    circular["self"] = circular
    published = await publish_meeting_artifact(_state(artifact=circular))
    assert published is not None
    call = fake_store.publish_calls[0]
    assert call["content"] is None
    assert call["content_ref"] == "mtg-pub-1/"


async def test_publish_title_truncated_to_500(fake_store: FakeArtifactStore):
    """标题超长截断到 500 字符（边界）"""
    await publish_meeting_artifact(_state(artifact={"title": "标" * 600}))
    assert fake_store.publish_calls[0]["title"] == "标" * 500


# ---------- get_lineage ----------


async def test_lineage_root_not_found_returns_none(fake_store: FakeArtifactStore):
    """根产物不存在 → None（路由层转 404，非正向）"""
    assert await get_lineage("art-ghost") is None


async def test_lineage_linear_chain(fake_store: FakeArtifactStore):
    """线性血缘 A→B→C：节点带深度，边方向为下游→上游"""
    fake_store.seed("art-c", sources=[])
    fake_store.seed("art-b", sources=["art-c"])
    fake_store.seed("art-a", sources=["art-b"])

    lineage = await get_lineage("art-a")
    assert lineage is not None
    assert lineage["root_id"] == "art-a"
    assert lineage["truncated"] is False
    assert {n["id"]: n["depth"] for n in lineage["nodes"]} == {
        "art-a": 0,
        "art-b": 1,
        "art-c": 2,
    }
    assert {"child_id": "art-a", "parent_id": "art-b"} in lineage["edges"]
    assert {"child_id": "art-b", "parent_id": "art-c"} in lineage["edges"]


async def test_lineage_diamond_shared_upstream(fake_store: FakeArtifactStore):
    """菱形血缘：共享上游只入节点一次，但两条消费边都保留"""
    fake_store.seed("art-d", sources=[])
    fake_store.seed("art-b", sources=["art-d"])
    fake_store.seed("art-c", sources=["art-d"])
    fake_store.seed("art-a", sources=["art-b", "art-c"])

    lineage = await get_lineage("art-a")
    assert lineage is not None
    node_ids = [n["id"] for n in lineage["nodes"]]
    assert node_ids.count("art-d") == 1  # 共享上游不重复入图
    assert {"child_id": "art-b", "parent_id": "art-d"} in lineage["edges"]
    assert {"child_id": "art-c", "parent_id": "art-d"} in lineage["edges"]


async def test_lineage_cycle_terminates(fake_store: FakeArtifactStore):
    """成环血缘（A→B→A）必须终止且不重复访问（非正向）"""
    fake_store.seed("art-b", sources=["art-a"])
    fake_store.seed("art-a", sources=["art-b"])

    lineage = await get_lineage("art-a")
    assert lineage is not None
    assert lineage["truncated"] is False  # 环被 visited 挡住，不算截断
    assert len(lineage["nodes"]) == 2
    assert lineage["edges"] == [{"child_id": "art-a", "parent_id": "art-b"}]


async def test_lineage_depth_limit_truncates(fake_store: FakeArtifactStore):
    """超过深度上限的长链被截断（边界）"""
    # 构造 root -> n1 -> n2 -> ... -> n12 共 13 层
    prev: str | None = None
    for i in range(12, 0, -1):
        node_id = f"art-n{i}"
        fake_store.seed(node_id, sources=[prev] if prev else [])
        prev = node_id
    fake_store.seed("art-root", sources=["art-n1"])

    lineage = await get_lineage("art-root")
    assert lineage is not None
    assert lineage["truncated"] is True
    assert lineage["depth_limit"] == MAX_LINEAGE_DEPTH
    assert all(n["depth"] <= MAX_LINEAGE_DEPTH for n in lineage["nodes"])
    # 链尾节点（超出深度）不应入图
    assert "art-n12" not in {n["id"] for n in lineage["nodes"]}


async def test_lineage_missing_upstream_silently_skipped(fake_store: FakeArtifactStore):
    """不存在的上游 id 静默跳过，不建悬空边（非正向）"""
    fake_store.seed("art-a", sources=["art-ghost"])

    lineage = await get_lineage("art-a")
    assert lineage is not None
    assert len(lineage["nodes"]) == 1  # 只有根节点
    assert lineage["edges"] == []
    assert lineage["truncated"] is False


# ---------- publish_and_notify ----------


async def test_publish_and_notify_swallows_errors(fake_store: FakeArtifactStore, monkeypatch: pytest.MonkeyPatch):
    """发布失败只记日志不抛出，不阻断会议终态（降级路径）"""

    async def boom(meeting_id: str, artifact_type: str) -> tuple[int, str | None]:
        raise RuntimeError("数据库写入失败")

    monkeypatch.setattr(artifact_dao, "next_version", boom)
    assert await publish_and_notify(_state()) is None


async def test_publish_and_notify_broadcasts_event(fake_store: FakeArtifactStore, monkeypatch: pytest.MonkeyPatch):
    """发布成功时广播 artifact.published 事件"""
    published_events: list[Any] = []

    async def fake_publish(event: Any) -> None:
        published_events.append(event)

    monkeypatch.setattr(bus, "publish", fake_publish)
    published = await publish_and_notify(_state())

    assert published is not None
    assert len(published_events) == 1
    event = published_events[0]
    assert event.type == "artifact.published"
    assert event.meeting_id == "mtg-pub-1"
    assert event.payload["artifact_id"] == published["id"]
    assert event.payload["type"] == "adr"
    assert event.payload["version"] == 1


async def test_publish_and_notify_no_event_when_no_artifact(
    fake_store: FakeArtifactStore, monkeypatch: pytest.MonkeyPatch
):
    """无产物可发布时不广播事件（边界）"""
    published_events: list[Any] = []

    async def fake_publish(event: Any) -> None:
        published_events.append(event)

    monkeypatch.setattr(bus, "publish", fake_publish)
    assert await publish_and_notify(_state(artifact=None)) is None
    assert published_events == []
