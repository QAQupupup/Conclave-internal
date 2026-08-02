"""
后端契约测试：/auth/me 响应格式与前端 UserInfo 接口一致性验证。

本测试通过 TestClient 调用真实的 /auth/me 端点，验证后端返回的用户数据
包含前端所需的所有必填字段，防止前后端接口不一致导致的运行时崩溃。

前端 UserInfo 接口定义（frontend/src/types/meeting.ts）：
  interface UserInfo {
    id: string;
    username: string;
    display_name: string;
    tenant_id: string;
    tenants: TenantInfo[];  // 必须为数组
    email?: string;
    role?: string;
    avatar_url?: string;
  }

  interface TenantInfo {
    id: string;
    name: string;
    role: string;  // 'owner' | 'admin' | 'member'
  }
"""

from __future__ import annotations


class TestMeEndpointContract:
    """通过真实 HTTP 请求验证 /auth/me 端点的响应契约。"""

    def test_me_returns_200(self, client):
        """/auth/me 在测试模式下应返回 200。"""
        resp = client.get("/auth/me")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

    def test_me_response_has_nested_user_key(self, client):
        """MeResponse 必须包含 user 字段（嵌套格式 { user: {...} }）。"""
        resp = client.get("/auth/me")
        data = resp.json()
        assert "user" in data, "响应缺少 user 字段"
        assert isinstance(data["user"], dict), "user 字段必须是 dict"

    def test_me_response_not_flat(self, client):
        """MeResponse 必须是嵌套格式，id/username 等字段在 user 内部，不在顶层。"""
        resp = client.get("/auth/me")
        data = resp.json()
        assert "user" in data
        # id 应在 user 内部，不在顶层
        assert "id" not in data, "id 不应在顶层，应在 user 内部"
        assert "username" not in data, "username 不应在顶层，应在 user 内部"

    def test_user_has_all_required_fields(self, client):
        """/auth/me 返回的 user dict 必须包含前端 UserInfo 的所有必填字段。"""
        resp = client.get("/auth/me")
        user = resp.json()["user"]

        required_fields = ["id", "username", "display_name", "tenant_id", "tenants"]
        for field in required_fields:
            assert field in user, f"user dict 缺少前端必填字段: {field}"

    def test_user_id_is_string(self, client):
        """user.id 必须存在且非空（前端用做 key 和比较）。"""
        resp = client.get("/auth/me")
        user = resp.json()["user"]
        assert user["id"] is not None, "user.id 不应为 None"
        assert str(user["id"]).strip() != "", "user.id 不应为空字符串"

    def test_user_username_is_string(self, client):
        """user.username 必须存在且非空。"""
        resp = client.get("/auth/me")
        user = resp.json()["user"]
        assert isinstance(user["username"], str)
        assert user["username"].strip() != ""

    def test_user_display_name_exists(self, client):
        """user.display_name 必须存在（前端用做显示名称）。"""
        resp = client.get("/auth/me")
        user = resp.json()["user"]
        assert "display_name" in user
        # display_name 可以为空字符串，但不能缺失
        assert user["display_name"] is not None

    def test_tenants_is_always_list(self, client):
        """tenants 字段必须始终为列表（前端依赖此假设调用 .find()）。"""
        resp = client.get("/auth/me")
        user = resp.json()["user"]
        assert isinstance(user["tenants"], list), f"tenants 应为 list，实际为 {type(user['tenants'])}"

    def test_tenants_not_empty_for_admin(self, client):
        """admin 用户应至少有 1 个租户（session fixture 创建了默认租户）。"""
        resp = client.get("/auth/me")
        user = resp.json()["user"]
        assert len(user["tenants"]) >= 1, "admin 用户应至少有 1 个租户"

    def test_each_tenant_has_required_fields(self, client):
        """每个 tenant 对象必须包含前端 TenantInfo 的必填字段：id, name, role。"""
        resp = client.get("/auth/me")
        user = resp.json()["user"]

        required_fields = ["id", "name", "role"]
        for i, tenant in enumerate(user["tenants"]):
            for field in required_fields:
                assert field in tenant, f"tenant[{i}] 缺少前端必填字段: {field}"

    def test_tenant_role_is_valid_value(self, client):
        """tenant.role 必须是前端能识别的值（owner/admin/member）。"""
        resp = client.get("/auth/me")
        user = resp.json()["user"]

        valid_roles = {"owner", "admin", "member"}
        for i, tenant in enumerate(user["tenants"]):
            assert tenant["role"] in valid_roles, f"tenant[{i}].role='{tenant['role']}' 不在有效值 {valid_roles} 中"

    def test_tenant_id_matches_one_of_tenants(self, client):
        """
        user.tenant_id 必须能在 user.tenants 中找到匹配项。
        前端代码：user.tenants.find(t => t.id === user.tenant_id)
        如果不匹配，.find() 返回 undefined，TenantSwitcher 不显示当前组织。
        """
        resp = client.get("/auth/me")
        user = resp.json()["user"]

        tenant_id = user["tenant_id"]
        # tenant_id 可能为 None（未关联租户），此时 tenants 中的匹配也应为空
        if tenant_id is not None:
            # 由于 JS 的 === 比较不自动转换类型，后端应确保 tenant_id 和 tenant.id 类型一致
            # 这里验证 tenant_id 能在 tenants 中找到（使用 str 比较容忍 int/str 差异）
            matched = any(str(t["id"]) == str(tenant_id) for t in user["tenants"])
            assert matched, (
                f"tenant_id={tenant_id} 在 tenants 中未找到匹配项。tenants ids: {[t['id'] for t in user['tenants']]}"
            )

    def test_tenant_id_type_consistent_with_tenant_ids(self, client):
        """
        tenant_id 的类型应与 tenant.id 的类型一致。
        JS 中 1 === "1" 为 false，如果类型不一致会导致 .find() 匹配失败。
        """
        resp = client.get("/auth/me")
        user = resp.json()["user"]

        tenant_id = user["tenant_id"]
        if tenant_id is not None and len(user["tenants"]) > 0:
            tenant_id_type = type(tenant_id).__name__
            for i, t in enumerate(user["tenants"]):
                t_id_type = type(t["id"]).__name__
                assert t_id_type == tenant_id_type, (
                    f"类型不一致: tenant_id 是 {tenant_id_type}({tenant_id}), "
                    f"但 tenant[{i}].id 是 {t_id_type}({t['id']})"
                )


class TestMeResponseSchemaStability:
    """MeResponse schema 稳定性测试。"""

    def test_me_response_model_has_user_field(self):
        """MeResponse model 必须有 user 字段。"""
        from app.plugins.builtin.auth.router import MeResponse

        fields = MeResponse.model_fields
        assert "user" in fields, "MeResponse 必须有 user 字段"

    def test_me_response_user_is_dict_type(self):
        """MeResponse.user 字段类型必须为 dict。"""
        from app.plugins.builtin.auth.router import MeResponse

        resp = MeResponse(user={"id": "1", "username": "test"})
        assert isinstance(resp.user, dict)
        data = resp.model_dump()
        assert "user" in data
        assert isinstance(data["user"], dict)
