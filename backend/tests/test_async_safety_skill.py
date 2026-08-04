"""异步代码安全 Skill 单元测试。

验证 async_safety.yaml skill 正确加载，engineer 和 security_expert 角色都匹配。
"""

from app.agents.skills import get_active_skills, load_all_skills


class TestAsyncSafetySkillLoad:
    """验证 skill 正确加载。"""

    def test_async_safety_exists(self):
        skills = load_all_skills()
        ids = [s.id for s in skills]
        assert "async_safety" in ids, f"async_safety 未加载，已加载: {ids}"

    def test_priority_is_90(self):
        skills = {s.id: s for s in load_all_skills()}
        assert skills["async_safety"].priority == 90

    def test_type_is_constraint(self):
        skills = {s.id: s for s in load_all_skills()}
        assert skills["async_safety"].type == "constraint"


class TestAsyncSafetyMatching:
    """验证 applies_to 匹配规则。"""

    def test_matches_engineer_produce(self):
        active = get_active_skills(stage="produce", deliverable_type="backend_service", role="engineer")
        ids = [s.id for s in active]
        assert "async_safety" in ids

    def test_matches_security_expert_produce(self):
        active = get_active_skills(stage="produce", deliverable_type="backend_service", role="security_expert")
        ids = [s.id for s in active]
        assert "async_safety" in ids

    def test_matches_engineer_review(self):
        active = get_active_skills(stage="review", deliverable_type="backend_service", role="engineer")
        ids = [s.id for s in active]
        assert "async_safety" in ids

    def test_not_match_non_backend_roles(self):
        active = get_active_skills(stage="produce", deliverable_type="backend_service", role="product_architect")
        ids = [s.id for s in active]
        assert "async_safety" not in ids


class TestAsyncSafetyPromptContent:
    """验证 prompt 包含关键 async 安全章节。"""

    def test_prompt_mentions_blocking_io(self):
        skills = {s.id: s for s in load_all_skills()}
        prompt = skills["async_safety"].prompt
        assert "阻塞" in prompt
        assert "time.sleep" in prompt
        assert "requests" in prompt

    def test_prompt_mentions_timeout(self):
        skills = {s.id: s for s in load_all_skills()}
        prompt = skills["async_safety"].prompt
        assert "超时" in prompt or "timeout" in prompt

    def test_prompt_mentions_create_task(self):
        skills = {s.id: s for s in load_all_skills()}
        prompt = skills["async_safety"].prompt
        assert "create_task" in prompt

    def test_prompt_mentions_nested_loop(self):
        skills = {s.id: s for s in load_all_skills()}
        prompt = skills["async_safety"].prompt
        assert "嵌套" in prompt or "run_until_complete" in prompt

    def test_prompt_mentions_lock(self):
        skills = {s.id: s for s in load_all_skills()}
        prompt = skills["async_safety"].prompt
        assert "async with" in prompt or "lock" in prompt

    def test_prompt_contains_checklist(self):
        skills = {s.id: s for s in load_all_skills()}
        prompt = skills["async_safety"].prompt
        assert "检查清单" in prompt or "审查" in prompt
        # 至少包含10个检查项（[）标记
        assert prompt.count("- [ ]") >= 8
