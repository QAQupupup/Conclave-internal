"""三种新产出类型的注册与质量门禁测试（ADR-017 Phase 1 / T1.6-T1.8）。

覆盖：
- PRODUCE_TEMPLATES：三新类型模板已注册且互不相同（含未知类型回退，非正向）
- WORKFLOW_TEMPLATES：feasibility/adr/test_gen 模板字段完整、阶段序列正确
- DELIVERABLE_TEMPLATE_MAP：产出类型 → 模板映射完整
- Runner._evaluate_quality 分派：feasibility_report/adr 走文档评估、
  test_suite 走代码评估（空产物硬门槛，非正向）
"""

from __future__ import annotations

from app.domain.meeting import MeetingState
from app.models import Stage
from app.orchestrator.runner import Runner
from app.orchestrator.workflow_templates import (
    DELIVERABLE_TEMPLATE_MAP,
    WORKFLOW_TEMPLATES,
)
from conclave_core.prompts import PRODUCE, PRODUCE_TEMPLATES, get_produce_template

NEW_TYPES = ("feasibility_report", "adr", "test_suite")


def _state(deliverable_type: str, artifact: dict | None) -> MeetingState:
    return MeetingState(
        meeting_id="mtg-qg-test",
        topic="质量门禁分派测试",
        deliverable_type=deliverable_type,
        artifact=artifact,
    )


# ---------- produce 模板注册（T1.6） ----------


def test_produce_templates_registered():
    """三新类型的 produce 模板均已注册且互不相同"""
    for dt in NEW_TYPES:
        assert dt in PRODUCE_TEMPLATES
        assert isinstance(PRODUCE_TEMPLATES[dt], str)
        assert PRODUCE_TEMPLATES[dt].strip()
    assert len({PRODUCE_TEMPLATES[dt] for dt in NEW_TYPES}) == 3


def test_produce_template_lookup_and_fallback():
    """get_produce_template 命中新类型；未知类型回退默认 PRD 模板（非正向）"""
    for dt in NEW_TYPES:
        assert get_produce_template(dt) == PRODUCE_TEMPLATES[dt]
    assert get_produce_template("no_such_type") == PRODUCE


# ---------- 工作流模板注册（T1.8） ----------


def test_workflow_templates_for_new_types():
    """三个专用模板字段完整且 produce_type 对应正确"""
    expected = {
        "feasibility": "feasibility_report",
        "adr": "adr",
        "test_gen": "test_suite",
    }
    for template_id, produce_type in expected.items():
        template = WORKFLOW_TEMPLATES[template_id]
        assert template.template_id == template_id
        assert template.produce_type == produce_type
        assert template.description
        assert template.default_roles
        assert template.quality_dimensions
        assert Stage.CLARIFY in template.stages
        assert Stage.PRODUCE in template.stages


def test_feasibility_template_keeps_evidence_check():
    """可行性研究保留证据核验；adr/test_gen 聚焦产出跳过证据核验与仲裁"""
    assert Stage.EVIDENCE_CHECK in WORKFLOW_TEMPLATES["feasibility"].stages
    assert Stage.EVIDENCE_CHECK not in WORKFLOW_TEMPLATES["adr"].stages
    assert Stage.EVIDENCE_CHECK not in WORKFLOW_TEMPLATES["test_gen"].stages
    assert Stage.ARBITRATE not in WORKFLOW_TEMPLATES["adr"].stages


def test_deliverable_template_map_complete():
    """产出类型 → 专用模板映射覆盖三新类型"""
    assert DELIVERABLE_TEMPLATE_MAP == {
        "feasibility_report": "feasibility",
        "adr": "adr",
        "test_suite": "test_gen",
    }


# ---------- 质量门禁分派（T1.7） ----------


async def test_quality_gate_feasibility_report_pass():
    """字段齐全的可行性报告走文档评估且达标"""
    long_text = "本维度评估基于现有技术方案与成本模型，覆盖性能、合规与运维风险，结论可追溯到前置假设。"
    artifact = {
        "feasibility_report": {
            "title": "仓储机器人项目可行性报告",
            "summary": long_text,
            "verdict": long_text,
            "dimensions": ["技术可行性", "成本可行性", "合规可行性"],
            "assumptions": ["硬件单价按 2026 年市场价估算"],
        }
    }
    result = await Runner()._evaluate_quality(_state("feasibility_report", artifact))
    assert result["score"] >= 60
    assert result["should_iterate"] is False
    assert result["hard_failures"] == []


async def test_quality_gate_adr_pass():
    """字段齐全的 ADR 走文档评估且达标"""
    long_text = "经过多方案对比与风险权衡，决策采纳产物独立表方案，否决 metadata 扩展与 payload 延续两条路径。"
    artifact = {
        "adr": {
            "title": "ADR-017 产物链",
            "summary": long_text,
            "context": long_text,
            "decision_table": [{"id": "D1", "decision": "独立表"}],
            "alternatives_rejected": ["metadata JSONB 扩展"],
        }
    }
    result = await Runner()._evaluate_quality(_state("adr", artifact))
    assert result["score"] >= 60
    assert result["should_iterate"] is False


async def test_quality_gate_empty_document_hard_fail():
    """空产物触发硬门槛必须迭代（非正向）"""
    for dt in ("feasibility_report", "adr"):
        result = await Runner()._evaluate_quality(_state(dt, {}))
        assert result["hard_failures"], f"{dt} 空产物应有硬门槛"
        assert result["should_iterate"] is True


async def test_quality_gate_test_suite_routes_to_code_eval():
    """test_suite 走代码评估：完整产物达标且反馈提及未执行扣分"""
    code = "def test_artifact_publish():\n    assert publish() is not None\n" * 8
    artifact = {
        "test_suite": {
            "title": "产物模块测试套件",
            "test_files": [{"path": "tests/test_artifact.py", "code": code}],
            "run_instructions": "pytest tests/test_artifact.py",
        }
    }
    result = await Runner()._evaluate_quality(_state("test_suite", artifact))
    assert result["hard_failures"] == []
    assert result["score"] >= 60
    # 「未执行」反馈是 test_suite 代码评估路径的特有输出，证明分派正确
    assert "未执行" in result["feedback"]


async def test_quality_gate_test_suite_empty_hard_fail():
    """test_suite 空产物触发硬门槛（非正向）"""
    result = await Runner()._evaluate_quality(_state("test_suite", {}))
    assert result["hard_failures"]
    assert result["should_iterate"] is True


async def test_quality_gate_test_suite_missing_test_files():
    """test_files 缺少 path/code 时触发硬门槛（边界）"""
    artifact = {
        "test_suite": {
            "title": "无效套件",
            "test_files": [{"path": "", "code": ""}],
            "run_instructions": "pytest",
        }
    }
    result = await Runner()._evaluate_quality(_state("test_suite", artifact))
    assert any("test_files" in h for h in result["hard_failures"])
    assert result["should_iterate"] is True
