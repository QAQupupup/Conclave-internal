# 中间阶段退化检测测试
# 验证 _check_intermediate_degradation 在各阶段正确检测退化指标
from __future__ import annotations

import asyncio

from app.domain.meeting import MeetingState
from app.models import MeetingStatus, Stage
from app.orchestrator.runner import Runner


def _make_state(stage: Stage = Stage.INTRA_TEAM) -> MeetingState:
    """构造测试用 MeetingState"""
    state = MeetingState(
        meeting_id="test-deg-001",
        topic="退化检测测试",
        stage=stage,
        status=MeetingStatus.RUNNING,
    )
    state.team_config = [
        {"role": "engineer", "persona": "工程师"},
        {"role": "product_architect", "persona": "产品架构师"},
        {"role": "qa_engineer", "persona": "测试工程师"},
    ]
    return state


def test_intra_team_homogenization_detected():
    """intra_team 阶段：所有 claim 同类型 → 检测到同质化退化"""
    state = _make_state()
    state.team_conclusions = [
        {"role": "engineer", "claims": [
            {"claim": "A", "type": "assumption"},
            {"claim": "B", "type": "assumption"},
        ]},
        {"role": "product_architect", "claims": [
            {"claim": "C", "type": "assumption"},
            {"claim": "D", "type": "assumption"},
        ]},
    ]

    runner = Runner()
    asyncio.run(runner._check_intermediate_degradation(state, Stage.INTRA_TEAM))

    warnings = [w for w in state.degradation_warnings if w["stage"] == "intra_team"]
    assert len(warnings) >= 1
    assert warnings[0]["warning_type"] == "claim_type_homogenization"
    assert warnings[0]["severity"] == "high"


def test_intra_team_diverse_types_no_warning():
    """intra_team 阶段：claim 类型多样 → 无同质化告警"""
    state = _make_state()
    state.team_conclusions = [
        {"role": "engineer", "claims": [
            {"claim": "A", "type": "fact"},
            {"claim": "B", "type": "assumption"},
            {"claim": "C", "type": "constraint"},
        ]},
        {"role": "product_architect", "claims": [
            {"claim": "D", "type": "fact"},
            {"claim": "E", "type": "assumption"},
        ]},
    ]

    runner = Runner()
    asyncio.run(runner._check_intermediate_degradation(state, Stage.INTRA_TEAM))

    homogenization_warnings = [
        w for w in state.degradation_warnings
        if w["warning_type"] == "claim_type_homogenization"
    ]
    assert len(homogenization_warnings) == 0


def test_intra_team_type_imbalance_detected():
    """intra_team 阶段：2 种类型但一种占比 >85% → 检测到分布不均"""
    state = _make_state()
    # 7 条 assumption + 1 条 fact → assumption 占 87.5%
    state.team_conclusions = [
        {"role": "engineer", "claims": [
            {"claim": f"claim-{i}", "type": "assumption"} for i in range(7)
        ]},
        {"role": "product_architect", "claims": [
            {"claim": "only-fact", "type": "fact"},
        ]},
    ]

    runner = Runner()
    asyncio.run(runner._check_intermediate_degradation(state, Stage.INTRA_TEAM))

    imbalance_warnings = [
        w for w in state.degradation_warnings
        if w["warning_type"] == "claim_type_imbalance"
    ]
    assert len(imbalance_warnings) == 1
    assert imbalance_warnings[0]["severity"] == "medium"


def test_intra_team_insufficient_claims():
    """intra_team 阶段：claim 数量少于角色数 → 检测到不足"""
    state = _make_state()
    state.team_config = [
        {"role": "engineer", "persona": "工程师"},
        {"role": "product_architect", "persona": "产品架构师"},
        {"role": "qa_engineer", "persona": "测试工程师"},
        {"role": "security_expert", "persona": "安全专家"},
    ]
    state.team_conclusions = [
        {"role": "engineer", "claims": [{"claim": "only-one", "type": "fact"}]},
    ]

    runner = Runner()
    asyncio.run(runner._check_intermediate_degradation(state, Stage.INTRA_TEAM))

    insufficient_warnings = [
        w for w in state.degradation_warnings
        if w["warning_type"] == "insufficient_claims"
    ]
    assert len(insufficient_warnings) == 1


def test_cross_team_zero_conflicts_with_claims():
    """cross_team 阶段：有 claim 但无冲突 → 检测到观点趋同"""
    state = _make_state(Stage.CROSS_TEAM)
    state.team_conclusions = [
        {"role": "engineer", "claims": [
            {"claim": f"c-{i}", "type": "fact"} for i in range(6)
        ]},
    ]
    state.conflicts = []

    runner = Runner()
    asyncio.run(runner._check_intermediate_degradation(state, Stage.CROSS_TEAM))

    zero_conflict_warnings = [
        w for w in state.degradation_warnings
        if w["warning_type"] == "zero_conflicts"
    ]
    assert len(zero_conflict_warnings) == 1
    assert zero_conflict_warnings[0]["severity"] == "medium"


def test_cross_team_with_conflicts_no_warning():
    """cross_team 阶段：有冲突 → 无告警"""
    state = _make_state(Stage.CROSS_TEAM)
    state.team_conclusions = [
        {"role": "engineer", "claims": [
            {"claim": f"c-{i}", "type": "fact"} for i in range(6)
        ]},
    ]
    state.conflicts = [
        {"side_a": "engineer", "side_b": "product_architect", "summary": "冲突1"},
    ]

    runner = Runner()
    asyncio.run(runner._check_intermediate_degradation(state, Stage.CROSS_TEAM))

    zero_conflict_warnings = [
        w for w in state.degradation_warnings
        if w["warning_type"] == "zero_conflicts"
    ]
    assert len(zero_conflict_warnings) == 0


def test_evidence_check_zero_assessments():
    """evidence_check 阶段：有 claim 但无评估 → 检测到证据缺失"""
    state = _make_state(Stage.EVIDENCE_CHECK)
    state.team_conclusions = [
        {"role": "engineer", "claims": [
            {"claim": "c-1", "type": "fact"},
            {"claim": "c-2", "type": "assumption"},
        ]},
    ]
    state.evidence_set = []

    runner = Runner()
    asyncio.run(runner._check_intermediate_degradation(state, Stage.EVIDENCE_CHECK))

    zero_evidence_warnings = [
        w for w in state.degradation_warnings
        if w["warning_type"] == "zero_evidence_assessments"
    ]
    assert len(zero_evidence_warnings) == 1
    assert zero_evidence_warnings[0]["severity"] == "high"


def test_arbitrate_missing_decision_record():
    """arbitrate 阶段：无决策记录 → 检测到缺失"""
    state = _make_state(Stage.ARBITRATE)
    state.decision_record = None

    runner = Runner()
    asyncio.run(runner._check_intermediate_degradation(state, Stage.ARBITRATE))

    missing_decision_warnings = [
        w for w in state.degradation_warnings
        if w["warning_type"] == "missing_decision_record"
    ]
    assert len(missing_decision_warnings) == 1
    assert missing_decision_warnings[0]["severity"] == "high"


def test_clarify_stage_not_checked():
    """clarify 阶段不在检查范围 → 无告警"""
    state = _make_state(Stage.CLARIFY)

    runner = Runner()
    asyncio.run(runner._check_intermediate_degradation(state, Stage.CLARIFY))

    assert len(state.degradation_warnings) == 0


def test_degradation_warnings_serializable():
    """degradation_warnings 可序列化为 JSON（确保持久化不报错）"""
    import json

    state = _make_state()
    state.team_conclusions = [
        {"role": "engineer", "claims": [
            {"claim": "A", "type": "assumption"},
        ]},
    ]

    runner = Runner()
    asyncio.run(runner._check_intermediate_degradation(state, Stage.INTRA_TEAM))

    # 确保所有告警都能 JSON 序列化
    json_str = json.dumps(state.degradation_warnings, ensure_ascii=False)
    parsed = json.loads(json_str)
    assert len(parsed) >= 1
