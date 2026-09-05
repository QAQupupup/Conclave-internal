"""议题 DAO 集成测试（ADR-017 Phase 2，容器内真实 PostgreSQL）。

覆盖：
- create/get 往返 + 非法 source 拒绝（D7 两条入口）
- FK 红线：引用不存在的项目必须抛错（非正向）
- list 过滤（项目/状态）+ 最新在上 + 分页
- update_issue_fields 白名单过滤（非正向：越权字段被忽略）
- transition_status 条件更新：命中/未命中（并发竞争语义，非正向）
- unbind_meeting：会议侧解绑置 NULL
- bulk_get_by_project 批量统计
- 多租户隔离（P8 红线，非正向）
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from app.dao import issue_dao, meeting_dao, project_dao
from app.tenants.context import set_system_tenant, set_tenant_id


def _slug(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


async def _ensure_tenant(tid: int) -> None:
    """预建真实租户行：issues 挂 fk_issues_tenant FK（ADR-017 Phase 2
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


def _mid(prefix: str) -> str:
    return f"mtg-{prefix}-{uuid.uuid4().hex[:8]}"


async def _seed_project(prefix: str) -> dict:
    """建一个测试项目并返回其 dict。"""
    return await project_dao.create_project(slug=_slug(prefix), name=f"{prefix} 项目")


async def _seed_meeting(meeting_id: str) -> None:
    await meeting_dao.save_meeting(
        meeting_id=meeting_id,
        topic=f"议题 DAO 测试会议 {meeting_id}",
        status="done",
        stage="produce",
        created_at=datetime.now(timezone.utc),
        payload={},
    )


# ---------- 创建与往返 ----------


async def test_create_and_get_roundtrip():
    """创建后取回：全字段往返一致（source=user 入口）"""
    project = await _seed_project("roundtrip")
    row = await issue_dao.create_issue(
        project_id=project["id"],
        title="往返议题",
        body="议题正文",
        source="user",
        priority=80,
        created_by="admin",
    )

    got = await issue_dao.get_issue(row["id"])
    assert got is not None
    assert got["project_id"] == project["id"]
    assert got["title"] == "往返议题"
    assert got["body"] == "议题正文"
    assert got["source"] == "user"
    assert got["status"] == "open"  # 初始状态
    assert got["priority"] == 80
    assert got["assigned_meeting_id"] is None
    assert got["resolution_artifact_id"] is None
    assert got["created_by"] == "admin"
    assert got["created_at"]


async def test_create_invalid_source_raises():
    """非法入口 → ValueError（非正向；D7 只允许 user|meeting）"""
    project = await _seed_project("badsrc")
    with pytest.raises(ValueError, match="非法议题入口"):
        await issue_dao.create_issue(project_id=project["id"], title="x", source="auto")


async def test_create_missing_project_raises():
    """FK 红线：引用不存在的项目必须抛错而非静默写入（非正向）"""
    with pytest.raises(IntegrityError):
        await issue_dao.create_issue(project_id="proj-no-such-project", title="x", source="user")


async def test_get_missing_returns_none():
    """不存在的 id → None（边界）"""
    assert await issue_dao.get_issue("issue-does-not-exist") is None


# ---------- 列表过滤与排序 ----------


async def test_list_filters_project_status_newest_first():
    """列表：项目/状态过滤 + 最新在上 + 分页 total 稳定"""
    project = await _seed_project("list")
    i1 = await issue_dao.create_issue(project_id=project["id"], title="先建", source="user")
    i2 = await issue_dao.create_issue(project_id=project["id"], title="后建", source="user")
    await issue_dao.transition_status(i2["id"], expected_statuses=("open",), new_status="scheduled")

    listed = await issue_dao.list_issues(project_id=project["id"])
    assert listed["total"] == 2
    ids = [i["id"] for i in listed["items"]]
    assert ids.index(i2["id"]) < ids.index(i1["id"])  # 最新在上

    only_scheduled = await issue_dao.list_issues(project_id=project["id"], status="scheduled")
    assert only_scheduled["total"] == 1
    assert only_scheduled["items"][0]["id"] == i2["id"]

    paged = await issue_dao.list_issues(project_id=project["id"], limit=1)
    assert paged["total"] == 2
    assert len(paged["items"]) == 1


# ---------- 更新白名单 ----------


async def test_update_fields_whitelist():
    """更新只接受白名单字段：越权改 project_id/tenant_id 被忽略（非正向）"""
    project = await _seed_project("upd")
    issue = await issue_dao.create_issue(project_id=project["id"], title="旧标题", source="user")
    updated = await issue_dao.update_issue_fields(
        issue["id"],
        {"title": "新标题", "priority": 99, "project_id": "hacked", "tenant_id": 99999, "created_by": "hacker"},
    )
    assert updated is not None
    assert updated["title"] == "新标题"
    assert updated["priority"] == 99
    assert updated["project_id"] == project["id"]  # 未被篡改
    assert updated["tenant_id"] == issue["tenant_id"]  # 未被篡改

    assert await issue_dao.update_issue_fields("issue-no-such", {"title": "x"}) is None


# ---------- 条件状态流转（原子性） ----------


async def test_transition_status_hit_and_miss():
    """条件更新：期望状态命中则流转；未命中返回 None（并发竞争语义，非正向）"""
    project = await _seed_project("trans")
    issue = await issue_dao.create_issue(project_id=project["id"], title="流转议题", source="user")

    # 命中：open → scheduled，附带 extra_fields
    updated = await issue_dao.transition_status(
        issue["id"],
        expected_statuses=("open",),
        new_status="scheduled",
        extra_fields={"priority": 77},
    )
    assert updated is not None
    assert updated["status"] == "scheduled"
    assert updated["priority"] == 77

    # 未命中：当前是 scheduled，期望 (in_progress,) → None 且状态不变
    missed = await issue_dao.transition_status(issue["id"], expected_statuses=("in_progress",), new_status="resolved")
    assert missed is None
    got = await issue_dao.get_issue(issue["id"])
    assert got is not None and got["status"] == "scheduled"

    # extra_fields 白名单过滤：越权字段被忽略
    filtered = await issue_dao.transition_status(
        issue["id"],
        expected_statuses=("scheduled",),
        new_status="in_progress",
        extra_fields={"tenant_id": 99999},
    )
    assert filtered is not None
    assert filtered["tenant_id"] == issue["tenant_id"]

    # 不存在的议题 → None
    assert (
        await issue_dao.transition_status("issue-no-such", expected_statuses=("open",), new_status="scheduled") is None
    )


# ---------- 会议绑定/解绑 ----------


async def test_bind_and_unbind_meeting():
    """绑定会议写入 assigned_meeting_id；unbind_meeting 置 NULL（会议删除语义）"""
    project = await _seed_project("bind")
    issue = await issue_dao.create_issue(project_id=project["id"], title="绑定议题", source="user")
    mid = _mid("issue-bind")
    await _seed_meeting(mid)

    bound = await issue_dao.transition_status(
        issue["id"],
        expected_statuses=("open", "scheduled"),
        new_status="in_progress",
        extra_fields={"assigned_meeting_id": mid},
    )
    assert bound is not None
    assert bound["assigned_meeting_id"] == mid

    await issue_dao.unbind_meeting(mid)
    got = await issue_dao.get_issue(issue["id"])
    assert got is not None
    assert got["assigned_meeting_id"] is None  # 解绑置 NULL
    assert got["status"] == "in_progress"  # 解绑不改状态（服务层语义）


# ---------- 批量统计 ----------


async def test_bulk_get_by_project():
    """bulk_get_by_project：按项目统计议题数；空列表短路返回 {}"""
    p1 = await _seed_project("bulk-a")
    p2 = await _seed_project("bulk-b")
    await issue_dao.create_issue(project_id=p1["id"], title="a1", source="user")
    await issue_dao.create_issue(project_id=p1["id"], title="a2", source="user")
    await issue_dao.create_issue(project_id=p2["id"], title="b1", source="meeting")

    counts = await issue_dao.bulk_get_by_project([p1["id"], p2["id"]])
    assert counts[p1["id"]] == 2
    assert counts[p2["id"]] == 1
    assert await issue_dao.bulk_get_by_project([]) == {}


# ---------- 删除 ----------


async def test_delete_issue():
    """删除议题：存在 → True；不存在 → False（边界）"""
    project = await _seed_project("del")
    issue = await issue_dao.create_issue(project_id=project["id"], title="待删", source="user")
    assert await issue_dao.delete_issue(issue["id"]) is True
    assert await issue_dao.get_issue(issue["id"]) is None
    assert await issue_dao.delete_issue(issue["id"]) is False


# ---------- 多租户隔离（P8 红线） ----------


async def test_tenant_isolation_cross_tenant_invisible():
    """跨租户读/列表/流转/删除全部不可见（非正向）"""
    await _ensure_tenant(961)
    await _ensure_tenant(962)
    set_system_tenant(False)
    set_tenant_id(961)
    try:
        project = await project_dao.create_project(slug=_slug("tenant"), name="租户 961 项目")
        issue = await issue_dao.create_issue(project_id=project["id"], title="租户议题", source="user")
        assert issue["tenant_id"] == 961
        assert (await issue_dao.get_issue(issue["id"])) is not None

        set_tenant_id(962)
        assert await issue_dao.get_issue(issue["id"]) is None
        listed = await issue_dao.list_issues(project_id=project["id"])
        assert listed["total"] == 0
        # 跨租户流转/更新/删除全部落空
        assert (
            await issue_dao.transition_status(issue["id"], expected_statuses=("open",), new_status="scheduled") is None
        )
        assert await issue_dao.update_issue_fields(issue["id"], {"title": "越权"}) is None
        assert await issue_dao.delete_issue(issue["id"]) is False

        set_tenant_id(961)
        assert (await issue_dao.get_issue(issue["id"])) is not None
    finally:
        set_tenant_id(None)
        set_system_tenant(True)
