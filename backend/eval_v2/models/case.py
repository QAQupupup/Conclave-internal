"""Test case definitions for Eval V2."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from eval_v2.models.enums import CaseCategory, DeliverableType


class UploadedDoc(BaseModel):
    """上传到会议的参考文档。"""

    filename: str
    content: str | None = None
    """文档内容。如果为 None，使用 filename 作为路径从 dataset 目录读取。"""


class CaseConfig(BaseModel):
    """用例运行配置。"""

    deliverable_type: DeliverableType = DeliverableType.PRD_OPENAPI
    flow_plan: str = "standard"
    """工作流模板：standard/instant/plan/simple/fast/fast_path/deep_think/full"""
    workflow_template: str = "standard"
    """工作流模板：standard/design/build/research/analysis"""
    debate_depth: str = "standard"
    """辩论深度：light/standard/deep"""
    dynamic_routing: bool = False


class TerminalExpectation(BaseModel):
    """终端状态期望。"""

    expected_status: str = "done"
    expected_stage: str = "produce"
    """如果用例预期在非 produce 阶段终止（如空 topic 预期 clarify 追问），设置此值。"""
    expected_stage_early: str | None = None
    """如果预期提前终止（如注入被拦截），指定阶段。"""


class EvalCase(BaseModel):
    """评估用例定义。

    关键设计：不再包含 expected.min_claims/min_conflicts/must_have_fields 等硬性结构约束。
    评分标准由 rubric 系统统一管理，用例只定义输入和基本期望。
    """

    case_id: str
    category: CaseCategory
    tier: int = Field(default=1, ge=1, le=3)
    """用例层级：1=smoke, 2=standard, 3=challenging"""
    topic: str
    description: str = ""
    config: CaseConfig = Field(default_factory=CaseConfig)
    uploaded_docs: list[UploadedDoc] = Field(default_factory=list)
    expected_terminal: TerminalExpectation = Field(default_factory=TerminalExpectation)
    tags: list[str] = Field(default_factory=list)
    """标签用于筛选和分组，如 ["security", "api", "injection"]"""
    notes: str = ""
    """测试备注/说明。"""
    rubric_overrides: dict[str, Any] = Field(default_factory=dict)
    """维度权重覆盖（可选）。"""
