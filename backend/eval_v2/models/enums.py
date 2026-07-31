"""Enumerations for Eval V2 framework."""

from enum import Enum


class FailureClass(str, Enum):
    """故障三分类。"""

    INFRASTRUCTURE = "infrastructure"
    """基础设施故障：HTTP 5xx/4xx、认证失败、连接超时、Embedding 402、熔断器触发等。"""

    MODEL = "model"
    """模型/系统能力缺陷：stub 降级、质量分过低、Judge 判定语义不合格、退化告警等。"""

    TEST_BUG = "test_bug"
    """测试用例/框架缺陷：JSON Schema 校验失败、expected 配置非法、评分器 bug 等。"""


class Level(str, Enum):
    """5 层评估层级。"""

    L0_HEALTH = "l0_health"
    """L0 系统健康（硬门槛）：服务可达、认证有效、基础设施正常。"""

    L1_PROCESS = "l1_process"
    """L1 流程完整性：终态正确、阶段完成、无 stub 降级、冲突处理、漂移率可接受。"""

    L2_INTERNAL = "l2_internal"
    """L2 内部质量：复用 SUT quality_score、退化告警、confidence_flags、hard_failures。"""

    L3_SEMANTIC = "l3_semantic"
    """L3 语义质量：LLM-as-Judge 多维度 CoT 评分（核心层，权重 0.45）。"""

    L4_COMPARATIVE = "l4_comparative"
    """L4 对比评估：Pass@3 稳定性、Judge 自一致性、消融对比、长度偏置检测。"""


class DeliverableType(str, Enum):
    """产出类型枚举，映射 SUT deliverable_type。"""

    PRD_OPENAPI = "prd_openapi"
    DESIGN_DOC = "design_doc"
    RESEARCH_REPORT = "research_report"
    BUSINESS_REPORT = "business_report"
    MEETING_SUMMARY = "meeting_summary"
    TECH_SPEC = "tech_spec"
    ARCHITECTURE_DECISION = "architecture_decision"
    GENERAL = "general"


class CaseCategory(str, Enum):
    """测试用例分类。"""

    PRD_OPENAPI = "prd_openapi"
    DESIGN_DOC = "design_doc"
    RESEARCH = "research"
    BUSINESS = "business"
    EDGE_ADVERSARIAL = "edge_adversarial"


class JudgeScale(str, Enum):
    """Judge 评分量表类型。"""

    BINARY = "binary"
    """二元判定：pass/fail。"""

    LIKERT_5 = "likert_5"
    """5 级 Likert 量表：1-5 分，带锚点描述。"""

    CONTINUOUS = "continuous"
    """连续评分：0.0-1.0（仅用于内部聚合，不直接用于 Judge 输出）。"""


class ConfidenceLevel(str, Enum):
    """Judge 置信度等级。"""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class RunMode(str, Enum):
    """运行模式。"""

    STANDARD = "standard"
    ABLATION = "ablation"
    FULL = "full"
    SERVICE_CHECK = "service_check"
