# §3 核心 Pydantic 模型
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

from app.agents.trace import CallTrace
from conclave_core.charter import MeetingCharter
from conclave_core.conclusion_chain import ConclusionChain


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
    FAILED = "failed"  # [AUDIT-FIX P0-2/P0-4] 新增：节点异常或超时时的终态


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
    # 角色配置：从 agent_roles 表加载的完整角色定义列表
    # 每项: {id, display_name, perspective, expertise_domains, risk_appetite,
    #        default_stance, evidence_preference, model_override, background_brief,
    #        prompt_template}
    role_configs: list[dict[str, Any]] = Field(default_factory=list)
    key_questions: list[str] = Field(default_factory=list)
    messages: list[dict[str, Any]] = Field(default_factory=list)  # 发言记录
    injected_messages: list[dict[str, Any]] = Field(default_factory=list)
    # 用户介入对话：用户↔主持人 1v1 私密对话历史
    # 每项: {id, sender: "user"|"moderator", content, reply_to_id?, timestamp}
    intervention_messages: list[dict[str, Any]] = Field(default_factory=list)
    team_conclusions: list[dict[str, Any]] = Field(default_factory=list)  # 队内结论
    claims: list[dict[str, Any]] = Field(default_factory=list)
    conflicts: list[dict[str, Any]] = Field(default_factory=list)
    evidence_set: list[dict[str, Any]] = Field(default_factory=list)
    decision_record: Optional[dict[str, Any]] = None
    artifact: Optional[dict[str, Any]] = None
    # 产出类型（创建会议时指定，produce 阶段据此切换模板）
    deliverable_type: str = "prd_openapi"
    # 议题路由计划：clarify 阶段 LLM 输出，Runner 据此裁剪后续阶段
    # "full" = 完整六阶段 / "standard" = 无冲突时跳过 evidence_check / "simple" = 跳过中间三阶段
    # "plan" = 先制定计划再逐步执行（Planner → 按计划分步执行）
    # "fast" = 快速路径（单次 LLM 直接回答，跳过六阶段）
    flow_plan: str = "full"
    # 辩论深度：轻量(light) / 标准(standard) / 深度(deep)
    # - light: 2-3 Agents, 1 轮队内发言, 跳过跨队辩论和证据核验
    # - standard: 3-5 Agents, 2-3 轮辩论, 标准流程
    # - deep: 5+ Agents, 完整多轮辩论, 证据核验 + 仲裁
    debate_depth: str = "standard"
    # 动态路由：是否启用元认知 Agent 决定下一阶段（替代固定六阶段顺序）
    dynamic_routing: bool = True
    # 会议级模型覆盖（创建会议时指定，空=使用 ENV 默认）
    # 格式: "provider_id:model_id" 或纯 "model_id"
    model_override: str = ""
    # 模型快照（会议启动时 resolve，运行时直接读取，不再动态 resolve）
    # 格式: {role_or_stage: "provider_id:model_id"}
    # key 可以是角色 id（如 "engineer"）或 @阶段名（如 "@arbitrate"）
    resolved_models: dict[str, str] = Field(default_factory=dict)
    paused_snapshot: Optional[dict[str, Any]] = None
    doc_summaries: list[str] = Field(default_factory=list)  # 上传资料摘要
    reference_meeting_ids: list[str] = Field(default_factory=list)  # 引用的历史会议 ID 列表
    reference_context: str = ""  # 引用会议摘要文本（注入 prompt）
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
    # 自动借调机制：主持人评估是否需要补充角色
    # 自动通过的借调次数（< 3 次时主持人自动审批，>= 3 次需用户确认）
    auto_borrow_count: int = 0
    # 待用户审批的借调申请（超过自动通过阈值后挂起）
    # 格式: {"id": "...", "target_role": "...", "goal": "...", "necessary": "...",
    #        "no_loan_cost": "...", "requested_by": "moderator", "requested_at": "..."}
    pending_borrow_request: Optional[dict[str, Any]] = None
    borrow_frozen: bool = False  # 是否冻结借调（用户选择不再允许借调）
    # 借调申请历史（含自动通过和用户审批的所有申请）
    borrow_request_history: list[dict[str, Any]] = Field(default_factory=list)
    # Agent 反馈评估结果（feedback.py evaluate_agents 写入）
    # {role: {"adoption_rate": float, "evidence_accuracy": float, "overall_score": float, ...}}
    agent_evaluations: Optional[dict[str, Any]] = None
    # 流水线优化：cross_team 阶段预检索的证据（evidence_check 优先使用）
    # 格式: {conflict_id: [evidence_chunks]}
    # [UNIQ-07 修复] 原字段名 _prefetched_evidence（下划线前缀）不会被 Pydantic
    # 序列化，导致会议状态快照+SQLite 持久化时丢失该字段，进程重启后
    # evidence_check 节点需要重新检索。改为 prefetched_evidence（无下划线）。
    prefetched_evidence: Optional[dict[str, list[dict]]] = Field(default=None)
    # Agent 拒绝权：用户注入消息后，Agent 可投票拒绝（需证据支撑，至少 2 票）
    # 格式: {message_id: [{"agent_role": "...", "evidence_refs": [...], "reason": "..."}]}
    user_rejections: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    # [AUDIT-FIX P0-2/P0-4] 新增：异常终态记录，用于审计可追溯性
    completed_at: Optional[datetime] = None
    error_detail: Optional[str] = None  # 节点异常或超时时记录错误信息

    def model_post_init(self, __context: Any) -> None:
        """初始化后确保 conclusion_chain 和 llm_trace 的 meeting_id 正确"""
        if not self.conclusion_chain.meeting_id:
            self.conclusion_chain.meeting_id = self.meeting_id
        if not self.llm_trace.meeting_id:
            self.llm_trace.meeting_id = self.meeting_id

    # ---------- Aux 大字段分离（MeetingState 瘦身）----------

    # 需要从热路径 payload 中分离的大字段名称列表
    _AUX_KEYS: tuple[str, ...] = ("llm_trace", "evidence_set", "conclusion_chain", "borrowed_agents")

    def extract_aux(self) -> dict[str, Any]:
        """将大字段提取到独立 dict，自身字段重置为默认值。

        返回的 dict 可单独持久化到 meeting_aux 表，避免序列化到主 payload JSON。
        调用后 self 中的对应字段被替换为空/默认值，大幅减小 snapshot() 体积。

        Returns:
            dict，key 为字段名，value 为该字段的 JSON 可序列化值
        """
        aux: dict[str, Any] = {}

        # llm_trace: CallTrace Pydantic 模型
        # 注意：llm_trace 需要持续累积所有 LLM 调用，不能重置为空，
        # 否则每次 persist 后之前的调用记录会丢失。
        aux["llm_trace"] = self.llm_trace.model_dump(mode="json")

        # evidence_set: list[dict]
        aux["evidence_set"] = list(self.evidence_set)
        self.evidence_set = []

        # conclusion_chain: ConclusionChain Pydantic 模型
        aux["conclusion_chain"] = self.conclusion_chain.model_dump(mode="json")
        self.conclusion_chain = ConclusionChain(meeting_id=self.meeting_id)

        # borrowed_agents: list[dict]
        aux["borrowed_agents"] = list(self.borrowed_agents)
        self.borrowed_agents = []

        return aux

    def inject_aux(self, aux: dict[str, Any]) -> None:
        """从 aux dict 恢复大字段到自身。

        向后兼容：如果某个 key 不存在于 aux 中，则保持当前值不变。

        Args:
            aux: extract_aux() 返回的 dict，或从 DB 加载的等效数据
        """
        if "llm_trace" in aux and aux["llm_trace"]:
            try:
                self.llm_trace = CallTrace.model_validate(aux["llm_trace"])
            except Exception:
                pass  # 数据损坏时保留默认空值

        if "evidence_set" in aux and aux["evidence_set"]:
            self.evidence_set = list(aux["evidence_set"])

        if "conclusion_chain" in aux and aux["conclusion_chain"]:
            try:
                self.conclusion_chain = ConclusionChain.model_validate(aux["conclusion_chain"])
            except Exception:
                pass

        if "borrowed_agents" in aux and aux["borrowed_agents"]:
            self.borrowed_agents = list(aux["borrowed_agents"])

    def snapshot_lite(self) -> dict[str, Any]:
        """生成轻量快照：排除 aux 大字段，用于热路径序列化。

        与 snapshot() 不同，此方法不包含 llm_trace / evidence_set /
        conclusion_chain / borrowed_agents 的实际数据。
        """
        data = self.model_dump(mode="json")
        # 将大字段替换为占位标记，表明数据存储在 aux 表
        for key in self._AUX_KEYS:
            if key in data:
                data[key] = {"_aux": True}
        return data

    def snapshot(self) -> dict[str, Any]:
        """生成快照用于 pause 暂存 / WS 回放"""
        return self.model_dump(mode="json")


# ---------- Agent 角色模型 ----------

class AgentRole(BaseModel):
    """Agent 角色定义：可从数据库加载、API 返回、LLM 生成"""
    id: str                                    # 英文标识，如 "fullstack_engineer"
    display_name: str                          # 中文名
    perspective: str = ""                      # 核心视角
    expertise_domains: list[str] = Field(default_factory=list)
    risk_appetite: str = "balanced"            # conservative | balanced | aggressive
    default_stance: str = ""                   # 默认立场
    evidence_preference: str = "balanced"      # 证据偏好
    model_override: str = ""                   # 留空则用全局 LLM
    background_brief: str = ""                 # 一句话背景
    prompt_template: str = ""                  # 完整 prompt 模板
    is_builtin: bool = False
    is_active: bool = True
    created_at: str = ""
    updated_at: str = ""

    @classmethod
    def from_db_row(cls, row: dict[str, Any]) -> "AgentRole":
        return cls(
            id=row["id"],
            display_name=row["display_name"],
            perspective=row.get("perspective", ""),
            expertise_domains=row.get("expertise_domains", []),
            risk_appetite=row.get("risk_appetite", "balanced"),
            default_stance=row.get("default_stance", ""),
            evidence_preference=row.get("evidence_preference", "balanced"),
            model_override=row.get("model_override", ""),
            background_brief=row.get("background_brief", ""),
            prompt_template=row.get("prompt_template", ""),
            is_builtin=bool(row.get("is_builtin", False)),
            is_active=bool(row.get("is_active", True)),
            created_at=row.get("created_at", ""),
            updated_at=row.get("updated_at", ""),
        )


class AgentRoleListResponse(BaseModel):
    """角色列表响应"""
    roles: list[AgentRole]
    total: int
