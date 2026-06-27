# §3 核心 Pydantic 模型
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

from app.agents.trace import CallTrace
from app.orchestrator.charter import MeetingCharter
from app.orchestrator.conclusion_chain import ConclusionChain


# ---------- 枚举 ----------

class Role(str, Enum):
    """会议角色"""
    MODERATOR = "moderator"
    PRODUCT_ARCHITECT = "product_architect"
    ENGINEER = "engineer"
    SECURITY_EXPERT = "security_expert"
    DATA_ENGINEER = "data_engineer"
    UX_DESIGNER = "ux_designer"
    MARKETING_EXPERT = "marketing_expert"


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
    # 产出类型（创建会议时指定，produce 阶段据此切换模板）
    deliverable_type: str = "prd_openapi"
    paused_snapshot: Optional[dict[str, Any]] = None
    doc_summaries: list[str] = Field(default_factory=list)  # 上传资料摘要
    # 会议宪章（clarify 阶段构造，作为后续阶段防漂移的不变锚点）
    charter: Optional[MeetingCharter] = None
    # 漂移检查日志（非阻塞，记录每条发言的 drift 判定）
    drift_log: list[dict[str, Any]] = Field(default_factory=list)
    # 第2层：结论锁定链（记录每阶段锁定结论，供后续引用和一致性校验）
    conclusion_chain: ConclusionChain = Field(default_factory=ConclusionChain)
    # 第4层：LLM 调用追踪（仅 RealLLM 记录调用，stub 为空记录）
    llm_trace: CallTrace = Field(default_factory=CallTrace)
    # 第5层：置信度标记（stage -> "high"|"low"|"fallback"）
    confidence_flags: dict[str, str] = Field(default_factory=dict)
    # 借调的 agent 列表（loan 信号裁决通过后追加，待发言）
    # 每项: {"role": "security_expert", "verdict": "approve_temporary",
    #        "spoken": False, "request": {...}}
    borrowed_agents: list[dict[str, Any]] = Field(default_factory=list)
    # 流水线优化：cross_team 阶段预检索的证据（evidence_check 优先使用）
    # 格式: {conflict_id: [evidence_chunks]}
    _prefetched_evidence: Optional[dict[str, list[dict]]] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def model_post_init(self, __context: Any) -> None:
        """初始化后确保 conclusion_chain 和 llm_trace 的 meeting_id 正确"""
        if not self.conclusion_chain.meeting_id:
            self.conclusion_chain.meeting_id = self.meeting_id
        if not self.llm_trace.meeting_id:
            self.llm_trace.meeting_id = self.meeting_id

    def snapshot(self) -> dict[str, Any]:
        """生成快照用于 pause 暂存 / WS 回放"""
        return self.model_dump(mode="json")
