"""任务分解 Skill 单元测试。

验证 task_decomposition.yaml skill 正确加载、匹配规则正确、
三段式结构（Specify/Plan/Tasks）完整。
"""

from app.agents.skills import get_active_skills, load_all_skills


class TestTaskDecompositionSkillLoad:
    """验证 skill 正确加载。"""

    def test_task_decomposition_exists(self):
        """load_all_skills() 返回包含 id=task_decomposition 的 skill。"""
        skills = load_all_skills()
        ids = [s.id for s in skills]
        assert "task_decomposition" in ids, f"task_decomposition 未加载，已加载: {ids}"

    def test_priority_is_80(self):
        """priority 必须为 80。"""
        skills = {s.id: s for s in load_all_skills()}
        assert skills["task_decomposition"].priority == 80

    def test_type_is_constraint(self):
        """type 必须为 constraint。"""
        skills = {s.id: s for s in load_all_skills()}
        assert skills["task_decomposition"].type == "constraint"


class TestTaskDecompositionMatching:
    """验证 applies_to 匹配规则正确。"""

    def test_matches_produce_deployable(self):
        """stage=produce, deliverable_type=deployable_service 时匹配。"""
        active = get_active_skills(stage="produce", deliverable_type="deployable_service", role="engineer")
        ids = [s.id for s in active]
        assert "task_decomposition" in ids

    def test_matches_produce_prd(self):
        """stage=produce, deliverable_type=prd_openapi 时匹配。"""
        active = get_active_skills(stage="produce", deliverable_type="prd_openapi", role="product_architect")
        ids = [s.id for s in active]
        assert "task_decomposition" in ids

    def test_matches_produce_tested_system(self):
        """deliverable_type=tested_system 时匹配。"""
        active = get_active_skills(stage="produce", deliverable_type="tested_system", role="engineer")
        ids = [s.id for s in active]
        assert "task_decomposition" in ids

    def test_not_match_research_report(self):
        """deliverable_type=research_report 时不匹配（研究报告不需要代码任务分解）。"""
        active = get_active_skills(stage="produce", deliverable_type="research_report", role="product_architect")
        ids = [s.id for s in active]
        assert "task_decomposition" not in ids

    def test_not_match_business_report(self):
        """deliverable_type=business_report 时不匹配。"""
        active = get_active_skills(stage="produce", deliverable_type="business_report", role="product_architect")
        ids = [s.id for s in active]
        assert "task_decomposition" not in ids

    def test_not_match_simple_complexity(self):
        """complexity=simple 时不匹配（仅 standard/full）。"""
        active = get_active_skills(
            stage="produce",
            deliverable_type="deployable_service",
            role="engineer",
            complexity="simple",
        )
        ids = [s.id for s in active]
        assert "task_decomposition" not in ids

    def test_matches_standard_complexity(self):
        """complexity=standard 时匹配。"""
        active = get_active_skills(
            stage="produce",
            deliverable_type="deployable_service",
            role="engineer",
            complexity="standard",
        )
        ids = [s.id for s in active]
        assert "task_decomposition" in ids

    def test_not_match_clarify_stage(self):
        """stage=clarify 时不匹配（仅 produce）。"""
        active = get_active_skills(stage="clarify", deliverable_type="prd_openapi", role="product_architect")
        ids = [s.id for s in active]
        assert "task_decomposition" not in ids

    def test_not_match_ux_designer_role(self):
        """role=ux_designer 时不匹配（仅 product_architect 和 engineer）。"""
        active = get_active_skills(stage="produce", deliverable_type="design_doc", role="ux_designer")
        ids = [s.id for s in active]
        assert "task_decomposition" not in ids


class TestTaskDecompositionPromptContent:
    """验证 prompt 包含三段式关键章节。"""

    def test_prompt_contains_specify(self):
        """prompt 包含 Specify 段。"""
        skills = {s.id: s for s in load_all_skills()}
        prompt = skills["task_decomposition"].prompt
        assert "Specify" in prompt and "规格明确" in prompt

    def test_prompt_contains_plan(self):
        """prompt 包含 Plan 段。"""
        skills = {s.id: s for s in load_all_skills()}
        prompt = skills["task_decomposition"].prompt
        assert "Plan" in prompt and "实现计划" in prompt

    def test_prompt_contains_tasks(self):
        """prompt 包含 Tasks 段。"""
        skills = {s.id: s for s in load_all_skills()}
        prompt = skills["task_decomposition"].prompt
        assert "Tasks" in prompt and "原子任务" in prompt

    def test_prompt_contains_task_type_prefixes(self):
        """prompt 包含任务类型前缀（MOD/API/SVC/TST/DOC/CFG）。"""
        skills = {s.id: s for s in load_all_skills()}
        prompt = skills["task_decomposition"].prompt
        for prefix in ["MOD", "API", "SVC", "TST", "DOC", "CFG"]:
            assert prefix in prompt, f"prompt 缺少任务类型前缀 {prefix}"

    def test_prompt_contains_deployable_grouping(self):
        """prompt 包含 deployable_service 任务分组顺序。"""
        skills = {s.id: s for s in load_all_skills()}
        prompt = skills["task_decomposition"].prompt
        assert "脚手架" in prompt
        assert "数据层" in prompt
        assert "业务逻辑层" in prompt
        assert "接口层" in prompt

    def test_prompt_bans_circular_deps(self):
        """prompt 禁止循环依赖。"""
        skills = {s.id: s for s in load_all_skills()}
        prompt = skills["task_decomposition"].prompt
        assert "循环依赖" in prompt

    def test_prompt_requires_test_tasks(self):
        """prompt 要求每个代码任务有对应测试。"""
        skills = {s.id: s for s in load_all_skills()}
        prompt = skills["task_decomposition"].prompt
        assert "TST" in prompt and "测试" in prompt


class TestSkillCombinationForPRD:
    """验证 prd_openapi+produce 场景同时激活多个相关 skill。"""

    def test_prd_produce_activates_all_relevant_skills(self):
        """prd_openapi+produce+product_architect 场景应激活 prd_traceability + task_decomposition。"""
        active = get_active_skills(
            stage="produce",
            deliverable_type="prd_openapi",
            role="product_architect",
            complexity="standard",
        )
        ids = [s.id for s in active]
        assert "prd_traceability" in ids, f"缺少 prd_traceability，激活: {ids}"
        assert "task_decomposition" in ids, f"缺少 task_decomposition，激活: {ids}"
        # 注意：deliverable_quality 仅匹配 moderator/engineer，不匹配 product_architect

    def test_deployable_engineer_activates_code_and_tasks(self):
        """deployable_service+produce+engineer 场景应激活 code_conventions + task_decomposition + ui_design_system + deliverable_quality。"""
        active = get_active_skills(
            stage="produce",
            deliverable_type="deployable_service",
            role="engineer",
            complexity="standard",
        )
        ids = [s.id for s in active]
        assert "code_conventions" in ids, f"缺少 code_conventions，激活: {ids}"
        assert "task_decomposition" in ids, f"缺少 task_decomposition，激活: {ids}"
        assert "ui_design_system" in ids, f"缺少 ui_design_system，激活: {ids}"
        assert "deliverable_quality" in ids, f"缺少 deliverable_quality，激活: {ids}"
