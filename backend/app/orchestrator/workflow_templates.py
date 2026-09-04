# ADR-014 Phase 2: 工作流模板系统
# 定义不同议题类型的阶段序列 + 角色组合 + 产出格式
# 默认模板 "standard" = 现有六阶段管线（向后兼容）
from __future__ import annotations

from app.models import Stage
from conclave_core.state import STAGE_ORDER


class WorkflowTemplate:
    """工作流模板：定义阶段序列 + 角色组合 + 产出格式

    ADR-014 Phase 2: 替代固定 STAGE_ORDER，支持按议题类型定制阶段序列。
    默认模板 "standard" 的 stages = STAGE_ORDER（向后兼容）。
    """

    def __init__(
        self,
        template_id: str,
        description: str,
        stages: list[Stage],
        default_roles: list[str],
        produce_type: str,
        quality_dimensions: list[str] | None = None,
    ) -> None:
        self.template_id = template_id
        self.description = description
        self.stages = stages
        self.default_roles = default_roles
        self.produce_type = produce_type
        self.quality_dimensions = quality_dimensions or [
            "completeness",
            "accuracy",
            "actionability",
        ]


# ---------- 内置工作流模板 ----------
# ADR-014 Phase 2: 6 个内置模板覆盖常见议题类型
# standard 模板的 stages = STAGE_ORDER（向后兼容，不改变现有行为）

WORKFLOW_TEMPLATES: dict[str, WorkflowTemplate] = {
    "standard": WorkflowTemplate(
        template_id="standard",
        description="通用议题（默认，向后兼容六阶段管线）",
        stages=STAGE_ORDER,  # [clarify, intra_team, cross_team, evidence_check, arbitrate, produce]
        default_roles=["product_architect", "engineer"],
        produce_type="prd_openapi",
    ),
    "design": WorkflowTemplate(
        template_id="design",
        description="架构设计类议题（跳过证据检查和仲裁，聚焦设计产出）",
        stages=[
            Stage.CLARIFY,
            Stage.INTRA_TEAM,
            Stage.CROSS_TEAM,
            Stage.PRODUCE,
        ],
        default_roles=["product_architect", "engineer", "security_expert"],
        produce_type="design_doc",
        quality_dimensions=[
            "completeness",
            "architecture_clarity",
            "tech_stack_rational",
            "risk_coverage",
        ],
    ),
    "build": WorkflowTemplate(
        template_id="build",
        description="可部署服务议题（跳过证据检查，聚焦工程实现）",
        stages=[
            Stage.CLARIFY,
            Stage.INTRA_TEAM,
            Stage.CROSS_TEAM,
            Stage.PRODUCE,
        ],
        default_roles=[
            "product_architect",
            "engineer",
            "security_expert",
            "data_engineer",
        ],
        produce_type="deployable_service",
        quality_dimensions=[
            "completeness",
            "layered_architecture",
            "test_coverage",
            "security_review",
            "deployability",
        ],
    ),
    "research": WorkflowTemplate(
        template_id="research",
        description="调研报告类议题（跳过跨队辩论和证据检查，聚焦研究发现）",
        stages=[
            Stage.CLARIFY,
            Stage.INTRA_TEAM,
            Stage.PRODUCE,
        ],
        default_roles=["product_architect", "marketing_expert"],
        produce_type="research_report",
        quality_dimensions=[
            "completeness",
            "evidence_quality",
            "analysis_depth",
            "recommendation_actionability",
        ],
    ),
    "analysis": WorkflowTemplate(
        template_id="analysis",
        description="商业分析类议题（跳过证据检查，聚焦商业决策）",
        stages=[
            Stage.CLARIFY,
            Stage.INTRA_TEAM,
            Stage.CROSS_TEAM,
            Stage.ARBITRATE,
            Stage.PRODUCE,
        ],
        default_roles=["product_architect", "marketing_expert", "data_engineer"],
        produce_type="business_report",
        quality_dimensions=[
            "completeness",
            "market_analysis_depth",
            "financial_rigor",
            "strategic_clarity",
        ],
    ),
    # ---------- ADR-017 Phase 1：三种新产出类型的专用模板（T1.8 / I6） ----------
    "feasibility": WorkflowTemplate(
        template_id="feasibility",
        description="可行性研究议题（保留证据检查，产出可行性报告）",
        stages=[
            Stage.CLARIFY,
            Stage.INTRA_TEAM,
            Stage.CROSS_TEAM,
            Stage.EVIDENCE_CHECK,
            Stage.PRODUCE,
        ],
        default_roles=["product_architect", "engineer"],
        produce_type="feasibility_report",
        quality_dimensions=[
            "completeness",
            "verdict_clarity",
            "dimension_coverage",
            "assumption_traceability",
        ],
    ),
    "adr": WorkflowTemplate(
        template_id="adr",
        description="架构决策议题（聚焦决策记录，产出 ADR）",
        stages=[
            Stage.CLARIFY,
            Stage.INTRA_TEAM,
            Stage.CROSS_TEAM,
            Stage.PRODUCE,
        ],
        default_roles=["product_architect", "engineer"],
        produce_type="adr",
        quality_dimensions=[
            "completeness",
            "decision_traceability",
            "alternative_coverage",
            "consequence_clarity",
        ],
    ),
    "test_gen": WorkflowTemplate(
        template_id="test_gen",
        description="测试生成议题（聚焦测试设计，产出测试套件）",
        stages=[
            Stage.CLARIFY,
            Stage.INTRA_TEAM,
            Stage.CROSS_TEAM,
            Stage.PRODUCE,
        ],
        default_roles=["product_architect", "engineer"],
        produce_type="test_suite",
        quality_dimensions=[
            "completeness",
            "test_coverage",
            "negative_case_coverage",
            "runnability",
        ],
    ),
}

# ADR-017 Phase 1（T1.8 / I6）：产出类型 → 专用工作流模板。
# 会议创建请求的 deliverable_type 属于三新类型时，run_clarify 固定对应模板，
# 不被 complexity 映射或议题拆分覆写。
DELIVERABLE_TEMPLATE_MAP: dict[str, str] = {
    "feasibility_report": "feasibility",
    "adr": "adr",
    "test_suite": "test_gen",
}


def get_workflow_template(template_id: str) -> WorkflowTemplate:
    """获取工作流模板，未知 ID 回退到 standard（向后兼容）

    ADR-014 Phase 2: 模板选择器的核心函数。
    Runner 调用此函数获取阶段序列，替代固定 STAGE_ORDER。
    """
    return WORKFLOW_TEMPLATES.get(template_id, WORKFLOW_TEMPLATES["standard"])


def get_stage_sequence(template_id: str) -> list[Stage]:
    """获取工作流模板的阶段序列

    返回模板定义的阶段列表，未知模板回退到 STAGE_ORDER。
    """
    template = get_workflow_template(template_id)
    return template.stages


def next_stage_with_template(
    current: Stage,
    template_id: str,
    flow_plan: str = "standard",
) -> Stage | None:
    """在工作流模板的阶段序列中返回下一阶段

    ADR-014 Phase 2: 替代 conclave_core.state.next_stage()，支持自定义阶段序列。
    仍兼容 flow_plan 的阶段跳过逻辑（simple 模式跳过 cross_team + evidence_check）。

    Args:
        current: 当前阶段
        template_id: 工作流模板 ID
        flow_plan: 议题路由计划（用于阶段跳过）

    Returns:
        下一阶段，末尾返回 None
    """
    from conclave_core.state import get_skipped_stages

    stages = get_stage_sequence(template_id)
    skip = get_skipped_stages(flow_plan)

    # 当前阶段不在模板序列中（异常情况），回退到 STAGE_ORDER
    if current not in stages:
        from conclave_core.state import next_stage

        return next_stage(current, flow_plan)

    idx = stages.index(current)
    for i in range(idx + 1, len(stages)):
        if stages[i] not in skip:
            return stages[i]
    return None


def complexity_to_template(complexity: str, topic_type: str = "") -> str:
    """将 clarify 阶段的 complexity 映射到工作流模板 ID

    ADR-014 Phase 2: clarify 阶段输出 complexity + topic_type，
    本函数将它们映射到工作流模板。

    映射规则：
    - simple → standard（flow_plan=simple 会跳过部分阶段）
    - standard → standard
    - full → 按议题类型选择 design/build/research/analysis
    - 未知 complexity → standard（兜底）

    Args:
        complexity: clarify 阶段输出的复杂度（simple/standard/full）
        topic_type: clarify 阶段输出的议题类型（analysis/design/build/research）

    Returns:
        工作流模板 ID
    """
    if complexity == "full":
        # full 复杂度按议题类型选择专用模板
        type_mapping = {
            "analysis": "analysis",
            "design": "design",
            "build": "build",
            "research": "research",
            "report": "standard",  # report 类型走标准六阶段（保持向后兼容）
        }
        return type_mapping.get(topic_type, "standard")
    # simple / standard / 未知 → standard 模板
    return "standard"
