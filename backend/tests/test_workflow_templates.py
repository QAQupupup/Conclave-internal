# ADR-014 Phase 2: 工作流模板系统测试
from __future__ import annotations

from app.models import Stage
from app.orchestrator.workflow_templates import (
    WORKFLOW_TEMPLATES,
    WorkflowTemplate,
    complexity_to_template,
    get_stage_sequence,
    get_workflow_template,
    next_stage_with_template,
)
from conclave_core.state import STAGE_ORDER

# ---------- 模板注册表测试 ----------


def test_workflow_templates_has_eight_templates():
    """工作流模板注册表包含 8 个内置模板（ADR-017 Phase 1 新增 adr/feasibility/test_gen）"""
    expected_ids = {"standard", "design", "build", "research", "analysis", "adr", "feasibility", "test_gen"}
    assert set(WORKFLOW_TEMPLATES.keys()) == expected_ids


def test_all_templates_valid():
    """所有模板字段完整"""
    for tid, template in WORKFLOW_TEMPLATES.items():
        assert isinstance(template, WorkflowTemplate)
        assert template.template_id == tid
        assert template.description
        assert len(template.stages) >= 2  # 至少有 clarify + produce
        assert template.default_roles
        assert template.produce_type
        assert template.quality_dimensions


def test_standard_template_matches_stage_order():
    """standard 模板的阶段序列 = STAGE_ORDER（向后兼容）"""
    standard = get_workflow_template("standard")
    assert standard.stages == STAGE_ORDER


def test_unknown_template_falls_back_to_standard():
    """未知模板 ID 回退到 standard"""
    template = get_workflow_template("nonexistent")
    assert template.template_id == "standard"


# ---------- 阶段序列测试 ----------


def test_get_stage_sequence_standard():
    """standard 模板返回完整六阶段"""
    stages = get_stage_sequence("standard")
    assert stages == STAGE_ORDER
    assert len(stages) == 6


def test_get_stage_sequence_design_skips_evidence_and_arbitrate():
    """design 模板跳过 evidence_check 和 arbitrate"""
    stages = get_stage_sequence("design")
    assert Stage.EVIDENCE_CHECK not in stages
    assert Stage.ARBITRATE not in stages
    assert Stage.CLARIFY in stages
    assert Stage.INTRA_TEAM in stages
    assert Stage.CROSS_TEAM in stages
    assert Stage.PRODUCE in stages


def test_get_stage_sequence_research_skips_cross_team_and_evidence():
    """research 模板跳过 cross_team 和 evidence_check"""
    stages = get_stage_sequence("research")
    assert Stage.CROSS_TEAM not in stages
    assert Stage.EVIDENCE_CHECK not in stages
    assert Stage.ARBITRATE not in stages
    assert Stage.CLARIFY in stages
    assert Stage.INTRA_TEAM in stages
    assert Stage.PRODUCE in stages


def test_get_stage_sequence_analysis_skips_evidence():
    """analysis 模板跳过 evidence_check"""
    stages = get_stage_sequence("analysis")
    assert Stage.EVIDENCE_CHECK not in stages
    assert Stage.CLARIFY in stages
    assert Stage.INTRA_TEAM in stages
    assert Stage.CROSS_TEAM in stages
    assert Stage.ARBITRATE in stages
    assert Stage.PRODUCE in stages


# ---------- next_stage_with_template 测试 ----------


def test_next_stage_standard_after_clarify():
    """standard 模板：clarify 之后是 intra_team"""
    nxt = next_stage_with_template(Stage.CLARIFY, "standard", "standard")
    assert nxt == Stage.INTRA_TEAM


def test_next_stage_standard_after_arbitrate():
    """standard 模板：arbitrate 之后是 produce"""
    nxt = next_stage_with_template(Stage.ARBITRATE, "standard", "standard")
    assert nxt == Stage.PRODUCE


def test_next_stage_design_after_cross_team():
    """design 模板：cross_team 之后直接是 produce（跳过 evidence_check 和 arbitrate）"""
    nxt = next_stage_with_template(Stage.CROSS_TEAM, "design", "standard")
    assert nxt == Stage.PRODUCE


def test_next_stage_research_after_intra_team():
    """research 模板：intra_team 之后直接是 produce（跳过 cross_team）"""
    nxt = next_stage_with_template(Stage.INTRA_TEAM, "research", "standard")
    assert nxt == Stage.PRODUCE


def test_next_stage_analysis_after_cross_team():
    """analysis 模板：cross_team 之后是 arbitrate（跳过 evidence_check）"""
    nxt = next_stage_with_template(Stage.CROSS_TEAM, "analysis", "standard")
    assert nxt == Stage.ARBITRATE


def test_next_stage_simple_flow_plan_skips_cross_team():
    """simple flow_plan 跳过 cross_team 和 evidence_check"""
    nxt = next_stage_with_template(Stage.INTRA_TEAM, "standard", "simple")
    # simple 跳过 cross_team，所以 intra_team 之后是 arbitrate
    assert nxt == Stage.ARBITRATE


def test_next_stage_produce_returns_none():
    """produce 是最后一个阶段，返回 None"""
    nxt = next_stage_with_template(Stage.PRODUCE, "standard", "standard")
    assert nxt is None


def test_next_stage_unknown_template_falls_back():
    """未知模板回退到 standard"""
    nxt = next_stage_with_template(Stage.CLARIFY, "nonexistent", "standard")
    assert nxt == Stage.INTRA_TEAM


# ---------- complexity_to_template 测试 ----------


def test_complexity_simple_returns_standard():
    """simple 复杂度 → standard 模板"""
    assert complexity_to_template("simple") == "standard"
    assert complexity_to_template("simple", "analysis") == "standard"


def test_complexity_standard_returns_standard():
    """standard 复杂度 → standard 模板"""
    assert complexity_to_template("standard") == "standard"
    assert complexity_to_template("standard", "build") == "standard"


def test_complexity_full_with_analysis_returns_analysis():
    """full + analysis → analysis 模板"""
    assert complexity_to_template("full", "analysis") == "analysis"


def test_complexity_full_with_design_returns_design():
    """full + design → design 模板"""
    assert complexity_to_template("full", "design") == "design"


def test_complexity_full_with_build_returns_build():
    """full + build → build 模板"""
    assert complexity_to_template("full", "build") == "build"


def test_complexity_full_with_research_returns_research():
    """full + research → research 模板"""
    assert complexity_to_template("full", "research") == "research"


def test_complexity_full_with_report_returns_standard():
    """full + report → standard 模板（保持六阶段向后兼容）"""
    assert complexity_to_template("full", "report") == "standard"


def test_complexity_full_with_unknown_type_returns_standard():
    """full + 未知类型 → standard 模板（兜底）"""
    assert complexity_to_template("full", "unknown_type") == "standard"


def test_complexity_unknown_returns_standard():
    """未知 complexity → standard 模板"""
    assert complexity_to_template("unknown") == "standard"


# ---------- 向后兼容性测试 ----------


def test_backward_compatible_standard_flow():
    """standard 模板 + standard flow_plan = 原有六阶段完整流程"""
    # 验证完整阶段链
    from conclave_core.state import next_stage

    template_stages = [
        Stage.CLARIFY,
        Stage.INTRA_TEAM,
        Stage.CROSS_TEAM,
        Stage.EVIDENCE_CHECK,
        Stage.ARBITRATE,
        Stage.PRODUCE,
    ]

    for i in range(len(template_stages) - 1):
        current = template_stages[i]
        expected_next = template_stages[i + 1]

        # 新函数
        new_next = next_stage_with_template(current, "standard", "standard")
        # 旧函数
        old_next = next_stage(current, "standard")

        assert new_next == old_next, f"阶段 {current}: new={new_next}, old={old_next}"
        assert new_next == expected_next
