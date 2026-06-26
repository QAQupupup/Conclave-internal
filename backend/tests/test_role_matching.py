# 角色模糊匹配测试 + 真实 LLM 回归防护
# 防止 StubLLM 盲区：测试中文角色名、混合角色名、未知角色名等各种情况

import pytest

from app.models import Role


# ---------- 角色模糊匹配单元测试 ----------

def _match_role(role_str: str) -> Role | None:
    """从 nodes.py 提取的匹配逻辑（保持一致）"""
    _ROLE_KEYWORDS: dict[str, list[str]] = {
        Role.PRODUCT_ARCHITECT.value: ["product_architect", "产品", "产品经理", "pm", "architect", "架构师"],
        Role.ENGINEER.value: ["engineer", "工程师", "后端", "开发", "developer", "前端"],
    }

    def _match(role_str: str) -> Role | None:
        role_lower = role_str.lower()
        for role, keywords in _ROLE_KEYWORDS.items():
            for kw in keywords:
                if kw in role_lower:
                    return Role(role)
        return None

    return _match(role_str)


def test_match_english_role_names():
    """英文角色名精确匹配"""
    assert _match_role("product_architect") == Role.PRODUCT_ARCHITECT
    assert _match_role("engineer") == Role.ENGINEER


def test_match_chinese_role_names():
    """中文角色名模糊匹配（真实 LLM 返回的场景）"""
    assert _match_role("产品经理") == Role.PRODUCT_ARCHITECT
    assert _match_role("后端架构师") == Role.PRODUCT_ARCHITECT  # "架构师" 优先匹配
    assert _match_role("工程师") == Role.ENGINEER
    assert _match_role("后端开发") == Role.ENGINEER
    assert _match_role("前端开发者") == Role.ENGINEER


def test_match_mixed_role_names():
    """中英文混合角色名"""
    assert _match_role("PM（产品经理）") == Role.PRODUCT_ARCHITECT
    assert _match_role("Backend Engineer") == Role.ENGINEER
    assert _match_role("Architect") == Role.PRODUCT_ARCHITECT


def test_match_unknown_role_returns_none():
    """未知角色返回 None（安全专家、QA等不匹配）"""
    assert _match_role("安全专家") is None
    assert _match_role("QA工程师") is not None  # "工程师" 匹配
    assert _match_role("DevOps") is None
    assert _match_role("数据分析师") is None


def test_match_empty_and_edge_cases():
    """空字符串和边界情况"""
    assert _match_role("") is None
    assert _match_role("unknown") is None
    assert _match_role("PM") == Role.PRODUCT_ARCHITECT


def test_match_case_insensitive():
    """大小写不敏感"""
    assert _match_role("PRODUCT_ARCHITECT") == Role.PRODUCT_ARCHITECT
    assert _match_role("Engineer") == Role.ENGINEER
    assert _match_role("Product_Architect") == Role.PRODUCT_ARCHITECT
    assert _match_role("ARCHITECT") == Role.PRODUCT_ARCHITECT
    # "Product_Manager" 不含 "architect" 关键词，不匹配（正确行为）
    assert _match_role("Product_Manager") is None


# ---------- intra_team 兜底逻辑测试 ----------

def test_intra_team_fallback_when_no_match(client):
    """当 LLM 返回的角色全部不匹配时，使用默认配置兜底"""
    from app.models import MeetingState, MeetingStatus, Stage
    from app.orchestrator import runner as runner_mod
    from app.orchestrator.runner import Runner
    import asyncio

    state = MeetingState(
        meeting_id="test-fallback-001",
        topic="测试兜底",
        stage=Stage.CLARIFY,
        status=MeetingStatus.RUNNING,
    )
    # 设置全是不认识的中文角色名
    state.team_config = [
        {"role": "数据分析师", "stance": "关注数据"},
        {"role": "UX设计师", "stance": "关注体验"},
    ]
    runner_mod.set_state(state)

    state = asyncio.run(Runner().run(state))
    runner_mod.set_state(state)

    # 应该使用兜底默认配置，claims 不为空
    assert len(state.claims) > 0, "兜底配置应该产出 claims"
    assert len(state.team_conclusions) > 0, "应该有团队结论"


def test_intra_team_with_chinese_role_names(client):
    """LLM 返回中文角色名时正确匹配"""
    from app.models import MeetingState, MeetingStatus, Stage
    from app.orchestrator import runner as runner_mod
    from app.orchestrator.runner import Runner
    import asyncio

    state = MeetingState(
        meeting_id="test-chinese-roles-001",
        topic="测试中文角色",
        stage=Stage.CLARIFY,
        status=MeetingStatus.RUNNING,
    )
    # 模拟真实 LLM 返回的中文角色配置
    state.team_config = [
        {"role": "产品经理", "stance": "代表用户需求"},
        {"role": "后端架构师", "stance": "关注技术可行性"},
        {"role": "前端开发者", "stance": "关注接口易用性"},
        {"role": "安全专家", "stance": "确保API安全"},  # 不匹配，应被跳过
    ]
    runner_mod.set_state(state)

    state = asyncio.run(Runner().run(state))
    runner_mod.set_state(state)

    # 3 个角色应被匹配（产品经理、后端架构师、前端开发者），安全专家跳过
    assert len(state.team_conclusions) >= 2, "至少2个角色应被匹配"
    roles = [tc["role"] for tc in state.team_conclusions]
    # 不应包含"安全专家"
    assert "安全专家" not in roles


# ---------- 真实 LLM 输出格式回归测试 ----------

def test_stub_llm_returns_english_roles():
    """StubLLM 返回英文角色名（验证 mock 与真实 LLM 的差异）

    这个测试记录了 StubLLM 和真实 LLM 的行为差异：
    - StubLLM: 返回 "product_architect"（英文）
    - 真实 LLM (DeepSeek-V3.2): 返回 "产品经理"（中文）

    模糊匹配逻辑必须同时支持两种，否则真实场景会静默失败。
    """
    from app.agents.llm import get_llm
    import asyncio

    llm = get_llm()
    # StubLLM 的 clarify 返回中 team_config 是英文
    result = asyncio.run(llm.complete("test", schema_hint="clarify"))
    team_config = result.get("team_config", [])
    # StubLLM 返回英文角色名
    for member in team_config:
        role = member.get("role", "")
        # 验证 stub 返回的是英文（记录差异，不是断言）
        assert "_" in role or role.isascii(), f"StubLLM 应返回英文角色名, 实际: {role}"
