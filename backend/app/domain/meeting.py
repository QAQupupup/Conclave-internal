"""会议核心模型：PRD, Artifact, Meeting, BorrowRequest, MeetingState。

从 app/models.py 迁移而来，原样保留，仅调整文件位置。
"""

from __future__ import annotations

import contextlib
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from app.agents.trace import CallTrace
from app.domain.enums import MeetingStatus, Role, Stage
from app.domain.message import Message
from conclave_core.charter import MeetingCharter
from conclave_core.conclusion_chain import ConclusionChain


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
    artifact: Artifact | None = None


class BorrowRequest(BaseModel):
    """借调三问表单"""

    id: str
    requester: Role
    target_role: str
    goal: str
    necessary: str
    no_loan_cost: str
    verdict: str | None = None  # reject|defer|approve_temporary|approve_frozen_scope


# ---------- 状态机状态对象 ----------


class MeetingCoreSection(BaseModel):
    """会议核心元信息（身份/状态/配置），分组字段。"""

    meeting_id: str
    topic: str
    stage: Stage
    status: MeetingStatus
    clarified_topic: str | None = None
    deliverable_type: str = "prd_openapi"
    flow_plan: str = "standard"
    debate_depth: str = "standard"
    dynamic_routing: bool = True
    model_override: str = ""
    owner_username: str | None = None
    owner_uid: str | None = None
    tenant_id: int | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    error_detail: str | None = None


class MeetingDebateSection(BaseModel):
    """辩论/讨论阶段相关数据。"""

    team_config: list[dict[str, Any]] = Field(default_factory=list)
    role_configs: list[dict[str, Any]] = Field(default_factory=list)
    key_questions: list[str] = Field(default_factory=list)
    messages: list[dict[str, Any]] = Field(default_factory=list)
    injected_messages: list[dict[str, Any]] = Field(default_factory=list)
    intervention_messages: list[dict[str, Any]] = Field(default_factory=list)
    team_conclusions: list[dict[str, Any]] = Field(default_factory=list)
    claims: list[dict[str, Any]] = Field(default_factory=list)
    conflicts: list[dict[str, Any]] = Field(default_factory=list)
    evidence_set: list[dict[str, Any]] = Field(default_factory=list)
    prefetched_evidence: dict[str, list[dict]] | None = None
    drift_log: list[dict[str, Any]] = Field(default_factory=list)
    user_rejections: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)


class MeetingBorrowSection(BaseModel):
    """Agent 借调相关状态。"""

    borrowed_agents: list[dict[str, Any]] = Field(default_factory=list)
    auto_borrow_count: int = 0
    pending_borrow_request: dict[str, Any] | None = None
    borrow_frozen: bool = False
    borrow_request_history: list[dict[str, Any]] = Field(default_factory=list)


class MeetingIterationSection(BaseModel):
    """迭代/质量门禁相关状态。"""

    iteration_count: int = 0
    max_iterations: int = 2
    quality_score: float | None = None
    quality_feedback: str | None = None
    iteration_history: list[dict[str, Any]] = Field(default_factory=list)
    auto_iterate: bool = False
    checkpoint: dict[str, Any] | None = None
    stage_retry_count: dict[str, int] = Field(default_factory=dict)
    max_stage_retries: int = 2


class MeetingObservabilitySection(BaseModel):
    """可观测性与审计数据。"""

    decision_record: dict[str, Any] | None = None
    artifact: dict[str, Any] | None = None
    doc_summaries: list[str] = Field(default_factory=list)
    reference_meeting_ids: list[str] = Field(default_factory=list)
    reference_context: str = ""
    charter: MeetingCharter | None = None
    conclusion_chain: ConclusionChain = Field(default_factory=ConclusionChain)
    llm_trace: CallTrace = Field(default_factory=CallTrace)
    confidence_flags: dict[str, str] = Field(default_factory=dict)
    agent_evaluations: dict[str, Any] | None = None
    resolved_models: dict[str, str] = Field(default_factory=dict)
    paused_snapshot: dict[str, Any] | None = None
    participants: list[str] = Field(default_factory=list)


class MeetingState(BaseModel):
    """状态机运行态（见 §1.4）

    各节点以纯函数风格读写该对象，副作用通过事件总线外溢。
    """

    meeting_id: str
    topic: str
    stage: Stage = Stage.CLARIFY
    status: MeetingStatus = MeetingStatus.RUNNING
    clarified_topic: str | None = None
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
    decision_record: dict[str, Any] | None = None
    artifact: dict[str, Any] | None = None
    # 产出类型（创建会议时指定，produce 阶段据此切换模板）
    deliverable_type: str = "prd_openapi"
    # 议题执行模式（flow_plan）：Runner 据此决定走 instant 还是 standard 六阶段管线
    # "instant" = 即时回答模式（单次 LLM 直接回答，跳过六阶段）
    # "standard" = 标准会议模式（完整六阶段管线）
    # "plan" = 先制定计划再逐步执行
    # "simple" = 简化路由（映射到 instant）
    # 兼容旧值："fast"/"fast_path"→instant, "deep_think"/"full"→standard
    flow_plan: str = "standard"
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
    paused_snapshot: dict[str, Any] | None = None
    doc_summaries: list[str] = Field(default_factory=list)  # 上传资料摘要
    reference_meeting_ids: list[str] = Field(default_factory=list)  # 引用的历史会议 ID 列表
    reference_context: str = ""  # 引用会议摘要文本（注入 prompt）
    # 会议宪章（clarify 阶段构造，作为后续阶段防漂移的不变锚点）
    charter: MeetingCharter | None = None
    # 漂移检查日志（非阻塞，记录每条发言的 drift 判定）
    drift_log: list[dict[str, Any]] = Field(default_factory=list)
    # 第2层：结论锁定链（记录每阶段锁定结论，供后续引用和一致性校验）
    conclusion_chain: ConclusionChain = Field(default_factory=ConclusionChain)
    # 第4层：LLM 调用追踪（仅 RealLLM 记录调用，stub 为空记录）
    llm_trace: CallTrace = Field(default_factory=CallTrace)
    # 第5层：置信度标记（stage -> "high"|"low"|"fallback"）
    confidence_flags: dict[str, str] = Field(default_factory=dict)
    # ADR-010: cross_team 质量门禁决策历史
    # 每项: {"round": 1, "decision": "pass|supplement|re_examine", "reason": "...", "target_roles": [...]}
    gate_history: list[dict[str, Any]] = Field(default_factory=list)
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
    pending_borrow_request: dict[str, Any] | None = None
    borrow_frozen: bool = False  # 是否冻结借调（用户选择不再允许借调）
    # 借调申请历史（含自动通过和用户审批的所有申请）
    borrow_request_history: list[dict[str, Any]] = Field(default_factory=list)
    # Agent 反馈评估结果（feedback.py evaluate_agents 写入）
    # {role: {"adoption_rate": float, "evidence_accuracy": float, "overall_score": float, ...}}
    agent_evaluations: dict[str, Any] | None = None
    # 流水线优化：cross_team 阶段预检索的证据（evidence_check 优先使用）
    # 格式: {conflict_id: [evidence_chunks]}
    # [UNIQ-07 修复] 原字段名 _prefetched_evidence（下划线前缀）不会被 Pydantic
    # 序列化，导致会议状态快照+SQLite 持久化时丢失该字段，进程重启后
    # evidence_check 节点需要重新检索。改为 prefetched_evidence（无下划线）。
    prefetched_evidence: dict[str, list[dict]] | None = Field(default=None)
    # Agent 拒绝权：用户注入消息后，Agent 可投票拒绝（需证据支撑，至少 2 票）
    # 格式: {message_id: [{"agent_role": "...", "evidence_refs": [...], "reason": "..."}]}
    user_rejections: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    # [AUDIT-FIX P0-2/P0-4] 新增：异常终态记录，用于审计可追溯性
    completed_at: datetime | None = None
    error_detail: str | None = None  # 节点异常或超时时记录错误信息
    # [SECURITY-FIX] 会议所有权：创建会议时记录创建者，用于访问控制
    owner_username: str | None = None
    owner_uid: str | None = None
    # [MULTI-TENANT] 租户隔离：会议所属租户 ID，用于内存状态访问校验
    tenant_id: int | None = None
    # 参与者列表（通过 WS 加入的用户）
    participants: list[str] = Field(default_factory=list)
    # === 断点续传 & 自我迭代支持 ===
    # checkpoint: 记录最近一次成功完成的阶段，用于断点恢复
    # 格式: {"stage": "produce", "completed_at": "...", "substep": "code_generated", "retry_count": 0}
    checkpoint: dict[str, Any] | None = None
    # stage_retry_count: 各阶段重试次数 {stage_name: int}
    stage_retry_count: dict[str, int] = Field(default_factory=dict)
    max_stage_retries: int = 2  # 每个阶段最大重试次数
    # === 自我迭代 Loop ===
    # iteration_count: 当前迭代轮次（0=首轮，1+=迭代轮）
    iteration_count: int = 0
    max_iterations: int = 2  # 最大迭代轮次（防止无限循环）
    # quality_score: 产出质量评分（0-100），由质量门禁评估
    quality_score: float | None = None
    quality_feedback: str | None = None  # 质量门禁的反馈意见（用于下一轮迭代）
    # iteration_history: 历次迭代记录 [{iteration, quality_score, feedback, changes}]
    iteration_history: list[dict[str, Any]] = Field(default_factory=list)
    # auto_iterate: 是否自动迭代直到质量达标（用户可设置）
    auto_iterate: bool = False

    # [SECURITY-FIX] 消息列表上限：超过此数量时裁剪最旧消息（保留上下文窗口）
    MAX_MESSAGES: int = 500

    def model_post_init(self, __context: Any) -> None:
        """初始化后确保 conclusion_chain 和 llm_trace 的 meeting_id 正确"""
        if not self.conclusion_chain.meeting_id:
            self.conclusion_chain.meeting_id = self.meeting_id
        if not self.llm_trace.meeting_id:
            self.llm_trace.meeting_id = self.meeting_id

    def append_message(self, msg: dict[str, Any]) -> None:
        """安全添加消息，超过上限时裁剪最旧消息"""
        self.messages.append(msg)
        if len(self.messages) > self.MAX_MESSAGES:
            # 保留最近的 MAX_MESSAGES 条消息，最旧的被裁剪
            # LLM 上下文构建时使用 state.messages[-N:]，裁剪不影响上下文质量
            excess = len(self.messages) - self.MAX_MESSAGES
            del self.messages[:excess]

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
        if aux.get("llm_trace"):
            with contextlib.suppress(Exception):
                self.llm_trace = CallTrace.model_validate(aux["llm_trace"])

        if aux.get("evidence_set"):
            self.evidence_set = list(aux["evidence_set"])

        if aux.get("conclusion_chain"):
            with contextlib.suppress(Exception):
                self.conclusion_chain = ConclusionChain.model_validate(aux["conclusion_chain"])

        if aux.get("borrowed_agents"):
            self.borrowed_agents = list(aux["borrowed_agents"])

    def snapshot_lite(self) -> dict[str, Any]:
        """生成轻量快照：排除 aux 大字段，用于热路径序列化。

        与 snapshot() 不同，此方法不包含 llm_trace / evidence_set /
        conclusion_chain / borrowed_agents 的实际数据。
        """
        data: dict[str, Any] = self.model_dump(mode="json")
        # 将大字段替换为占位标记，表明数据存储在 aux 表
        for key in self._AUX_KEYS:
            if key in data:
                data[key] = {"_aux": True}
        return data

    @property
    def sections(self) -> dict[str, BaseModel]:
        """按职责返回嵌套分组视图（向后兼容：不影响扁平字段访问）。

        返回 dict 而不是嵌套对象，是为了避免 Pydantic 双向同步问题；
        每次访问返回新对象（视图），用于日志/序列化/前端聚合输出场景。
        注意：返回的 section 是视图（拷贝），不要在其上修改以期反向写回 state。
        """
        return {
            "core": MeetingCoreSection(
                meeting_id=self.meeting_id,
                topic=self.topic,
                stage=self.stage,
                status=self.status,
                clarified_topic=self.clarified_topic,
                deliverable_type=self.deliverable_type,
                flow_plan=self.flow_plan,
                debate_depth=self.debate_depth,
                dynamic_routing=self.dynamic_routing,
                model_override=self.model_override,
                owner_username=self.owner_username,
                owner_uid=self.owner_uid,
                tenant_id=self.tenant_id,
                created_at=self.created_at,
                completed_at=self.completed_at,
                error_detail=self.error_detail,
            ),
            "debate": MeetingDebateSection(
                team_config=self.team_config,
                role_configs=self.role_configs,
                key_questions=self.key_questions,
                messages=self.messages,
                injected_messages=self.injected_messages,
                intervention_messages=self.intervention_messages,
                team_conclusions=self.team_conclusions,
                claims=self.claims,
                conflicts=self.conflicts,
                evidence_set=self.evidence_set,
                prefetched_evidence=self.prefetched_evidence,
                drift_log=self.drift_log,
                user_rejections=self.user_rejections,
            ),
            "borrow": MeetingBorrowSection(
                borrowed_agents=self.borrowed_agents,
                auto_borrow_count=self.auto_borrow_count,
                pending_borrow_request=self.pending_borrow_request,
                borrow_frozen=self.borrow_frozen,
                borrow_request_history=self.borrow_request_history,
            ),
            "iteration": MeetingIterationSection(
                iteration_count=self.iteration_count,
                max_iterations=self.max_iterations,
                quality_score=self.quality_score,
                quality_feedback=self.quality_feedback,
                iteration_history=self.iteration_history,
                auto_iterate=self.auto_iterate,
                checkpoint=self.checkpoint,
                stage_retry_count=self.stage_retry_count,
                max_stage_retries=self.max_stage_retries,
            ),
            "observability": MeetingObservabilitySection(
                decision_record=self.decision_record,
                artifact=self.artifact,
                doc_summaries=self.doc_summaries,
                reference_meeting_ids=self.reference_meeting_ids,
                reference_context=self.reference_context,
                charter=self.charter,
                conclusion_chain=self.conclusion_chain,
                llm_trace=self.llm_trace,
                confidence_flags=self.confidence_flags,
                agent_evaluations=self.agent_evaluations,
                resolved_models=self.resolved_models,
                paused_snapshot=self.paused_snapshot,
                participants=self.participants,
            ),
        }

    def snapshot(self) -> dict[str, Any]:
        """生成快照用于 pause 暂存 / WS 回放"""
        return self.model_dump(mode="json")  # type: ignore[no-any-return]

    def snapshot_sections(self) -> dict[str, dict[str, Any]]:
        """按 section 分组返回快照，用于 WS 增量推送 / 调试输出。

        与 snapshot() 的区别：
        - snapshot() 返回平铺字段（向后兼容）
        - snapshot_sections() 返回嵌套分组（前端可按 section 增量订阅）

        返回示例::
            {
                "core": {"meeting_id": "...", "stage": "clarify", ...},
                "debate": {"messages": [...], "claims": [...], ...},
                "borrow": {"borrowed_agents": [...], ...},
                "iteration": {"iteration_count": 0, ...},
                "observability": {"charter": {...}, ...},
            }
        """
        return {name: section.model_dump(mode="json") for name, section in self.sections.items()}
