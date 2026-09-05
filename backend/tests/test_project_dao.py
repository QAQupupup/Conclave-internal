"""项目 DAO 集成测试（ADR-017 Phase 2，容器内真实 PostgreSQL）。

覆盖：
- create/get/by_slug/list/update/delete CRUD 往返
- slug 租户内唯一约束 → IntegrityError（非正向）
- 更新白名单过滤：越权字段 id/tenant_id 被忽略（非正向）
- 删除项目级联删除议题（FK CASCADE）
- count_issues 状态分组统计
- 多租户隔离：跨租户读/改/删全部不可见（P8 红线，非正向）
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from app.dao import issue_dao, project_dao
from app.tenants.context import set_system_tenant, set_tenant_id


def _slug(prefix: str) -> str:
    """生成唯一 slug（避免并行 worker 内用例间冲突）。"""
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


async def _ensure_tenant(tid: int) -> None:
    """预建真实租户行：projects 挂 fk_projects_tenant FK（ADR-017 Phase 2
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


# ---------- CRUD 往返 ----------


async def test_create_and_get_roundtrip():
    """创建后按 id / slug 取回：全字段往返一致"""
    slug = _slug("roundtrip")
    row = await project_dao.create_project(
        slug=slug,
        name="往返项目",
        repo_url="https://example.com/demo/repo.git",
        default_branch="master",
        description="用于往返测试",
        created_by="admin",
    )

    got = await project_dao.get_project(row["id"])
    assert got is not None
    assert got["id"] == row["id"]
    assert got["slug"] == slug
    assert got["name"] == "往返项目"
    assert got["repo_url"] == "https://example.com/demo/repo.git"
    assert got["default_branch"] == "master"
    assert got["description"] == "用于往返测试"
    assert got["created_by"] == "admin"
    assert got["created_at"]  # CreatedAtMixin 自动填充

    by_slug = await project_dao.get_project_by_slug(slug)
    assert by_slug is not None
    assert by_slug["id"] == row["id"]


async def test_create_default_branch_defaults_to_main():
    """未指定 default_branch 时落库默认 main（边界）"""
    row = await project_dao.create_project(slug=_slug("defbranch"), name="默认分支项目")
    assert row["default_branch"] == "main"
    assert row["repo_url"] is None  # 纯文档型项目允许无仓库


async def test_get_missing_returns_none():
    """不存在的 id / slug → None（边界）"""
    assert await project_dao.get_project("proj-does-not-exist") is None
    assert await project_dao.get_project_by_slug("slug-does-not-exist") is None


async def test_slug_conflict_raises():
    """同租户内 slug 重复 → IntegrityError（非正向）"""
    slug = _slug("conflict")
    await _ensure_tenant(950)
    set_system_tenant(False)
    set_tenant_id(950)
    try:
        await project_dao.create_project(slug=slug, name="先创建的")
        with pytest.raises(IntegrityError):
            await project_dao.create_project(slug=slug, name="后创建的")
    finally:
        set_tenant_id(None)
        set_system_tenant(True)


# ---------- 列表与分页 ----------


async def test_list_newest_first_and_pagination():
    """列表：最新在上 + 分页 total 不随 limit 变化（UI 红线）"""
    p1 = await project_dao.create_project(slug=_slug("list-a"), name="先建")
    p2 = await project_dao.create_project(slug=_slug("list-b"), name="后建")

    listed = await project_dao.list_projects(limit=200, offset=0)
    ids = [p["id"] for p in listed["items"]]
    assert p1["id"] in ids and p2["id"] in ids
    # 最新在上：后建的 p2 排在 p1 之前
    assert ids.index(p2["id"]) < ids.index(p1["id"])

    paged = await project_dao.list_projects(limit=1, offset=0)
    assert paged["total"] == listed["total"]
    assert len(paged["items"]) == 1


# ---------- 更新白名单 ----------


async def test_update_whitelist_filters_forbidden_fields():
    """更新只接受白名单字段：越权改 id/tenant_id 被静默过滤（非正向）"""
    row = await project_dao.create_project(slug=_slug("upd"), name="旧名")
    updated = await project_dao.update_project(
        row["id"],
        {"name": "新名", "id": "hacked-id", "tenant_id": 99999, "created_by": "hacker"},
    )
    assert updated is not None
    assert updated["name"] == "新名"
    assert updated["id"] == row["id"]  # id 未被篡改
    assert updated["tenant_id"] == row["tenant_id"]  # tenant_id 未被篡改
    assert updated["created_by"] == row["created_by"]  # created_by 不在白名单


async def test_update_missing_returns_none():
    """更新不存在的项目 → None（边界）"""
    assert await project_dao.update_project("proj-no-such", {"name": "x"}) is None


# ---------- 删除与级联 ----------


async def test_delete_cascades_issues():
    """删除项目：旗下议题级联删除（FK CASCADE 语义）"""
    project = await project_dao.create_project(slug=_slug("del"), name="待删项目")
    issue = await issue_dao.create_issue(project_id=project["id"], title="陪葬议题", source="user")

    assert await project_dao.delete_project(project["id"]) is True
    assert await project_dao.get_project(project["id"]) is None
    assert await issue_dao.get_issue(issue["id"]) is None  # 级联删除


async def test_delete_missing_returns_false():
    """删除不存在的项目 → False（边界）"""
    assert await project_dao.delete_project("proj-no-such") is False


# ---------- 议题统计 ----------


async def test_count_issues_by_status():
    """count_issues：总数 + 按状态分组"""
    project = await project_dao.create_project(slug=_slug("stats"), name="统计项目")
    await issue_dao.create_issue(project_id=project["id"], title="议题一", source="user")
    i2 = await issue_dao.create_issue(project_id=project["id"], title="议题二", source="user")
    # 流转一条到 scheduled，制造状态分组
    await issue_dao.transition_status(i2["id"], expected_statuses=("open",), new_status="scheduled")

    stats = await project_dao.count_issues(project["id"])
    assert stats["total"] == 2
    assert stats["open"] == 1
    assert stats["scheduled"] == 1


# ---------- 多租户隔离（P8 红线） ----------


async def test_tenant_isolation_cross_tenant_invisible():
    """跨租户读/改/删全部不可见（非正向）"""
    slug = _slug("tenant")
    await _ensure_tenant(951)
    await _ensure_tenant(952)
    set_system_tenant(False)
    set_tenant_id(951)
    try:
        row = await project_dao.create_project(slug=slug, name="租户 951 的项目")
        assert row["tenant_id"] == 951
        assert (await project_dao.get_project(row["id"])) is not None

        # 切换到租户 952：读取/按 slug 查/列表/更新/删除全部不可见
        set_tenant_id(952)
        assert await project_dao.get_project(row["id"]) is None
        assert await project_dao.get_project_by_slug(slug) is None
        listed = await project_dao.list_projects(limit=200)
        assert row["id"] not in [p["id"] for p in listed["items"]]
        assert await project_dao.update_project(row["id"], {"name": "越权改名"}) is None
        assert await project_dao.delete_project(row["id"]) is False

        # 切回 951 恢复可见
        set_tenant_id(951)
        assert (await project_dao.get_project(row["id"])) is not None
    finally:
        set_tenant_id(None)
        set_system_tenant(True)
