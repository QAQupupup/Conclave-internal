# §3 核心 Pydantic 模型
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# ---------- 枚举 ----------

class Role(str, Enum):
    """会议角色"""
    MODERATOR = "moderator"
    PRODUCT_ARCHITECT = "product_architect"
    ENGINEER = "engineer"


class ClaimType(str, Enum):
    """论点类型"""
    FACT = "fact"
    ASSUMPTION = "assumption"
    CONSTRAINT = "constraint"


class ConflictType(str, Enum):
    """冲突类型"""
    FACTUAL = "factual"
    PREFERENCE = "preference"
    SCOPE = "scope"


class Stage(str, Enum):
    """状态机六阶段"""
    CLARIFY = "clarify"
    INTRA_TEAM = "intra_team"
    CROSS_TEAM = "cross_team"
    EVIDENCE_CHECK = "evidence_check"
    ARBITRATE = "arbitrate"
    PRODUCE = "produce"


class MeetingStatus(str, Enum):
    """会议运行状态"""
    RUNNING = "running"
    PAUSED = "paused"
    ABORTED = "aborted"
    DONE = "done"


# ---------- 业务模型 ----------

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


class PRD(BaseModel):
    """产品需求文档"""
    title: str
    goal: str
    scope: str
    assumptions: list[str]
    constraints: list[str]
    api_endpoints: list[str]
    open_questions: list[str]


class Artifact(BaseModel):
    """会议产出物：PRD + OpenAPI"""
    meeting_id: str
    prd: PRD
    openapi: str


class Meeting(BaseModel):
    """会议聚合根（对外视图）"""
    id: str
    topic: str
    status: str
    stage: str
    created_at: datetime
    messages: list[Message] = Field(default_factory=list)
    artifact: Optional[Artifact] = None


class BorrowRequest(BaseModel):
    """借调三问表单"""
    id: str
    requester: Role
    target_role: str
    goal: str
    necessary: str
    no_loan_cost: str
    verdict: Optional[str] = None  # reject|defer|approve_temporary|approve_frozen_scope


# ---------- 状态机状态对象 ----------

class MeetingState(BaseModel):
    """状态机运行态（见 §1.4）

    各节点以纯函数风格读写该对象，副作用通过事件总线外溢。
    """
    meeting_id: str
    topic: str
    stage: Stage = Stage.CLARIFY
    status: MeetingStatus = MeetingStatus.RUNNING
    clarified_topic: Optional[str] = None
    team_config: list[dict[str, Any]] = Field(default_factory=list)  # [{role, stance}]
    key_questions: list[str] = Field(default_factory=list)
    messages: list[dict[str, Any]] = Field(default_factory=list)  # 发言记录
    injected_messages: list[dict[str, Any]] = Field(default_factory=list)
    team_conclusions: list[dict[str, Any]] = Field(default_factory=list)  # 队内结论
    claims: list[dict[str, Any]] = Field(default_factory=list)
    conflicts: list[dict[str, Any]] = Field(default_factory=list)
    evidence_set: list[dict[str, Any]] = Field(default_factory=list)
    decision_record: Optional[dict[str, Any]] = None
    artifact: Optional[dict[str, Any]] = None
    paused_snapshot: Optional[dict[str, Any]] = None
    doc_summaries: list[str] = Field(default_factory=list)  # 上传资料摘要
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def snapshot(self) -> dict[str, Any]:
        """生成快照用于 pause 暂存 / WS 回放"""
        return self.model_dump(mode="json")
