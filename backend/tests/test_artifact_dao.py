"""产物 DAO 集成测试（ADR-017 Phase 1，容器内真实 PostgreSQL）。

覆盖：
- publish_artifact 幂等重放（ON CONFLICT DO UPDATE，D2）
- next_version 版本链递增与 parent 指向
- get_artifact / get_artifacts_by_ids / list_artifacts 查询契约
- 多租户隔离：跨租户读取不可见（P8 红线，非正向）
- 不存在的 id 返回 None / 空（边界）

artifacts.meeting_id 有 FK 约束（CASCADE），故每个用例先 save_meeting 建行。
租户上下文由 _reset_state fixture 预设为系统租户（不过滤），
租户隔离用例内显式切换 tenant_id 并在 finally 中恢复。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from app.dao import artifact_dao, meeting_dao
from app.tenants.context import set_system_tenant, set_tenant_id


def _mid(prefix: str) -> str:
    """生成唯一会议 ID（避免并行 worker 内用例间串数据）。"""
    return f"mtg-{prefix}-{uuid.uuid4().hex[:8]}"


async def _seed_meeting(meeting_id: str) -> None:
    await meeting_dao.save_meeting(
        meeting_id=meeting_id,
        topic=f"产物 DAO 测试会议 {meeting_id}",
        status="done",
        stage="produce",
        created_at=datetime.now(timezone.utc),
        payload={},
    )


async def _ensure_tenant(tid: int) -> None:
    """预建真实租户行：artifacts 挂 fk_artifacts_tenant FK（ADR-017 Phase 2
    纳入 _BUSINESS_TABLES 兜底），tenant_id 必须引用已存在的租户。"""
    from sqlalchemy import text

    from app.db.engine import async_session_factory

    async with async_session_factory() as session:
        await session.execute(
            text(
                "INSERT INTO tenants(id, name, slug, plan, owner_id, description, is_active, settings) "
                "VALUES(:id, :name, :slug, 'free', 1, '', TRUE, '{}'::jsonb) "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {"id": tid, "name": f"测试租户 {tid}", "slug": f"test-tenant-{tid}"},
        )
        await session.commit()


# ---------- 幂等发布与往返 ----------


async def test_publish_and_get_roundtrip():
    """发布后按 id 取回：全字段往返一致"""
    mid = _mid("roundtrip")
    await _seed_meeting(mid)
    content = {"title": "决策记录", "verdict": "采纳方案 A"}

    row = await artifact_dao.publish_artifact(
        meeting_id=mid,
        artifact_type="adr",
        version=1,
        title="决策记录",
        summary="采纳方案 A",
        content=content,
        source_artifact_ids=["art-up-1", "art-up-2"],
        created_by="admin",
    )

    got = await artifact_dao.get_artifact(row["id"])
    assert got is not None
    assert got["id"] == row["id"]
    assert got["meeting_id"] == mid
    assert got["type"] == "adr"
    assert got["version"] == 1
    assert got["title"] == "决策记录"
    assert got["summary"] == "采纳方案 A"
    assert got["content"] == content
    assert got["content_ref"] is None
    assert got["source_artifact_ids"] == ["art-up-1", "art-up-2"]
    assert got["created_by"] == "admin"
    assert got["created_at"]  # CreatedAtMixin 自动填充


async def test_publish_idempotent_replay():
    """同 (meeting, type, version) 重复发布：更新内容而非新增行（幂等重放）"""
    mid = _mid("idem")
    await _seed_meeting(mid)

    r1 = await artifact_dao.publish_artifact(meeting_id=mid, artifact_type="adr", version=1, title="初版", summary="s1")
    r2 = await artifact_dao.publish_artifact(
        meeting_id=mid, artifact_type="adr", version=1, title="重放更新", summary="s2"
    )

    assert r1["id"] == r2["id"]  # 命中唯一约束后更新同一行
    assert r2["title"] == "重放更新"
    assert r2["summary"] == "s2"

    listed = await artifact_dao.list_artifacts(meeting_id=mid)
    assert listed["total"] == 1


async def test_publish_missing_meeting_raises():
    """FK 红线：引用不存在的会议必须抛错而非静默写入（非正向）"""
    with pytest.raises(IntegrityError):
        await artifact_dao.publish_artifact(
            meeting_id="mtg-no-such-meeting-xyz",
            artifact_type="adr",
            version=1,
        )


# ---------- 版本链 ----------


async def test_next_version_chain():
    """next_version：无历史 → (1, None)；每发布一版递增并指向最新版 id"""
    mid = _mid("ver")
    await _seed_meeting(mid)

    assert await artifact_dao.next_version(mid, "adr") == (1, None)

    r1 = await artifact_dao.publish_artifact(meeting_id=mid, artifact_type="adr", version=1)
    assert await artifact_dao.next_version(mid, "adr") == (2, r1["id"])

    r2 = await artifact_dao.publish_artifact(meeting_id=mid, artifact_type="adr", version=2, parent_id=r1["id"])
    assert await artifact_dao.next_version(mid, "adr") == (3, r2["id"])

    # 同会议不同类型互不干扰
    assert await artifact_dao.next_version(mid, "feasibility_report") == (1, None)


# ---------- 查询契约 ----------


async def test_get_artifact_missing_returns_none():
    """不存在的 id → None（边界）"""
    assert await artifact_dao.get_artifact("art-does-not-exist") is None


async def test_get_artifacts_by_ids_skips_missing():
    """批量获取：不存在的 id 静默剔除（非正向）"""
    mid = _mid("batch")
    await _seed_meeting(mid)
    r1 = await artifact_dao.publish_artifact(meeting_id=mid, artifact_type="adr", version=1)
    r2 = await artifact_dao.publish_artifact(meeting_id=mid, artifact_type="adr", version=2)

    found = await artifact_dao.get_artifacts_by_ids([r1["id"], "art-ghost", r2["id"]])
    assert {a["id"] for a in found} == {r1["id"], r2["id"]}

    assert await artifact_dao.get_artifacts_by_ids([]) == []


async def test_list_artifacts_filters_and_order():
    """列表：按会议/类型过滤、总数正确、最新在上"""
    mid_a = _mid("list-a")
    mid_b = _mid("list-b")
    await _seed_meeting(mid_a)
    await _seed_meeting(mid_b)

    r1 = await artifact_dao.publish_artifact(meeting_id=mid_a, artifact_type="adr", version=1, title="先")
    r2 = await artifact_dao.publish_artifact(meeting_id=mid_a, artifact_type="adr", version=2, title="后")
    r3 = await artifact_dao.publish_artifact(
        meeting_id=mid_a, artifact_type="feasibility_report", version=1, title="可行性"
    )
    r4 = await artifact_dao.publish_artifact(meeting_id=mid_b, artifact_type="adr", version=1, title="他会议")

    listed_a = await artifact_dao.list_artifacts(meeting_id=mid_a)
    assert listed_a["total"] == 3
    assert {i["id"] for i in listed_a["items"]} == {r1["id"], r2["id"], r3["id"]}
    # 最新在上：后发布的 r2 排在 r1 之前
    ids_a = [i["id"] for i in listed_a["items"]]
    assert ids_a.index(r2["id"]) < ids_a.index(r1["id"])

    listed_adr = await artifact_dao.list_artifacts(meeting_id=mid_a, artifact_type="adr")
    assert listed_adr["total"] == 2

    listed_b = await artifact_dao.list_artifacts(meeting_id=mid_b)
    assert [i["id"] for i in listed_b["items"]] == [r4["id"]]

    # 分页：limit=1 只取一条但 total 不变
    paged = await artifact_dao.list_artifacts(meeting_id=mid_a, limit=1, offset=0)
    assert paged["total"] == 3
    assert len(paged["items"]) == 1


# ---------- 多租户隔离（P8 红线） ----------


async def test_tenant_isolation_cross_tenant_invisible():
    """跨租户读取不可见：get/批量/列表三条路径全部隔离（非正向）"""
    mid = _mid("tenant")
    await _seed_meeting(mid)
    await _ensure_tenant(901)
    await _ensure_tenant(902)

    set_system_tenant(False)
    set_tenant_id(901)
    try:
        row = await artifact_dao.publish_artifact(
            meeting_id=mid, artifact_type="adr", version=1, title="租户 901 的产物"
        )
        assert row["tenant_id"] == 901
        # 同租户可见
        assert (await artifact_dao.get_artifact(row["id"])) is not None

        # 切换到租户 902：三条读取路径全部不可见
        set_tenant_id(902)
        assert await artifact_dao.get_artifact(row["id"]) is None
        assert await artifact_dao.get_artifacts_by_ids([row["id"]]) == []
        listed = await artifact_dao.list_artifacts(meeting_id=mid)
        assert listed["total"] == 0

        # 切回 901 恢复可见
        set_tenant_id(901)
        assert (await artifact_dao.get_artifact(row["id"])) is not None
    finally:
        set_tenant_id(None)
        set_system_tenant(True)
