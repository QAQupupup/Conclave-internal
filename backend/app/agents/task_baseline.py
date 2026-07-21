# § TaskBaseline：领域任务基线模板
# 为不同议题类型（软件系统、股票分析、商业报告等）定义所需产物、检查点、Agent 团队。
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RequiredArtifact:
    """单个必需产物"""

    name: str
    description: str
    output_schema: str = ""
    checkers: list[str] = field(default_factory=list)


@dataclass
class TaskBaseline:
    """领域任务基线

    描述某个议题类型下：
    - 推荐 Agent 团队
    - 必需中间产物
    - 质量门
    - 默认交付物类型
    """

    domain: str
    name: str
    description: str
    default_deliverable_type: str
    team_roles: list[dict[str, Any]] = field(default_factory=list)
    required_artifacts: list[RequiredArtifact] = field(default_factory=list)
    quality_gates: list[str] = field(default_factory=list)


# ---------- 预置基线 ----------
SOFTWARE_DEV_BASELINE = TaskBaseline(
    domain="software_dev",
    name="软件系统开发",
    description="从需求到可部署全栈服务的端到端开发",
    default_deliverable_type="deployable_service",
    team_roles=[
        {"role": "product_architect", "stance": "重业务价值与用户体验"},
        {"role": "engineer", "stance": "重可行性与技术约束"},
        {"role": "qa_engineer", "stance": "重质量与边界条件"},
        {"role": "ui_designer", "stance": "重界面与交互"},
    ],
    required_artifacts=[
        RequiredArtifact("prd", "产品需求文档", "PRDResult"),
        RequiredArtifact("openapi", "OpenAPI 接口定义", "str"),
        RequiredArtifact("architecture", "架构设计说明", "str"),
        RequiredArtifact("frontend", "前端实现", "frontend_files"),
        RequiredArtifact("backend", "后端实现", "app_code"),
        RequiredArtifact("dockerfile", "容器化部署文件", "dockerfile"),
    ],
    quality_gates=[
        "PRD 包含明确目标、范围、约束",
        "API 设计覆盖 CRUD 与异常处理",
        "前端使用 React + /api 前缀",
        "Dockerfile 使用国内镜像源",
        "产物通过内容完整性校验",
    ],
)

STOCK_ANALYSIS_BASELINE = TaskBaseline(
    domain="stock_analysis",
    name="股票分析",
    description="基于多源数据的股票研究与投资建议",
    default_deliverable_type="research_report",
    team_roles=[
        {"role": "macro_analyst", "stance": "宏观与市场情绪"},
        {"role": "fundamental_analyst", "stance": "基本面与财务"},
        {"role": "technical_analyst", "stance": "技术指标与量价"},
        {"role": "risk_controller", "stance": "风险与回撤控制"},
    ],
    required_artifacts=[
        RequiredArtifact("data_sheet", "时间序列数据", "str"),
        RequiredArtifact("sentiment_analysis", "舆情与情绪分析", "str"),
        RequiredArtifact("risk_report", "风险评估", "str"),
        RequiredArtifact("investment_report", "投资建议报告", "research_report"),
    ],
    quality_gates=[
        "数据来源明确且可追溯",
        "分析结论区分事实与假设",
        "风险评估包含最大回撤与仓位建议",
    ],
)

BASELINE_REGISTRY: dict[str, TaskBaseline] = {
    "software_dev": SOFTWARE_DEV_BASELINE,
    "stock_analysis": STOCK_ANALYSIS_BASELINE,
}


def get_baseline(topic: str, domain_hint: str = "") -> TaskBaseline:
    """根据主题或显式领域提示选择基线"""
    if domain_hint and domain_hint in BASELINE_REGISTRY:
        return BASELINE_REGISTRY[domain_hint]
    topic_lower = topic.lower()
    if any(k in topic_lower for k in ("股票", "股市", "投资", "stock", "equity", "portfolio")):
        return STOCK_ANALYSIS_BASELINE
    # 默认软件系统
    return SOFTWARE_DEV_BASELINE
