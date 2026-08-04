"""UI 设计系统 Skill 单元测试。

验证 ui_design_system.yaml skill 正确加载、prompt 包含 Impeccable 反模式章节、
字体声明已修正。
"""

from app.agents.skills import get_active_skills, load_all_skills


class TestUIDesignSkillLoad:
    """验证 skill 正确加载。"""

    def test_ui_design_skill_exists(self):
        """load_all_skills() 返回包含 id=ui_design_system 的 skill。"""
        skills = load_all_skills()
        ids = [s.id for s in skills]
        assert "ui_design_system" in ids, f"ui_design_system 未加载，已加载: {ids}"

    def test_ui_design_priority_is_90(self):
        """ui_design_system priority 必须为 90。"""
        skills = {s.id: s for s in load_all_skills()}
        assert skills["ui_design_system"].priority == 90


class TestUIDesignPromptContent:
    """验证 prompt 包含 Impeccable 反模式关键内容。"""

    def test_prompt_contains_impeccable_section(self):
        """prompt 包含 Impeccable 章节标题。"""
        skills = {s.id: s for s in load_all_skills()}
        prompt = skills["ui_design_system"].prompt
        assert "Impeccable" in prompt

    def test_prompt_bans_purple_blue_gradient(self):
        """prompt 禁止紫蓝渐变。"""
        skills = {s.id: s for s in load_all_skills()}
        prompt = skills["ui_design_system"].prompt
        assert "紫蓝渐变" in prompt

    def test_prompt_bans_nested_cards(self):
        """prompt 禁止卡片套卡片。"""
        skills = {s.id: s for s in load_all_skills()}
        prompt = skills["ui_design_system"].prompt
        assert "卡片套卡片" in prompt

    def test_prompt_bans_glassmorphism(self):
        """prompt 禁止玻璃拟态。"""
        skills = {s.id: s for s in load_all_skills()}
        prompt = skills["ui_design_system"].prompt
        assert "玻璃拟态" in prompt

    def test_prompt_mentions_4px_spacing_base(self):
        """prompt 强调 4px 间距基准。"""
        skills = {s.id: s for s in load_all_skills()}
        prompt = skills["ui_design_system"].prompt
        assert "4px" in prompt and "基准" in prompt

    def test_prompt_bans_bounce_animation(self):
        """prompt 禁止弹跳动画。"""
        skills = {s.id: s for s in load_all_skills()}
        prompt = skills["ui_design_system"].prompt
        assert "弹跳" in prompt or "bounce" in prompt

    def test_prompt_restricts_inter_usage(self):
        """prompt 限制 Inter 仅用于英文数字场景。"""
        skills = {s.id: s for s in load_all_skills()}
        prompt = skills["ui_design_system"].prompt
        assert "Inter/Roboto 仅用于" in prompt

    def test_font_list_does_not_start_with_inter(self):
        """字体列表不应以 Inter 开头。"""
        skills = {s.id: s for s in load_all_skills()}
        prompt = skills["ui_design_system"].prompt
        # 找字体行
        for line in prompt.split("\n"):
            if "字体：" in line and "等宽" not in line:
                assert not line.strip().startswith("- 字体：Inter"), f"正文字体不应以 Inter 开头: {line.strip()}"
                break


class TestUIDesignMatching:
    """验证 applies_to 匹配规则正确。"""

    def test_matches_produce_deployable(self):
        """stage=produce, deliverable_type=deployable_service 时匹配。"""
        active = get_active_skills(stage="produce", deliverable_type="deployable_service", role="engineer")
        ids = [s.id for s in active]
        assert "ui_design_system" in ids

    def test_matches_produce_design_doc(self):
        """stage=produce, deliverable_type=design_doc 时匹配。"""
        active = get_active_skills(stage="produce", deliverable_type="design_doc", role="ux_designer")
        ids = [s.id for s in active]
        assert "ui_design_system" in ids

    def test_not_match_prd(self):
        """deliverable_type=prd_openapi 时不匹配（纯文档，无前端）。"""
        active = get_active_skills(stage="produce", deliverable_type="prd_openapi", role="product_architect")
        ids = [s.id for s in active]
        assert "ui_design_system" not in ids
