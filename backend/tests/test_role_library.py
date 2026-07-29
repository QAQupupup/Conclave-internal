# 动态角色库测试
from __future__ import annotations

from app.agents.role_templates import (
    ROLE_LIBRARY,
    RoleTemplate,
    get_borrow_prompt,
    get_role_template,
)


def test_role_library_has_seven_roles():
    """角色库包含 7 个角色"""
    assert len(ROLE_LIBRARY) == 7
    expected_ids = {
        "moderator",
        "product_architect",
        "engineer",
        "security_expert",
        "data_engineer",
        "ux_designer",
        "marketing_expert",
    }
    assert set(ROLE_LIBRARY.keys()) == expected_ids


def test_role_library_all_templates_valid():
    """所有角色模板字段完整"""
    for role_id, template in ROLE_LIBRARY.items():
        assert isinstance(template, RoleTemplate)
        assert template.role_id == role_id
        assert template.display_name
        assert template.perspective
        assert template.evidence_preference
        assert template.risk_appetite in ("conservative", "balanced", "aggressive")
        assert template.default_stance
        assert template.prompt_template


def test_get_role_template_returns_correct():
    """get_role_template 返回正确模板"""
    t = get_role_template("security_expert")
    assert t is not None
    assert isinstance(t, RoleTemplate)
    assert t.role_id == "security_expert"
    assert t.display_name == "安全专家"
    assert "安全" in t.prompt_template

    t2 = get_role_template("data_engineer")
    assert t2 is not None
    assert t2.display_name == "数据工程师"
    assert "数据" in t2.prompt_template

    t3 = get_role_template("ux_designer")
    assert t3 is not None
    assert t3.display_name == "UX设计师"
    assert "用户体验" in t3.prompt_template


def test_get_role_template_core_roles():
    """核心角色也可从角色库获取"""
    t = get_role_template("moderator")
    assert t is not None
    assert t.display_name == "主持人"

    t = get_role_template("product_architect")
    assert t is not None
    assert t.display_name == "产品架构师"

    t = get_role_template("engineer")
    assert t is not None
    assert t.display_name == "工程师"


def test_get_borrow_prompt_returns_text():
    """get_borrow_prompt 返回 prompt 文本"""
    p = get_borrow_prompt("security_expert")
    assert isinstance(p, str)
    assert len(p) > 0
    assert "安全专家" in p
    assert "认证" in p

    p2 = get_borrow_prompt("data_engineer")
    assert "数据工程师" in p2
    assert "数据完整性" in p2

    p3 = get_borrow_prompt("ux_designer")
    assert "用户体验" in p3


def test_get_borrow_prompt_backward_compatible():
    """核心角色描述（视角+决策偏置）保持向后兼容，增强内容（方法论+检查清单）作为扩展附加"""
    # ADR-014 Phase 1: 角色画像从"1-2句话"升级为"四维画像"
    # 旧的精确匹配改为子串匹配，验证核心描述不变 + 新增方法论内容存在
    prompt_sec = get_borrow_prompt("security_expert")
    assert "你是安全专家。关注认证、授权、数据安全、注入防护。决策偏置：先找安全漏洞，重风险。" in prompt_sec
    assert "STRIDE" in prompt_sec  # 方法论增强
    assert "OWASP" in prompt_sec

    prompt_data = get_borrow_prompt("data_engineer")
    assert "你是数据工程师。关注数据模型、存储、迁移、一致性。决策偏置：重数据完整性。" in prompt_data
    assert "3NF" in prompt_data  # 方法论增强

    prompt_ux = get_borrow_prompt("ux_designer")
    assert "你是用户体验设计师。关注交互流程、可用性、错误处理。决策偏置：重用户视角。" in prompt_ux
    assert "Nielsen" in prompt_ux  # 方法论增强


def test_get_role_template_unknown_returns_none():
    """未知角色返回 None"""
    assert get_role_template("nonexistent_role") is None
    assert get_role_template("") is None


def test_get_borrow_prompt_unknown_returns_default():
    """未知借调角色返回兜底 prompt"""
    p = get_borrow_prompt("unknown_expert")
    assert isinstance(p, str)
    assert "unknown_expert" in p
    assert "专家" in p
