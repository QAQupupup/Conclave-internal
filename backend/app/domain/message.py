"""发言/证据/决策模型：Message, Claim, Conflict, Evidence, EvidenceAssessment,
Decision, DecisionRecord, EvidenceSet。

从 app/models.py 迁移而来，原样保留，仅调整文件位置。
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.domain.enums import Role, ClaimType, ConflictType


class Message(BaseModel):
    """发言记录"""
    id: str
    meeting_id: str
    agent_role: Role
    stage: str
    content: str
    claim_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    created_at: datetime


class Claim(BaseModel):
    """结构化论点"""
    id: str
    agent_role: Role
    text: str
    claim_type: ClaimType
    evidence_ref: Optional[str] = None
    risk_level: Optional[str] = None


class Conflict(BaseModel):
    """冲突点"""
    id: str
    conflict_type: ConflictType
    summary: str
    side_a: str
    side_b: str


class Evidence(BaseModel):
    """检索到的证据片段"""
    id: str
    chunk_id: str
    quote: str
    source: str  # doc:section
    char_range: tuple[int, int]


class EvidenceAssessment(BaseModel):
    """证据与冲突的对照判断"""
    conflict_id: str
    evidence_id: str
    supports: str  # "a" | "b" | "neutral" | "irrelevant"


class Decision(BaseModel):
    """仲裁裁决"""
    conflict_id: str
    verdict: str  # "a" | "b" | "compromise"
    rationale: str


class DecisionRecord(BaseModel):
    """裁决记录集合"""
    decisions: list[Decision]
    adopted_claims: list[str]


class EvidenceSet(BaseModel):
    """单冲突的证据对照集合"""
    conflict_id: str
    assessments: list[EvidenceAssessment]
