"""PRD 溯源 Skill 单元测试。

验证 prd_traceability.yaml skill 正确加载、匹配规则正确、priority 排序正确、
prompt 包含关键章节标识。
"""

from app.agents.skills import get_active_skills, load_all_skills


class TestPRDTraceabilitySkillLoad:
    """验证 skill 正确加载。"""

    def test_prd_traceability_skill_exists(self):
        """load_all_skills() 返回包含 id=prd_traceability 的 skill。"""
        skills = load_all_skills()
        ids = [s.id for s in skills]
        assert "prd_traceability" in ids, f"prd_traceability 未加载，已加载: {ids}"

    def test_prd_traceability_priority_is_90(self):
        """prd_traceability priority 必须为 90（高于 code_conventions 的 85）。"""
        skills = {s.id: s for s in load_all_skills()}
        assert skills["prd_traceability"].priority == 90

    def test_prd_traceability_type_is_constraint(self):
        """type 必须为 constraint。"""
        skills = {s.id: s for s in load_all_skills()}
        assert skills["prd_traceability"].type == "constraint"


class TestPRDTraceabilityMatching:
    """验证 applies_to 匹配规则正确。"""

    def test_matches_clarify_prd(self):
        """stage=clarify, deliverable_type=prd_openapi 时匹配。"""
        active = get_active_skills(stage="clarify", deliverable_type="prd_openapi")
        ids = [s.id for s in active]
        assert "prd_traceability" in ids

    def test_matches_produce_prd(self):
        """stage=produce, deliverable_type=prd_openapi 时匹配。"""
        active = get_active_skills(stage="produce", deliverable_type="prd_openapi")
        ids = [s.id for s in active]
        assert "prd_traceability" in ids

    def test_not_match_deployable_service(self):
        """deliverable_type=deployable_service 时不匹配。"""
        active = get_active_skills(stage="produce", deliverable_type="deployable_service")
        ids = [s.id for s in active]
        assert "prd_traceability" not in ids

    def test_not_match_research_report(self):
        """deliverable_type=research_report 时不匹配。"""
        active = get_active_skills(stage="produce", deliverable_type="research_report")
        ids = [s.id for s in active]
        assert "prd_traceability" not in ids

    def test_matches_product_architect_role(self):
        """role=product_architect 时匹配。"""
        active = get_active_skills(stage="produce", deliverable_type="prd_openapi", role="product_architect")
        ids = [s.id for s in active]
        assert "prd_traceability" in ids

    def test_not_match_engineer_role_for_prd(self):
        """role=engineer 时不匹配（仅 product_architect 和 clarifier）。"""
        active = get_active_skills(stage="produce", deliverable_type="prd_openapi", role="engineer")
        ids = [s.id for s in active]
        assert "prd_traceability" not in ids


class TestPRDTraceabilityPriorityOrdering:
    """验证 priority 排序：prd_traceability(90) 排在 code_conventions(85) 前面。"""

    def test_prd_traceability_before_code_conventions(self):
        """在 prd_openapi+produce 场景中，prd_traceability 必须在 code_conventions 之前。"""
        active = get_active_skills(stage="produce", deliverable_type="prd_openapi")
        ids = [s.id for s in active]
        if "prd_traceability" in ids and "code_conventions" in ids:
            idx_prd = ids.index("prd_traceability")
            idx_code = ids.index("code_conventions")
            assert idx_prd < idx_code, (
                f"prd_traceability(priority 90)应在 code_conventions(priority 85)之前，实际顺序: {ids}"
            )


class TestPRDTraceabilityPromptContent:
    """验证 prompt 包含四个关键章节标识。"""

    def test_prompt_contains_append_only(self):
        """prompt 包含输入历史只追加相关标识。"""
        skills = {s.id: s for s in load_all_skills()}
        prompt = skills["prd_traceability"].prompt
        assert "Append-Only" in prompt or "只追加" in prompt

    def test_prompt_contains_smart(self):
        """prompt 包含 SMART 成功标准标识。"""
        skills = {s.id: s for s in load_all_skills()}
        prompt = skills["prd_traceability"].prompt
        assert "SMART" in prompt

    def test_prompt_contains_p0_p1_p2(self):
        """prompt 包含 P0/P1/P2 优先级标识。"""
        skills = {s.id: s for s in load_all_skills()}
        prompt = skills["prd_traceability"].prompt
        assert "P0" in prompt and "P1" in prompt and "P2" in prompt

    def test_prompt_contains_source_quotes(self):
        """prompt 包含 source_quotes 溯源标识。"""
        skills = {s.id: s for s in load_all_skills()}
        prompt = skills["prd_traceability"].prompt
        assert "source_quotes" in prompt

    def test_prompt_contains_given_when_then(self):
        """prompt 包含 GIVEN-WHEN-THEN 格式标识。"""
        skills = {s.id: s for s in load_all_skills()}
        prompt = skills["prd_traceability"].prompt
        assert "GIVEN" in prompt and "WHEN" in prompt and "THEN" in prompt
