"""Rubric definitions for L3 semantic evaluation.

Each deliverable type has a set of dimensions with weights and 5-level Likert anchors.
"""

from __future__ import annotations


class DimensionSpec:
    """单个评分维度的规范。"""

    def __init__(
        self,
        name: str,
        weight: float,
        anchors: dict[int, str],
        description: str = "",
    ):
        self.name = name
        self.weight = weight
        self.anchors = anchors  # 1-5 -> anchor text
        self.description = description

    def get_anchor_text(self) -> str:
        """生成锚点描述文本，用于 Judge prompt。"""
        lines = []
        for score in sorted(self.anchors.keys()):
            lines.append(f"  {score}: {self.anchors[score]}")
        return "\n".join(lines)


# PRD + OpenAPI 8 维度
PRD_OPENAPI_DIMENSIONS: list[DimensionSpec] = [
    DimensionSpec(
        name="completeness",
        weight=0.15,
        description="所有必需章节是否完整，API 端点是否覆盖全部功能需求",
        anchors={
            1: "大量必需章节缺失，核心功能未覆盖，大面积占位符/TODO",
            2: "部分章节存在但不完整，多个关键端点缺失或仅有名称无细节",
            3: "主要章节齐全，核心端点有基本描述但部分参数/响应细节不足",
            4: "所有必需章节完整，API端点覆盖全部需求，参数和响应基本完整",
            5: "极其完整：所有章节详尽无遗，每个端点包含完整method/path/parameters/requestBody/responses/errors，覆盖所有边界情况",
        },
    ),
    DimensionSpec(
        name="accuracy",
        weight=0.15,
        description="技术准确性，RESTful 规范遵循，参数和状态码设计合理性",
        anchors={
            1: "存在严重技术错误，HTTP方法使用错误，状态码完全混乱",
            2: "多处REST规范违反，参数类型错误，状态码使用不当",
            3: "基本遵循REST规范，主要技术决策正确，但有少量不准确之处",
            4: "技术准确，RESTful规范，参数和状态码设计合理",
            5: "技术上完美无瑕：HTTP方法语义精确，状态码选择精准，符合OpenAPI最佳实践，数据类型和格式完全正确",
        },
    ),
    DimensionSpec(
        name="coherence",
        weight=0.10,
        description="文档目标与范围一致，各章节之间无矛盾，需求和API设计对应",
        anchors={
            1: "目标/范围/API设计之间严重矛盾，前后不一致",
            2: "多处不一致，PRD描述的功能与API端点不对应",
            3: "基本一致，但有少量前后矛盾或未对齐之处",
            4: "目标与范围一致，API设计与需求对应，无明显矛盾",
            5: "高度一致：PRD每个需求点都有对应API端点，数据模型统一，无任何矛盾",
        },
    ),
    DimensionSpec(
        name="actionability",
        weight=0.15,
        description="产出是否可直接用于实现，开发者能否根据文档直接编码",
        anchors={
            1: "完全无法实现：只有模糊描述，无具体接口定义，全是高层概念",
            2: "需要大量补充才能实现：只有端点名称，缺参数/响应/示例",
            3: "基本可实现，但需要开发者自行推断部分字段和错误处理",
            4: "可以直接实现：端点/参数/响应/错误码基本齐全，有基本示例",
            5: "可直接交付开发：每个端点有完整定义和示例，包含curl命令/请求响应示例，开发者无需额外沟通即可编码",
        },
    ),
    DimensionSpec(
        name="specificity",
        weight=0.10,
        description="具体性：无模糊措辞、无TODO/placeholder、术语定义清晰",
        anchors={
            1: "大量TODO/placeholder/TBD，模糊措辞如'适当的''合理的'",
            2: "有多处占位符或模糊表述，关键参数未具体化",
            3: "主要内容具体，但有少量模糊之处需要澄清",
            4: "内容具体明确，无TODO，术语有定义，参数有具体值/格式",
            5: "极其具体：所有字段有精确类型/格式/约束/示例，零占位符，每个术语都有明确定义",
        },
    ),
    DimensionSpec(
        name="constraint_coverage",
        weight=0.10,
        description="安全/性能/兼容性/错误处理等非功能性约束覆盖",
        anchors={
            1: "完全未提及任何非功能性约束",
            2: "只提及1-2个方面（如认证），缺少性能/错误处理/限流等",
            3: "覆盖了主要非功能需求（认证+基本错误处理），但深度不足",
            4: "覆盖认证/授权/限流/分页/错误处理/版本控制等核心约束",
            5: "全面覆盖：认证/授权/限流/缓存/幂等性/版本控制/CORS/安全头/监控/性能SLA/降级方案，每个约束有具体实现方式",
        },
    ),
    DimensionSpec(
        name="openapi_validity",
        weight=0.15,
        description="OpenAPI 规范语法正确性，包含必要的 paths/components/servers 等结构",
        anchors={
            1: "无OpenAPI内容或完全无效的YAML/JSON",
            2: "有OpenAPI片段但语法错误多，缺少必要顶级字段",
            3: "基本有效的OpenAPI结构，有paths和基本components，但有少量schema错误",
            4: "语法正确的OpenAPI 3.x规范，有完整paths/components/servers/info",
            5: "完美的OpenAPI 3.1规范：完全符合规范，所有$ref正确，schemas完整可校验，有example和description",
        },
    ),
    DimensionSpec(
        name="risk_awareness",
        weight=0.10,
        description="风险意识：是否明确错误码、边界条件、降级方案、安全风险",
        anchors={
            1: "完全未考虑错误和风险",
            2: "列出了少量常见错误，但无处理方案",
            3: "有基本错误码定义，考虑了主要边界情况",
            4: "明确了主要错误场景和错误码，有基本降级思路",
            5: "全面风险覆盖：每个端点有详细错误码表，明确边界条件/并发问题/安全风险/降级策略/回滚方案",
        },
    ),
]

# 设计文档 5 维度
DESIGN_DOC_DIMENSIONS: list[DimensionSpec] = [
    DimensionSpec(
        name="architecture_clarity",
        weight=0.25,
        description="架构描述清晰度，组件关系明确，分层合理",
        anchors={
            1: "架构模糊不清，无组件图或分层说明",
            2: "有基本架构描述但组件关系混乱",
            3: "架构清晰，主要组件和关系有说明",
            4: "架构清晰，组件/模块/层次关系明确，有决策理由",
            5: "极其清晰：完整的架构视图，组件职责单一，接口契约明确，每个决策有trade-off分析",
        },
    ),
    DimensionSpec(
        name="tech_stack_rational",
        weight=0.20,
        description="技术栈选型合理性和论证",
        anchors={
            1: "无技术选型或选型完全无理由",
            2: "列出技术栈但无论证或论证薄弱",
            3: "主要技术选型有基本理由",
            4: "技术选型有对比分析和明确理由",
            5: "技术选型有详细的多方案对比、trade-off分析、团队能力/运维成本/生态考虑",
        },
    ),
    DimensionSpec(
        name="completeness",
        weight=0.20,
        description="设计文档完整性：架构/数据模型/接口/部署/监控等",
        anchors={
            1: "大量必需章节缺失",
            2: "覆盖部分章节但核心内容不全",
            3: "主要章节齐全",
            4: "所有核心章节完整，包含部署/监控/安全考虑",
            5: "极其完整：架构/数据模型/API/部署/监控/安全/容灾/扩展路线图全部覆盖",
        },
    ),
    DimensionSpec(
        name="risk_coverage",
        weight=0.20,
        description="风险识别和缓解方案",
        anchors={
            1: "未识别任何风险",
            2: "识别少量风险但无缓解方案",
            3: "识别主要风险并有基本缓解思路",
            4: "风险识别全面，每个风险有缓解措施",
            5: "全面风险矩阵：技术/业务/运维/安全/人员风险，每个有概率/影响/缓解/预案",
        },
    ),
    DimensionSpec(
        name="scalability",
        weight=0.15,
        description="可扩展性设计：水平扩展/性能/容量规划",
        anchors={
            1: "完全未考虑扩展性",
            2: "提及扩展性但无具体方案",
            3: "有基本扩展思路",
            4: "有明确的扩展方案和性能考虑",
            5: "详细的容量规划/扩展策略/性能指标/SLA/瓶颈分析",
        },
    ),
]

# 调研报告 5 维度
RESEARCH_REPORT_DIMENSIONS: list[DimensionSpec] = [
    DimensionSpec(
        name="evidence_quality",
        weight=0.25,
        description="证据质量：来源可靠性、数据支撑、引用规范",
        anchors={
            1: "无证据来源，全是主观断言",
            2: "有少量来源但不可靠或未引用",
            3: "主要结论有基本来源支撑",
            4: "结论有可靠来源，数据有出处",
            5: "每个关键结论有多源交叉验证，数据精确可追溯，引用规范",
        },
    ),
    DimensionSpec(
        name="analysis_depth",
        weight=0.25,
        description="分析深度：不只是罗列信息，有深入比较和洞察",
        anchors={
            1: "只有信息罗列，无分析",
            2: "有表面比较但缺深入分析",
            3: "有基本分析和对比",
            4: "分析深入，有对比表格和洞察",
            5: "深度分析：多维度对比矩阵，SWOT分析，趋势洞察，反直觉发现",
        },
    ),
    DimensionSpec(
        name="completeness",
        weight=0.20,
        description="调研覆盖度：主要方案/技术/竞品是否覆盖",
        anchors={
            1: "严重遗漏主要方案",
            2: "覆盖部分主流方案但有明显遗漏",
            3: "覆盖主要方案",
            4: "覆盖全面，主流方案和新兴方案都有涉及",
            5: "极其全面：主流+小众+新兴方案，分类清晰，筛选标准明确",
        },
    ),
    DimensionSpec(
        name="recommendation_actionability",
        weight=0.20,
        description="建议可操作性：推荐方案明确，落地路径清晰",
        anchors={
            1: "无推荐或推荐完全模糊",
            2: "有推荐但无论证和落地路径",
            3: "推荐明确，有基本理由",
            4: "推荐有论证，有落地步骤",
            5: "推荐方案明确，有分阶段实施计划、风险、ROI分析、决策树",
        },
    ),
    DimensionSpec(
        name="source_diversity",
        weight=0.10,
        description="来源多样性：官方文档/学术论文/社区/实测数据等",
        anchors={
            1: "单一来源",
            2: "2-3个同类来源",
            3: "有多种类型来源",
            4: "来源类型多样，有官方/社区/实测",
            5: "极其多样：官方文档+学术论文+benchmark+社区反馈+实测验证+专家意见",
        },
    ),
]

# 商业分析 5 维度
BUSINESS_REPORT_DIMENSIONS: list[DimensionSpec] = [
    DimensionSpec(
        name="market_analysis_depth",
        weight=0.25,
        description="市场分析深度：市场规模/增长/竞品/定位",
        anchors={
            1: "无市场分析",
            2: "有市场描述但无数据支撑",
            3: "有基本市场数据和竞品分析",
            4: "市场规模/增长/竞品/差异化分析完整",
            5: "深度市场分析：TAM/SAM/SOM，竞品矩阵，定位分析，趋势预测",
        },
    ),
    DimensionSpec(
        name="financial_rigor",
        weight=0.20,
        description="财务分析严谨性：成本/收入/利润/投资回报",
        anchors={
            1: "无财务分析",
            2: "有粗略数字但无模型",
            3: "有基本财务预测",
            4: "有成本/收入/利润模型和敏感性分析",
            5: "详细财务模型：多情景预测，敏感性分析，盈亏平衡，现金流，ROI计算",
        },
    ),
    DimensionSpec(
        name="strategic_clarity",
        weight=0.20,
        description="战略清晰度：目标明确，路径清晰，里程碑可衡量",
        anchors={
            1: "战略模糊或缺失",
            2: "有方向但无具体目标",
            3: "有目标和基本路径",
            4: "战略清晰，有阶段目标和里程碑",
            5: "战略极其清晰：SMART目标，分阶段路线图，关键里程碑，成功指标",
        },
    ),
    DimensionSpec(
        name="completeness",
        weight=0.20,
        description="商业分析完整性：市场/产品/财务/风险/执行",
        anchors={
            1: "严重缺失关键章节",
            2: "覆盖部分内容",
            3: "主要内容齐全",
            4: "内容完整，覆盖市场/产品/财务/风险",
            5: "极其完整：市场/产品/GTM/财务/团队/风险/合规/退出策略全覆盖",
        },
    ),
    DimensionSpec(
        name="data_grounding",
        weight=0.15,
        description="数据支撑：关键论断有数据支撑而非臆测",
        anchors={
            1: "全是主观判断无数据",
            2: "有少量数据但来源不明",
            3: "主要论断有数据支撑",
            4: "关键数据有可靠来源",
            5: "每个关键论断都有可验证数据来源，数据可追溯",
        },
    ),
]

# 通用产出 5 维度（兜底）
GENERAL_DIMENSIONS: list[DimensionSpec] = [
    DimensionSpec(
        name="completeness",
        weight=0.25,
        description="内容完整性",
        anchors={1: "严重缺失", 2: "不完整", 3: "基本完整", 4: "完整", 5: "极其完整"},
    ),
    DimensionSpec(
        name="accuracy",
        weight=0.25,
        description="准确性",
        anchors={1: "大量错误", 2: "多处不准确", 3: "基本正确", 4: "准确", 5: "高度准确"},
    ),
    DimensionSpec(
        name="clarity",
        weight=0.20,
        description="清晰性和可读性",
        anchors={1: "无法理解", 2: "难以理解", 3: "基本清晰", 4: "清晰", 5: "极其清晰"},
    ),
    DimensionSpec(
        name="actionability",
        weight=0.20,
        description="可操作性",
        anchors={1: "无法使用", 2: "需要大量工作", 3: "基本可用", 4: "可直接使用", 5: "完美可执行"},
    ),
    DimensionSpec(
        name="depth",
        weight=0.10,
        description="深度",
        anchors={1: "极浅", 2: "表面", 3: "适中", 4: "深入", 5: "极其深入"},
    ),
]

# 维度映射表
DIMENSIONS_BY_TYPE: dict[str, list[DimensionSpec]] = {
    "prd_openapi": PRD_OPENAPI_DIMENSIONS,
    "design_doc": DESIGN_DOC_DIMENSIONS,
    "research_report": RESEARCH_REPORT_DIMENSIONS,
    "business_report": BUSINESS_REPORT_DIMENSIONS,
    "tech_spec": DESIGN_DOC_DIMENSIONS,
    "meeting_summary": GENERAL_DIMENSIONS,
    "architecture_decision": DESIGN_DOC_DIMENSIONS,
    "general": GENERAL_DIMENSIONS,
}


def get_dimensions(deliverable_type: str) -> list[DimensionSpec]:
    """获取指定产出类型的维度列表。"""
    return DIMENSIONS_BY_TYPE.get(deliverable_type, GENERAL_DIMENSIONS)


def deliverable_type_display_name(dtype: str) -> str:
    """获取产出类型的中文显示名。"""
    names = {
        "prd_openapi": "PRD+OpenAPI规范",
        "design_doc": "技术设计文档",
        "research_report": "调研报告",
        "business_report": "商业分析报告",
        "tech_spec": "技术规格说明",
        "meeting_summary": "会议纪要",
        "architecture_decision": "架构决策记录",
        "general": "通用文档",
    }
    return names.get(dtype, dtype)
