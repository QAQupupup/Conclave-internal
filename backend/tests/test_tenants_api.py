"""租户管理 API 测试：列表、创建、成员、切换。

测试模式下 middleware 自动设置 uid=1（admin 用户），该用户由 conftest session fixture 预置，
lifespan 启动时自动关联到默认租户(slug='default')。
每个测试使用唯一 slug/名称避免测试间数据冲突。
"""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture()
def client():
    """创建测试客户端。"""
    app = create_app()
    with TestClient(app) as c:
        yield c


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


class TestTenantsAPI:
    """租户管理端点测试。"""

    def test_list_my_tenants_returns_list(self, client):
        """GET /api/tenants 返回当前用户租户列表"""
        resp = client.get("/api/tenants")
        assert resp.status_code == 200
        data = resp.json()
        assert "tenants" in data
        assert isinstance(data["tenants"], list)
        assert len(data["tenants"]) >= 1

    def test_list_my_tenants_has_default(self, client):
        """列表中应包含默认租户（slug='default'，由 lifespan 自动创建）"""
        resp = client.get("/api/tenants")
        data = resp.json()
        slugs = [t["slug"] for t in data["tenants"]]
        assert "default" in slugs

    def test_create_tenant(self, client):
        """POST /api/tenants 创建新租户"""
        name = _unique("测试团队")
        resp = client.post("/api/tenants", json={"name": name})
        assert resp.status_code == 201
        tenant = resp.json()
        assert tenant["name"] == name
        assert tenant["role"] == "owner"
        assert "id" in tenant
        assert "slug" in tenant
        assert tenant["plan"] == "free"
        assert len(tenant["slug"]) > 0

    def test_create_tenant_with_slug(self, client):
        """指定 slug 创建租户"""
        slug = _unique("my-company")
        resp = client.post("/api/tenants", json={"name": "我的公司", "slug": slug})
        assert resp.status_code == 201
        assert resp.json()["slug"] == slug

    def test_create_tenant_duplicate_slug_fails(self, client):
        """重复 slug 应返回 409"""
        slug = _unique("dup")
        client.post("/api/tenants", json={"name": "团队A", "slug": slug})
        resp = client.post("/api/tenants", json={"name": "团队B", "slug": slug})
        assert resp.status_code == 409

    def test_get_tenant_members(self, client):
        """GET /api/tenants/{id}/members 返回成员列表"""
        slug = _unique("members")
        create_resp = client.post("/api/tenants", json={"name": "成员测试", "slug": slug})
        assert create_resp.status_code == 201
        tid = create_resp.json()["id"]

        resp = client.get(f"/api/tenants/{tid}/members")
        assert resp.status_code == 200
        data = resp.json()
        assert "members" in data
        assert isinstance(data["members"], list)
        # 创建者(admin)应在成员列表中
        usernames = [m["username"] for m in data["members"]]
        assert "admin" in usernames

    def test_get_members_for_nonexistent_tenant(self, client):
        """访问不存在的租户成员应返回 404"""
        resp = client.get("/api/tenants/999999/members")
        assert resp.status_code == 404

    def test_switch_tenant(self, client):
        """POST /api/tenants/{id}/switch 切换租户并返回新 JWT"""
        slug = _unique("switch")
        create_resp = client.post("/api/tenants", json={"name": "切换测试", "slug": slug})
        assert create_resp.status_code == 201
        new_tid = create_resp.json()["id"]

        resp = client.post(f"/api/tenants/{new_tid}/switch")
        # 测试模式下认证被跳过，switch 会签发 token 并设置 cookie
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"
        assert "tenant" in data
        assert data["tenant"]["id"] == new_tid

    def test_switch_to_nonexistent_tenant_fails(self, client):
        """切换到不存在的租户返回 404"""
        resp = client.post("/api/tenants/999999/switch")
        assert resp.status_code == 404

    def test_create_tenant_returns_valid_id(self, client):
        """创建的租户可以通过 list 查询到"""
        slug = _unique("isolate")
        create_resp = client.post("/api/tenants", json={"name": "隔离测试", "slug": slug})
        assert create_resp.status_code == 201
        new_id = create_resp.json()["id"]

        list_resp = client.get("/api/tenants")
        ids = [t["id"] for t in list_resp.json()["tenants"]]
        assert new_id in ids

    def test_route_mounted(self, client):
        """路由挂载正确"""
        resp = client.get("/api/tenants")
        assert resp.status_code == 200
