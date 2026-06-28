# §2 LLM 结构化输出 Pydantic 模型
# 6 个输出模型，字段与 StubLLM 返回的 dict 结构完全对齐，
# 用于 RealLLM.complete() 的解析层校验（三明治模式）。
from __future__ import annotations

from typing import Optional

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
    """Clarify 阶段输出：主持人澄清议题"""
    model_config = _SCHEMA_CONFIG
    clarified_topic: str
    key_questions: list[str] = Field(default_factory=list)
    team_config: list[TeamMember] = Field(default_factory=list)


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


class ProduceResult(BaseModel):
    """Produce 阶段输出：PRD + OpenAPI"""
    model_config = _SCHEMA_CONFIG
    prd: PRDResult
    openapi: str


# ---------- schema_hint -> 模型映射 ----------
# RealLLM.complete() 依据 schema_hint 选择对应模型做 model_validate。
SCHEMA_MAP: dict[str, type[BaseModel]] = {
    "clarify": ClarifyResult,
    "intra_team": ClaimListResult,
    "cross_team": ConflictListResult,
    "evidence_check": EvidenceCheckResult,
    "arbitrate": ArbitrateResult,
    "produce": ProduceResult,
}
