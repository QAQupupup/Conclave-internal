"""项目与议题池 API 测试（ADR-017 Phase 2，/api 前缀迁移后的端点面回归）。

覆盖端点：
- /api/projects：创建（slug 冲突 409）、列表（附 issue_total）、详情（issue_stats）、
  PATCH（白名单更新 / 空请求 400）、DELETE（议题级联删）
- /api/projects/{id}/issues：入池（source=meeting 必须挂 source_meeting_id）、状态过滤
- /api/issues/{id}：单条（不存在 404）、PATCH 状态机（非法流转 409、闭环凭证红线）、DELETE

测试模式下 middleware 自动设置 uid=1（admin 用户），lifespan 启动时自动关联默认租户。
每个测试使用唯一 slug/标题避免测试间数据冲突。
client fixture 复用 backend/conftest.py 全局定义（带 lifespan 初始化）。
"""

from __future__ import annotations

import asyncio
import uuid

from fastapi.testclient import TestClient

from app.dao import artifact_dao


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _create_meeting(client: TestClient, topic: str = "议题闭环凭证测试会议") -> str:
    """经 POST /meetings 创建会议（满足产物 meeting_id FK），返回 meeting_id。"""
    resp = client.post("/meetings", json={"topic": topic, "deliverable_type": "adr"})
    assert resp.status_code == 200, resp.text
    return resp.json()["meeting_id"]


def _seed_artifact(meeting_id: str) -> dict:
    """同步包装 DAO 发布产物（测试用种子数据，同 test_artifacts_api.py 模式）。"""

    async def _do() -> dict:
        return await artifact_dao.publish_artifact(
            meeting_id=meeting_id,
            artifact_type="adr",
            version=1,
            title="闭环凭证",
            summary="议题闭环测试凭证",
            content={"title": "闭环凭证"},
        )

    return asyncio.run(_do())


def _create_project(client: TestClient, slug: str | None = None) -> dict:
    """辅助：创建一个项目并返回响应体。"""
    slug = slug or _unique("proj")
    resp = client.post("/api/projects", json={"slug": slug, "name": f"项目 {slug}"})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_issue(client: TestClient, project_id: str, title: str | None = None, **extra) -> dict:
    """辅助：在项目下入池一条议题并返回响应体。"""
    payload = {"title": title or _unique("议题"), **extra}
    resp = client.post(f"/api/projects/{project_id}/issues", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


class TestProjectsAPI:
    """项目端点（/api/projects）。"""

    def test_create_project_returns_fields(self, client):
        """POST /api/projects → 201，字段回显且默认分支为 main。"""
        slug = _unique("echo")
        resp = client.post(
            "/api/projects",
            json={"slug": slug, "name": "回显项目", "repo_url": "https://git.example.com/x.git"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["slug"] == slug
        assert data["name"] == "回显项目"
        assert data["default_branch"] == "main"
        assert data["repo_url"] == "https://git.example.com/x.git"
        assert data["issue_total"] is None or data.get("issue_total") in (None, 0)

    def test_create_project_duplicate_slug_409(self, client):
        """同一租户内重复 slug → 409（非正向）。"""
        slug = _unique("dup")
        client.post("/api/projects", json={"slug": slug, "name": "A"})
        resp = client.post("/api/projects", json={"slug": slug, "name": "B"})
        assert resp.status_code == 409

    def test_list_projects_contains_created_with_issue_total(self, client):
        """GET /api/projects 包含新建项目，且议题计数随入池增长。"""
        project = _create_project(client)
        _create_issue(client, project["id"])
        _create_issue(client, project["id"])

        resp = client.get("/api/projects", params={"limit": 200})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        match = next((p for p in data["items"] if p["id"] == project["id"]), None)
        assert match is not None
        assert match["issue_total"] == 2

    def test_project_detail_issue_stats(self, client):
        """GET /api/projects/{id} 返回议题状态分组统计。"""
        project = _create_project(client)
        _create_issue(client, project["id"])

        resp = client.get(f"/api/projects/{project['id']}")
        assert resp.status_code == 200
        stats = resp.json()["issue_stats"]
        assert stats["total"] == 1
        assert stats["open"] == 1

    def test_project_detail_not_found_404(self, client):
        """不存在的项目 → 404（非正向）。"""
        resp = client.get(f"/api/projects/{uuid.uuid4()}")
        assert resp.status_code == 404

    def test_update_project_whitelist_fields(self, client):
        """PATCH /api/projects/{id} 只更新传入字段。"""
        project = _create_project(client)
        resp = client.patch(f"/api/projects/{project['id']}", json={"name": "改名后", "default_branch": "dev"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "改名后"
        assert data["default_branch"] == "dev"
        assert data["slug"] == project["slug"]  # 未传入字段不变

    def test_update_project_empty_body_400(self, client):
        """PATCH 不带任何字段 → 400（非正向）。"""
        project = _create_project(client)
        resp = client.patch(f"/api/projects/{project['id']}", json={})
        assert resp.status_code == 400

    def test_delete_project_cascades_issues(self, client):
        """DELETE 项目 → 议题级联删除，议题再查 → 404（非正向）。"""
        project = _create_project(client)
        issue = _create_issue(client, project["id"])

        resp = client.delete(f"/api/projects/{project['id']}")
        assert resp.status_code == 200
        assert resp.json()["deleted"] == project["id"]

        assert client.get(f"/api/projects/{project['id']}").status_code == 404
        assert client.get(f"/api/issues/{issue['id']}").status_code == 404


class TestIssuesAPI:
    """议题端点（/api/projects/{id}/issues 入池 + /api/issues/{id} 平铺）。"""

    def test_create_issue_defaults(self, client):
        """入池默认：source=user、status=open、priority=50。"""
        project = _create_project(client)
        issue = _create_issue(client, project["id"], title="默认值议题")
        assert issue["title"] == "默认值议题"
        assert issue["source"] == "user"
        assert issue["status"] == "open"
        assert issue["priority"] == 50
        assert issue["project_id"] == project["id"]

    def test_create_issue_meeting_source_requires_meeting_id(self, client):
        """source=meeting 缺 source_meeting_id → 400（ADR-017 D7，非正向）。"""
        project = _create_project(client)
        resp = client.post(
            f"/api/projects/{project['id']}/issues",
            json={"title": "会议候选", "source": "meeting"},
        )
        assert resp.status_code == 400

    def test_create_issue_unknown_project_404(self, client):
        """向不存在的项目入池 → 404（非正向）。"""
        resp = client.post(f"/api/projects/{uuid.uuid4()}/issues", json={"title": "孤儿"})
        assert resp.status_code == 404

    def test_list_project_issues_filter_by_status(self, client):
        """GET /api/projects/{id}/issues 支持状态过滤（最新在上）。"""
        project = _create_project(client)
        kept = _create_issue(client, project["id"], title="保留-open")
        moved = _create_issue(client, project["id"], title="流转-scheduled")
        assert client.patch(f"/api/issues/{moved['id']}", json={"status": "scheduled"}).status_code == 200

        resp = client.get(f"/api/projects/{project['id']}/issues", params={"status": "open"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["id"] == kept["id"]

    def test_get_issue_not_found_404(self, client):
        """GET /api/issues/{id} 不存在 → 404（非正向）。"""
        resp = client.get(f"/api/issues/{uuid.uuid4()}")
        assert resp.status_code == 404

    def test_issue_transition_open_to_scheduled(self, client):
        """合法流转 open → scheduled → 200。"""
        project = _create_project(client)
        issue = _create_issue(client, project["id"])
        resp = client.patch(f"/api/issues/{issue['id']}", json={"status": "scheduled"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "scheduled"

    def test_issue_illegal_transition_409(self, client):
        """非法流转 open → resolved → 409（状态机红线，非正向）。"""
        project = _create_project(client)
        issue = _create_issue(client, project["id"])
        resp = client.patch(f"/api/issues/{issue['id']}", json={"status": "resolved"})
        assert resp.status_code == 409

    def test_issue_resolve_requires_artifact(self, client):
        """in_progress → resolved 缺闭环凭证 → 409；补凭证后 → 200（闭环红线）。"""
        project = _create_project(client)
        issue = _create_issue(client, project["id"])
        assert client.patch(f"/api/issues/{issue['id']}", json={"status": "in_progress"}).status_code == 200

        resp = client.patch(f"/api/issues/{issue['id']}", json={"status": "resolved"})
        assert resp.status_code == 409  # 非正向：缺凭证拒绝

        # 构造真实闭环凭证（会议 + 产物）：resolution_artifact_id 挂 artifacts FK，
        # 随机 UUID 会触发外键违约，必须用真实产物 ID
        mid = _create_meeting(client)
        artifact = _seed_artifact(mid)
        resp = client.patch(
            f"/api/issues/{issue['id']}",
            json={"status": "resolved", "resolution_artifact_id": artifact["id"]},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "resolved"
        assert resp.json()["resolution_artifact_id"] == artifact["id"]

    def test_issue_update_fields_without_status(self, client):
        """PATCH 普通字段（不流转状态）→ 200。"""
        project = _create_project(client)
        issue = _create_issue(client, project["id"])
        resp = client.patch(f"/api/issues/{issue['id']}", json={"title": "改标题", "priority": 90})
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "改标题"
        assert data["priority"] == 90
        assert data["status"] == "open"

    def test_delete_issue_then_get_404(self, client):
        """DELETE 议题后再查 → 404（非正向）。"""
        project = _create_project(client)
        issue = _create_issue(client, project["id"])
        resp = client.delete(f"/api/issues/{issue['id']}")
        assert resp.status_code == 200
        assert resp.json()["deleted"] == issue["id"]
        assert client.get(f"/api/issues/{issue['id']}").status_code == 404
