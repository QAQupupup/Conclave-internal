# §2 LLM 结构化输出 Pydantic 模型
# 6 个输出模型，字段与 StubLLM 返回的 dict 结构完全对齐，
# 用于 RealLLM.complete() 的解析层校验（三明治模式）。
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------- 通用配置 ----------
# 校验时忽略 LLM 多输出的字段；缺字段由各自默认值兜底，保证解析层稳定。
_SCHEMA_CONFIG = ConfigDict(extra="ignore")


# ---------- 1. clarify ----------
class TeamMember(BaseModel):
    """团队组成单项"""
    model_config = _SCHEMA_CONFIG
    role: str
    stance: str = ""


class ClarifyResult(BaseModel):
    """Clarify 阶段输出：主持人澄清议题 + 议题路由

    flow_plan 字段实现议题路由：LLM 根据议题复杂度裁剪后续阶段。
    """
    model_config = _SCHEMA_CONFIG
    clarified_topic: str
    key_questions: list[str] = Field(default_factory=list)
    team_config: list[TeamMember] = Field(default_factory=list)
    # 议题路由：简单任务跳过中间阶段，直接产出
    # "simple" = 跳过 cross_team + evidence_check + arbitrate
    # "standard" = 跳过 evidence_check（无冲突时）
    # "full" = 完整六阶段（默认）
    complexity: str = "full"


# ---------- 2. intra_team ----------
class ClaimItem(BaseModel):
    """单条论点

    工程师会带 risk_level；架构师不带（保持 Optional）。
    type 取值：fact | assumption | constraint。
    """
    model_config = _SCHEMA_CONFIG
    claim: str
    evidence_ref: str = ""
    risk_level: Optional[str] = None
    type: str = "assumption"


class ClaimListResult(BaseModel):
    """IntraTeam 阶段输出：队内论点列表

    claims 为必填字段（非空校验）：LLM 漏输出 claims 时会触发 ValidationError，
    进入重试→降级 StubLLM 路径，保证 claims 不再静默丢失。
    """
    model_config = _SCHEMA_CONFIG
    claims: list[ClaimItem]


# ---------- 3. cross_team ----------
class ConflictItem(BaseModel):
    """单条冲突点

    type 取值：factual | preference | scope。
    nodes.py 会把 type 改名 conflict_type，这里保持与 StubLLM 对齐。
    """
    model_config = _SCHEMA_CONFIG
    id: str
    type: str = "preference"
    summary: str = ""
    side_a: str = ""
    side_b: str = ""


class ConflictListResult(BaseModel):
    """CrossTeam 阶段输出：冲突列表"""
    model_config = _SCHEMA_CONFIG
    conflicts: list[ConflictItem] = Field(default_factory=list)


# ---------- 4. evidence_check ----------
class EvidenceAssessmentItem(BaseModel):
    """单条证据对照判断

    supports: a | b | neutral | irrelevant
    strength: strong（文档/网络证据）| weak（通用知识）| none（无证据占位）
    """
    model_config = _SCHEMA_CONFIG
    evidence_id: str
    quote: str = ""
    source: str = ""
    supports: str = "neutral"  # a | b | neutral | irrelevant
    strength: str = "strong"    # strong | weak | none


class EvidenceCheckResult(BaseModel):
    """EvidenceCheck 阶段输出：单冲突的证据对照集合"""
    model_config = _SCHEMA_CONFIG
    conflict_id: str
    evidence_assessments: list[EvidenceAssessmentItem] = Field(default_factory=list)


# ---------- 5. arbitrate ----------
class DecisionItem(BaseModel):
    """单条裁决"""
    model_config = _SCHEMA_CONFIG
    conflict_id: str
    verdict: str = "compromise"  # a | b | compromise
    rationale: str = ""


class ArbitrateResult(BaseModel):
    """Arbitrate 阶段输出：裁决记录集合"""
    model_config = _SCHEMA_CONFIG
    decisions: list[DecisionItem] = Field(default_factory=list)
    adopted_claims: list[str] = Field(default_factory=list)


# ---------- 6. produce ----------
class PRDResult(BaseModel):
    """产品需求文档"""
    model_config = _SCHEMA_CONFIG
    title: str
    goal: str = ""
    scope: str = ""
    assumptions: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    api_endpoints: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)


class CodeAnalysisArtifact(BaseModel):
    """code_analysis 产出：数据分析代码

    关键字段 code 为必填，LLM 漏输出时校验失败触发重试。
    """
    model_config = _SCHEMA_CONFIG
    title: str = ""
    description: str = ""
    code: str  # 必填：分析代码
    expected_output: str = ""


class TestedSystemArtifact(BaseModel):
    """tested_system 产出：可测试代码系统

    关键字段 main_code / test_code 为必填。
    """
    model_config = _SCHEMA_CONFIG
    title: str = ""
    description: str = ""
    main_code: str  # 必填：实现代码
    test_code: str   # 必填：测试代码
    run_command: str = "python -m pytest test_generated.py -v"


class DeployableServiceArtifact(BaseModel):
    """deployable_service 产出：工业级可部署服务

    支持两种模式：
    1. 分层架构模式（默认）：project_tree 包含完整项目文件树，遵循 Controller/Service/DAO/Model/Schema 分层
    2. 单文件兼容模式（向后兼容）：app_code/dockerfile 等顶层字段提供单文件实现

    复杂度等级（complexity_level）：
    - "micro": 微工具（<10个文件），单文件FastAPI，无前端，SQLite
    - "small": 小型服务（10-20个文件），基础分层，简单HTML前端，SQLite
    - "medium": 中型服务（20-50个文件），完整分层+React前端+PostgreSQL+测试+Alembic迁移
    - "large": 大型服务（50+文件），微服务架构+多模块+完整测试+CI/CD+监控
    """
    model_config = _SCHEMA_CONFIG

    # === 基础元数据 ===
    title: str = ""
    description: str = ""
    complexity_level: str = "medium"  # micro|small|medium|large
    tech_stack: list[str] = Field(default_factory=list)
    port: int = 8000
    run_command: str = "uvicorn app.main:app --host 0.0.0.0 --port 8000"
    credentials: dict[str, str] = Field(default_factory=dict)

    # === 分层架构文件树（主力输出）===
    # 格式: {"app/main.py": "...", "app/routers/xxx.py": "...", "app/db/models/xxx.py": "...", ...}
    # 包含后端所有Python文件、配置文件、迁移脚本
    project_tree: dict[str, str] = Field(default_factory=dict)

    # === 前端React项目文件树 ===
    # 格式: {"frontend/src/App.tsx": "...", "frontend/package.json": "...", "frontend/Dockerfile": "..."}
    frontend_tree: dict[str, str] = Field(default_factory=dict)

    # === 测试文件树 ===
    # 格式: {"tests/test_api.py": "...", "tests/conftest.py": "..."}
    test_tree: dict[str, str] = Field(default_factory=dict)

    # === 部署文件（项目根目录）===
    # 格式: {"Dockerfile": "...", "docker-compose.yml": "...", "requirements.txt": "...", ".env.example": "...", "pyproject.toml": "..."}
    root_files: dict[str, str] = Field(default_factory=dict)

    # === 向后兼容字段（单文件模式，LLM可能只输出这些）===
    # 如果project_tree为空，produce节点会将这些字段组装成project_tree
    app_code: str = ""
    dockerfile: str = ""
    docker_compose: str = ""
    requirements_txt: str = ""
    readme: str = ""
    static_files: dict[str, str] = Field(default_factory=dict)

    def get_effective_tree(self) -> dict[str, str]:
        """获取最终生效的完整文件树（合并project_tree + 兼容字段）"""
        tree = dict(self.project_tree)
        # 如果project_tree为空，从兼容字段组装
        if not tree:
            if self.app_code:
                tree["app/main.py"] = self.app_code
            if self.requirements_txt:
                tree["requirements.txt"] = self.requirements_txt
            if self.dockerfile:
                tree["Dockerfile"] = self.dockerfile
            if self.docker_compose:
                tree["docker-compose.yml"] = self.docker_compose
            if self.readme:
                tree["README.md"] = self.readme
            for path, content in self.static_files.items():
                tree[path] = content
        # 合并root_files
        for path, content in self.root_files.items():
            tree[path] = content
        # 合并frontend_tree
        for path, content in self.frontend_tree.items():
            tree[path] = content
        # 合并test_tree
        for path, content in self.test_tree.items():
            tree[path] = content
        return tree

    def count_code_lines(self) -> int:
        """统计总代码行数（用于规模评估）"""
        total = 0
        for content in self.get_effective_tree().values():
            total += len(content.split("\n"))
        return total

    def count_files(self) -> int:
        """统计文件总数（用于规模评估）"""
        return len(self.get_effective_tree())


class ProduceResult(BaseModel):
    """Produce 阶段输出：PRD + OpenAPI（可选 code_analysis/tested_system/deployable_service）

    根据 deliverable_type 不同，LLM 返回的字段不同：
    - prd_openapi: prd + openapi
    - code_analysis: prd + openapi + code_analysis
    - tested_system: prd + openapi + tested_system
    - deployable_service: prd + openapi + deployable_service
    扩展字段使用具体 Pydantic 模型，关键字段缺失时触发校验失败→重试。
    """
    model_config = _SCHEMA_CONFIG
    prd: PRDResult
    openapi: str = ""
    # 可选产出字段（根据 deliverable_type 动态填充）
    code_analysis: Optional[CodeAnalysisArtifact] = None
    tested_system: Optional[TestedSystemArtifact] = None
    deployable_service: Optional[DeployableServiceArtifact] = None


# ---------- 6b. produce 子类型：非 PRD 产出 ----------
class DesignDocArtifact(BaseModel):
    """design_doc 产出：架构设计文档"""
    model_config = _SCHEMA_CONFIG
    title: str = ""
    overview: str = ""
    architecture: str = ""
    tech_stack: list[str] = Field(default_factory=list)
    data_model: str = ""
    api_design: str = ""
    deployment: str = ""
    risks: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)


class DesignDocResult(BaseModel):
    """Produce 阶段输出：架构设计文档"""
    model_config = _SCHEMA_CONFIG
    design_doc: DesignDocArtifact


class ComprehensiveArtifact(BaseModel):
    """comprehensive 产出：综合设计文档"""
    model_config = _SCHEMA_CONFIG
    title: str = ""
    requirements: dict[str, Any] = Field(default_factory=dict)
    system_design: dict[str, Any] = Field(default_factory=dict)
    api_design: dict[str, Any] = Field(default_factory=dict)
    data_model: dict[str, Any] = Field(default_factory=dict)


class ComprehensiveResult(BaseModel):
    """Produce 阶段输出：综合设计文档"""
    model_config = _SCHEMA_CONFIG
    comprehensive: ComprehensiveArtifact


class ResearchReportArtifact(BaseModel):
    """research_report 产出：调研报告"""
    model_config = _SCHEMA_CONFIG
    title: str = ""
    summary: str = ""
    findings: list[dict[str, Any]] = Field(default_factory=list)
    analysis: str = ""
    recommendations: list[str] = Field(default_factory=list)
    references: list[str] = Field(default_factory=list)


class ResearchReportResult(BaseModel):
    """Produce 阶段输出：调研报告"""
    model_config = _SCHEMA_CONFIG
    research_report: ResearchReportArtifact


class BusinessReportArtifact(BaseModel):
    """business_report 产出：商业报告"""
    model_config = _SCHEMA_CONFIG
    title: str = ""
    executive_summary: str = ""
    market_analysis: str = ""
    financial_projection: str = ""
    risk_assessment: str = ""
    strategic_recommendation: str = ""
    next_steps: list[str] = Field(default_factory=list)


class BusinessReportResult(BaseModel):
    """Produce 阶段输出：商业报告"""
    model_config = _SCHEMA_CONFIG
    business_report: BusinessReportArtifact


# ---------- schema_hint -> 模型映射 ----------
# RealLLM.complete() 依据 schema_hint 选择对应模型做 model_validate。
# produce 阶段使用 (stage, subtype) 二级键：produce_{deliverable_type}
SCHEMA_MAP: dict[str, type[BaseModel]] = {
    "clarify": ClarifyResult,
    "intra_team": ClaimListResult,
    "cross_team": ConflictListResult,
    "evidence_check": EvidenceCheckResult,
    "arbitrate": ArbitrateResult,
    # produce 子类型：每种 deliverable_type 对应独立模型
    "produce_prd_openapi": ProduceResult,
    "produce_code_analysis": ProduceResult,
    "produce_tested_system": ProduceResult,
    "produce_deployable_service": ProduceResult,
    "produce_design_doc": DesignDocResult,
    "produce_comprehensive": ComprehensiveResult,
    "produce_research_report": ResearchReportResult,
    "produce_business_report": BusinessReportResult,
    # 向后兼容：纯 "produce" 映射到默认 PRD 模型
    "produce": ProduceResult,
}
