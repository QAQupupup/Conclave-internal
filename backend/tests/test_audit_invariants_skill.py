"""语义安全审计不变量 Skill 单元测试。

验证 audit_invariants.yaml skill 正确加载，security_expert 角色匹配。
"""

from app.agents.skills import get_active_skills, load_all_skills


class TestAuditInvariantsSkillLoad:
    """验证 skill 正确加载。"""

    def test_audit_invariants_exists(self):
        skills = load_all_skills()
        ids = [s.id for s in skills]
        assert "audit_invariants" in ids, f"audit_invariants 未加载，已加载: {ids}"

    def test_priority_is_85(self):
        skills = {s.id: s for s in load_all_skills()}
        assert skills["audit_invariants"].priority == 85

    def test_type_is_constraint(self):
        skills = {s.id: s for s in load_all_skills()}
        assert skills["audit_invariants"].type == "constraint"


class TestAuditInvariantsMatching:
    """验证 applies_to 匹配规则。"""

    def test_matches_security_expert_backend(self):
        active = get_active_skills(stage="produce", deliverable_type="backend_service", role="security_expert")
        ids = [s.id for s in active]
        assert "audit_invariants" in ids

    def test_matches_security_expert_fullstack(self):
        active = get_active_skills(stage="produce", deliverable_type="fullstack_app", role="security_expert")
        ids = [s.id for s in active]
        assert "audit_invariants" in ids

    def test_not_match_engineer(self):
        active = get_active_skills(stage="produce", deliverable_type="backend_service", role="engineer")
        ids = [s.id for s in active]
        assert "audit_invariants" not in ids

    def test_not_match_non_produce(self):
        active = get_active_skills(stage="clarify", deliverable_type="backend_service", role="security_expert")
        ids = [s.id for s in active]
        assert "audit_invariants" not in ids


class TestAuditInvariantsPromptContent:
    """验证 prompt 包含关键审计章节。"""

    def test_prompt_contains_tenant_isolation(self):
        skills = {s.id: s for s in load_all_skills()}
        prompt = skills["audit_invariants"].prompt
        assert "多租户" in prompt or "tenant_id" in prompt
        assert "跨租户" in prompt

    def test_prompt_contains_async_safety(self):
        skills = {s.id: s for s in load_all_skills()}
        prompt = skills["audit_invariants"].prompt
        assert "阻塞" in prompt or "async" in prompt.lower()
        assert "事件循环" in prompt or "time.sleep" in prompt

    def test_prompt_contains_n_plus_one(self):
        skills = {s.id: s for s in load_all_skills()}
        prompt = skills["audit_invariants"].prompt
        assert "N+1" in prompt or "N\\+1" in prompt

    def test_prompt_contains_authorization(self):
        skills = {s.id: s for s in load_all_skills()}
        prompt = skills["audit_invariants"].prompt
        assert "授权" in prompt or "认证" in prompt or "IDOR" in prompt

    def test_prompt_contains_block_condition(self):
        skills = {s.id: s for s in load_all_skills()}
        prompt = skills["audit_invariants"].prompt
        assert "BLOCK" in prompt or "阻断" in prompt
