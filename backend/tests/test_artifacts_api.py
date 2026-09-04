"""产物查询 API 契约测试（ADR-017 Phase 1 / T1.11）。

覆盖：
- GET /artifacts：空结果 / 会议与类型过滤 / 分页参数校验（含非正向 422）
- GET /artifacts/{id}：字段契约 / 不存在 404（非正向）
- GET /artifacts/{id}/lineage：血缘结构 / 不存在 404（非正向）
- POST /meetings 携带 source_artifact_ids：有效+无效混用时静默剔除不阻断创建

种子数据直接走 DAO（asyncio.run），会议行经 POST /meetings 创建（满足 FK）。
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.dao import artifact_dao


def _create_meeting(client, topic: str = "产物 API 测试会议", deliverable_type: str = "adr") -> str:
    resp = client.post("/meetings", json={"topic": topic, "deliverable_type": deliverable_type})
    assert resp.status_code == 200, resp.text
    return resp.json()["meeting_id"]


def _seed_artifact(meeting_id: str, **overrides: Any) -> dict[str, Any]:
    """同步包装 DAO 发布（测试用种子数据）。"""
    kwargs: dict[str, Any] = {
        "meeting_id": meeting_id,
        "artifact_type": "adr",
        "version": 1,
        "title": "种子产物",
        "summary": "种子摘要",
        "content": {"title": "种子产物"},
    }
    kwargs.update(overrides)

    async def _do() -> dict[str, Any]:
        return await artifact_dao.publish_artifact(**kwargs)

    return asyncio.run(_do())


# ---------- 列表 ----------


def test_list_artifacts_empty_for_unused_meeting(client):
    """无人引用的 meeting_id 过滤结果为空（边界）"""
    resp = client.get("/artifacts", params={"meeting_id": "mtg-nothing-here"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["items"] == []
    assert body["total"] == 0


def test_list_artifacts_filter_by_meeting_and_type(client):
    """会议 + 类型组合过滤命中种子数据"""
    mid = _create_meeting(client, topic="产物列表过滤专题")
    adr_row = _seed_artifact(mid, artifact_type="adr", title="ADR 产物")
    fea_row = _seed_artifact(mid, artifact_type="feasibility_report", title="可行性产物")

    resp = client.get("/artifacts", params={"meeting_id": mid})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    assert {i["id"] for i in body["items"]} == {adr_row["id"], fea_row["id"]}

    resp_adr = client.get("/artifacts", params={"meeting_id": mid, "type": "adr"})
    body_adr = resp_adr.json()
    assert body_adr["total"] == 1
    assert body_adr["items"][0]["id"] == adr_row["id"]


def test_list_artifacts_limit_validation_rejects_zero(client):
    """limit=0 违反 ge=1 约束 → 422（非正向）"""
    resp = client.get("/artifacts", params={"limit": 0})
    assert resp.status_code == 422


# ---------- 单条详情 ----------


def test_get_artifact_detail_contract(client):
    """单条产物字段契约"""
    mid = _create_meeting(client, topic="产物详情契约专题")
    row = _seed_artifact(mid, title="详情产物", summary="详情摘要")

    resp = client.get(f"/artifacts/{row['id']}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == row["id"]
    assert body["meeting_id"] == mid
    assert body["type"] == "adr"
    assert body["title"] == "详情产物"
    assert body["summary"] == "详情摘要"
    assert body["version"] == 1
    assert body["source_artifact_ids"] == []
    assert body["content"] == {"title": "种子产物"}


def test_get_artifact_not_found(client):
    """不存在的产物 → 404（非正向）"""
    resp = client.get("/artifacts/art-does-not-exist")
    assert resp.status_code == 404


# ---------- 血缘 ----------


def test_lineage_returns_upstream_chain(client):
    """下游产物血缘包含上游节点与消费边"""
    mid_up = _create_meeting(client, topic="血缘上游会议")
    mid_down = _create_meeting(client, topic="血缘下游会议")
    upstream = _seed_artifact(mid_up, title="上游可行性报告", artifact_type="feasibility_report")
    downstream = _seed_artifact(mid_down, title="下游 ADR", artifact_type="adr", source_artifact_ids=[upstream["id"]])

    resp = client.get(f"/artifacts/{downstream['id']}/lineage")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["root_id"] == downstream["id"]
    assert body["truncated"] is False
    assert {n["id"]: n["depth"] for n in body["nodes"]} == {
        downstream["id"]: 0,
        upstream["id"]: 1,
    }
    assert {"child_id": downstream["id"], "parent_id": upstream["id"]} in body["edges"]


def test_lineage_not_found(client):
    """不存在产物的血缘查询 → 404（非正向）"""
    resp = client.get("/artifacts/art-does-not-exist/lineage")
    assert resp.status_code == 404


# ---------- 会议创建引用上游产物 ----------


def test_create_meeting_with_source_artifacts(client):
    """source_artifact_ids 有效+无效混用：创建成功（无效 id 静默剔除）"""
    mid_up = _create_meeting(client, topic="被引用的上游会议")
    upstream = _seed_artifact(mid_up, title="被引用的产物")

    resp = client.post(
        "/meetings",
        json={
            "topic": "引用上游产物的新会议",
            "deliverable_type": "adr",
            "source_artifact_ids": [upstream["id"], "art-ghost-id"],
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["meeting_id"]


def test_create_meeting_accepts_new_deliverable_types(client):
    """三种新产出类型均可作为会议产出类型（T1.8 模板注册）"""
    for dt in ("feasibility_report", "adr", "test_suite"):
        resp = client.post("/meetings", json={"topic": f"新产出类型 {dt}", "deliverable_type": dt})
        assert resp.status_code == 200, f"{dt}: {resp.text}"
        assert resp.json()["meeting_id"]
