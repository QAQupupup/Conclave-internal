# 三层记忆系统测试
from __future__ import annotations

import pytest

from app.memory.models import FeatureMemory, MemoryLayer, ProfileMemory, RawMemory
from app.memory.store import memory_store

# ---------- fixtures ----------


@pytest.fixture(autouse=True)
async def _clear_memory():
    """每个测试前清空进程级记忆单例，保证隔离"""
    await memory_store.clear()
    yield
    await memory_store.clear()


def _enable_memory():
    """临时启用记忆（conftest 默认禁用），返回原值供恢复"""
    from app.config import settings

    original = settings.memory_enabled
    object.__setattr__(settings, "memory_enabled", True)
    return original


def _restore_memory(original):
    """恢复 memory_enabled 原值"""
    from app.config import settings

    object.__setattr__(settings, "memory_enabled", original)


# ---------- 数据模型测试 ----------


def test_memory_layer_enum():
    """MemoryLayer 枚举值"""
    assert MemoryLayer.RAW == "raw"
    assert MemoryLayer.FEATURE == "feature"
    assert MemoryLayer.PROFILE == "profile"


def test_raw_memory_model():
    """RawMemory 数据模型字段"""
    mem = RawMemory(
        id="raw-1",
        agent_role="engineer",
        meeting_id="m1",
        stage="intra_team",
        content="测试发言",
        evidence_refs=["ev-1", "ev-2"],
        adopted=True,
        corrected_by=None,
    )
    assert mem.id == "raw-1"
    assert mem.agent_role == "engineer"
    assert mem.evidence_refs == ["ev-1", "ev-2"]
    assert mem.adopted is True
    assert mem.corrected_by is None
    assert mem.created_at is not None


def test_feature_memory_model():
    """FeatureMemory 数据模型字段"""
    feat = FeatureMemory(
        id="feat-1",
        agent_role="engineer",
        feature_type="stance_style",
        feature_value="conservative",
        confidence=0.8,
        sample_count=5,
        source_meeting_ids=["m1"],
    )
    assert feat.feature_type == "stance_style"
    assert feat.feature_value == "conservative"
    assert feat.confidence == 0.8
    assert feat.sample_count == 5


def test_profile_memory_defaults():
    """ProfileMemory 默认值"""
    profile = ProfileMemory(agent_role="engineer")
    assert profile.default_stance_style == "balanced"
    assert profile.ambiguity_tolerance == 0.5
    assert profile.evidence_dependency_level == "medium"
    assert profile.collaboration_preference == "collaborative"
    assert profile.escalation_threshold == 0.6
    assert profile.version == 1


# ---------- record_raw 测试 ----------


@pytest.mark.asyncio
async def test_record_raw_and_query():
    """测试 record_raw + 查询"""
    mem = await memory_store.record_raw(
        meeting_id="m1",
        agent_role="engineer",
        stage="intra_team",
        content="需要关注高风险的认证模块",
        evidence_refs=["ev-1"],
        adopted=True,
    )
    assert mem.id.startswith("raw-")
    assert mem.agent_role == "engineer"
    assert mem.meeting_id == "m1"
    assert mem.stage == "intra_team"
    assert mem.content == "需要关注高风险的认证模块"
    assert mem.evidence_refs == ["ev-1"]
    assert mem.adopted is True

    # 查询
    raw_list = memory_store.get_raw("engineer")
    assert len(raw_list) == 1
    assert raw_list[0].content == "需要关注高风险的认证模块"

    # 查询不存在的角色
    assert memory_store.get_raw("nonexistent") == []


@pytest.mark.asyncio
async def test_record_raw_multiple():
    """测试多条 RawMemory 记录"""
    for i in range(3):
        await memory_store.record_raw(
            meeting_id="m1",
            agent_role="product_architect",
            stage="intra_team",
            content=f"发言{i}",
        )
    raw_list = memory_store.get_raw("product_architect")
    assert len(raw_list) == 3


# ---------- extract_features 测试 ----------


@pytest.mark.asyncio
async def test_extract_features_stub_rules():
    """测试 extract_features（stub 模式规则提炼）"""
    messages = [
        {
            "agent_role": "engineer",
            "stage": "intra_team",
            "content": "这个方案有高风险，存在安全漏洞，不可行",
            "evidence_refs": ["ev-1", "ev-2", "ev-3"],
            "claim_refs": [],
        },
        {
            "agent_role": "engineer",
            "stage": "intra_team",
            "content": "建议补充认证模块，存在严重风险隐患",
            "evidence_refs": ["ev-4"],
            "claim_refs": [],
        },
    ]
    features = await memory_store.extract_features(
        meeting_id="m1",
        agent_role="engineer",
        messages=messages,
    )
    assert len(features) == 4
    feature_types = {f.feature_type for f in features}
    assert feature_types == {"stance_style", "evidence_dependency", "risk_appetite", "collaboration"}

    stance = next(f for f in features if f.feature_type == "stance_style")
    assert stance.feature_value == "conservative"

    ev_dep = next(f for f in features if f.feature_type == "evidence_dependency")
    assert ev_dep.feature_value == "high"

    for f in features:
        assert f.sample_count == 2
        assert f.confidence > 0


@pytest.mark.asyncio
async def test_extract_features_empty_messages():
    """空消息列表不产出特征"""
    features = await memory_store.extract_features("m1", "engineer", [])
    assert features == []


@pytest.mark.asyncio
async def test_extract_features_evidence_low():
    """无证据引用 -> evidence_dependency = low"""
    messages = [
        {"content": "普通发言", "evidence_refs": []},
        {"content": "另一个普通发言", "evidence_refs": []},
    ]
    features = await memory_store.extract_features("m1", "engineer", messages)
    ev_dep = next(f for f in features if f.feature_type == "evidence_dependency")
    assert ev_dep.feature_value == "low"


# ---------- get_or_create_profile 测试 ----------


def test_get_or_create_profile_defaults():
    """测试 get_or_create_profile 默认值"""
    profile = memory_store.get_or_create_profile("engineer")
    assert profile.agent_role == "engineer"
    assert profile.default_stance_style == "balanced"
    assert profile.ambiguity_tolerance == 0.5
    assert profile.evidence_dependency_level == "medium"
    assert profile.collaboration_preference == "collaborative"
    assert profile.escalation_threshold == 0.6
    assert profile.version == 1


def test_get_or_create_profile_idempotent():
    """重复调用返回同一对象"""
    p1 = memory_store.get_or_create_profile("engineer")
    p2 = memory_store.get_or_create_profile("engineer")
    assert p1 is p2


# ---------- update_profile 测试 ----------


@pytest.mark.asyncio
async def test_update_profile_merges_features():
    """测试 update_profile 更新画像"""
    features = [
        FeatureMemory(
            id="f1",
            agent_role="engineer",
            feature_type="stance_style",
            feature_value="conservative",
            confidence=0.8,
            sample_count=5,
            source_meeting_ids=["m1"],
        ),
        FeatureMemory(
            id="f2",
            agent_role="engineer",
            feature_type="evidence_dependency",
            feature_value="high",
            confidence=0.8,
            sample_count=5,
            source_meeting_ids=["m1"],
        ),
        FeatureMemory(
            id="f3",
            agent_role="engineer",
            feature_type="collaboration",
            feature_value="bridging",
            confidence=0.8,
            sample_count=5,
            source_meeting_ids=["m1"],
        ),
        FeatureMemory(
            id="f4",
            agent_role="engineer",
            feature_type="risk_appetite",
            feature_value="conservative",
            confidence=0.8,
            sample_count=5,
            source_meeting_ids=["m1"],
        ),
    ]
    profile = await memory_store.update_profile("engineer", features)
    assert profile.default_stance_style == "conservative"
    assert profile.evidence_dependency_level == "high"
    assert profile.collaboration_preference == "bridging"
    assert profile.ambiguity_tolerance == 0.3
    assert profile.escalation_threshold == 0.4
    assert profile.version >= 2


@pytest.mark.asyncio
async def test_update_profile_empty_features():
    """空特征列表不更新画像"""
    profile = await memory_store.update_profile("engineer", [])
    assert profile.default_stance_style == "balanced"
    assert profile.version == 1


@pytest.mark.asyncio
async def test_update_profile_low_confidence_ignored():
    """低置信度特征不更新画像"""
    features = [
        FeatureMemory(
            id="f1",
            agent_role="engineer",
            feature_type="stance_style",
            feature_value="aggressive",
            confidence=0.1,
            sample_count=1,
            source_meeting_ids=["m1"],
        ),
    ]
    profile = await memory_store.update_profile("engineer", features)
    assert profile.default_stance_style == "balanced"


# ---------- get_profile_anchor 测试 ----------


def test_get_profile_anchor_empty_without_profile():
    """无画像时返回空串"""
    assert memory_store.get_profile_anchor("engineer") == ""


def test_get_profile_anchor_empty_for_default_profile():
    """仅默认画像（未更新）时返回空串"""
    memory_store.get_or_create_profile("engineer")
    assert memory_store.get_profile_anchor("engineer") == ""


@pytest.mark.asyncio
async def test_get_profile_anchor_returns_text_after_update():
    """更新画像后返回注入文本"""
    features = [
        FeatureMemory(
            id="f1",
            agent_role="engineer",
            feature_type="stance_style",
            feature_value="conservative",
            confidence=0.8,
            sample_count=5,
            source_meeting_ids=["m1"],
        ),
        FeatureMemory(
            id="f2",
            agent_role="engineer",
            feature_type="evidence_dependency",
            feature_value="high",
            confidence=0.8,
            sample_count=5,
            source_meeting_ids=["m1"],
        ),
        FeatureMemory(
            id="f3",
            agent_role="engineer",
            feature_type="collaboration",
            feature_value="bridging",
            confidence=0.8,
            sample_count=5,
            source_meeting_ids=["m1"],
        ),
        FeatureMemory(
            id="f4",
            agent_role="engineer",
            feature_type="risk_appetite",
            feature_value="conservative",
            confidence=0.8,
            sample_count=5,
            source_meeting_ids=["m1"],
        ),
    ]
    await memory_store.update_profile("engineer", features)
    anchor = memory_store.get_profile_anchor("engineer")
    assert anchor != ""
    assert "决策偏置" in anchor
    assert "conservative" in anchor
    assert "high" in anchor


# ---------- inject_profile 测试 ----------


@pytest.mark.asyncio
async def test_inject_profile_with_anchor():
    """inject_profile 在有画像时拼到 prompt 前"""
    from app.memory.profile import inject_profile

    features = [
        FeatureMemory(
            id="f1",
            agent_role="engineer",
            feature_type="stance_style",
            feature_value="conservative",
            confidence=0.8,
            sample_count=5,
            source_meeting_ids=["m1"],
        ),
        FeatureMemory(
            id="f2",
            agent_role="engineer",
            feature_type="evidence_dependency",
            feature_value="high",
            confidence=0.8,
            sample_count=5,
            source_meeting_ids=["m1"],
        ),
        FeatureMemory(
            id="f3",
            agent_role="engineer",
            feature_type="collaboration",
            feature_value="bridging",
            confidence=0.8,
            sample_count=5,
            source_meeting_ids=["m1"],
        ),
        FeatureMemory(
            id="f4",
            agent_role="engineer",
            feature_type="risk_appetite",
            feature_value="conservative",
            confidence=0.8,
            sample_count=5,
            source_meeting_ids=["m1"],
        ),
    ]
    await memory_store.update_profile("engineer", features)
    result = inject_profile("原始prompt", "engineer")
    assert "决策偏置" in result
    assert "原始prompt" in result
    assert result.index("决策偏置") < result.index("原始prompt")


def test_inject_profile_without_anchor():
    """inject_profile 无画像时原样返回"""
    from app.memory.profile import inject_profile

    result = inject_profile("原始prompt", "nonexistent")
    assert result == "原始prompt"


# ---------- trigger_extraction 测试 ----------


@pytest.mark.asyncio
async def test_trigger_extraction_from_state():
    """测试 trigger_extraction 从 MeetingState 提炼"""
    from app.memory.profile import trigger_extraction
    from app.models import MeetingState

    original = _enable_memory()
    try:
        state = MeetingState(meeting_id="m1", topic="测试议题")
        state.messages = [
            {
                "id": "msg-1",
                "meeting_id": "m1",
                "agent_role": "engineer",
                "stage": "intra_team",
                "content": "这个方案有高风险，存在安全漏洞，不可行",
                "evidence_refs": ["ev-1", "ev-2"],
                "claim_refs": ["c1"],
                "created_at": "2026-01-01T00:00:00Z",
            },
        ]
        state.decision_record = {
            "decisions": [],
            "adopted_claims": ["c1"],
        }

        await trigger_extraction(state)

        raw = memory_store.get_raw("engineer")
        assert len(raw) == 1
        assert raw[0].adopted is True

        features = memory_store.get_features("engineer")
        assert len(features) == 4

        anchor = memory_store.get_profile_anchor("engineer")
        assert anchor != ""
    finally:
        _restore_memory(original)


@pytest.mark.asyncio
async def test_trigger_extraction_borrowed_role_no_profile():
    """测试借调角色发言记录但不沉淀画像"""
    from app.memory.profile import trigger_extraction
    from app.models import MeetingState

    original = _enable_memory()
    try:
        state = MeetingState(meeting_id="m2", topic="借调测试")
        state.messages = [
            {
                "id": "msg-1",
                "meeting_id": "m2",
                "agent_role": "financial_advisor",
                "stage": "intra_team",
                "content": "预算超支风险高，认证模块有隐患",
                "evidence_refs": [],
                "claim_refs": [],
                "created_at": "2026-01-01T00:00:00Z",
            },
        ]
        state.decision_record = {"decisions": [], "adopted_claims": []}

        await trigger_extraction(state)

        raw = memory_store.get_raw("financial_advisor")
        assert len(raw) == 1
        assert raw[0].content == "预算超支风险高，认证模块有隐患"

        features = memory_store.get_features("financial_advisor")
        assert len(features) == 0

        anchor = memory_store.get_profile_anchor("financial_advisor")
        assert anchor == ""
    finally:
        _restore_memory(original)


def test_trigger_extraction_disabled():
    """memory_enabled=False 时 trigger_extraction 直接返回"""
    import asyncio

    from app.config import settings
    from app.memory.profile import trigger_extraction
    from app.models import MeetingState

    assert settings.memory_enabled is False

    state = MeetingState(meeting_id="m3", topic="禁用测试")
    state.messages = [
        {
            "agent_role": "engineer",
            "stage": "intra_team",
            "content": "测试",
            "evidence_refs": [],
            "claim_refs": [],
        },
    ]
    asyncio.run(trigger_extraction(state))

    assert memory_store.get_raw("engineer") == []


@pytest.mark.asyncio
async def test_trigger_extraction_mixed_roles():
    """正式角色与借调角色混合：正式角色沉淀画像，借调角色只记录"""
    from app.memory.profile import trigger_extraction
    from app.models import MeetingState

    original = _enable_memory()
    try:
        state = MeetingState(meeting_id="m4", topic="混合测试")
        state.messages = [
            {
                "agent_role": "engineer",
                "stage": "intra_team",
                "content": "高风险不可行，建议补充认证",
                "evidence_refs": ["ev-1"],
                "claim_refs": [],
            },
            {
                "agent_role": "legal_counsel",
                "stage": "intra_team",
                "content": "数据模型需关注合规性，存在法律风险",
                "evidence_refs": [],
                "claim_refs": [],
            },
        ]
        state.decision_record = {"decisions": [], "adopted_claims": []}

        await trigger_extraction(state)

        assert len(memory_store.get_raw("engineer")) == 1
        assert len(memory_store.get_features("engineer")) == 4
        assert memory_store.get_profile_anchor("engineer") != ""

        assert len(memory_store.get_raw("legal_counsel")) == 1
        assert len(memory_store.get_features("legal_counsel")) == 0
        assert memory_store.get_profile_anchor("legal_counsel") == ""
    finally:
        _restore_memory(original)


def test_trigger_extraction_exception_safe():
    """trigger_extraction 异常时不影响主流程"""
    import asyncio

    from app.memory.profile import trigger_extraction

    original = _enable_memory()
    try:
        asyncio.run(trigger_extraction(None))  # type: ignore
        asyncio.run(trigger_extraction("not a state"))  # type: ignore
    finally:
        _restore_memory(original)
