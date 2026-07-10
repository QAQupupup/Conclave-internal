// 镜像后端事件 schema 的 TypeScript 类型定义
// 对齐 backend/app/models.py 与 backend/app/events.py
// 前端所有 WS 事件、REST 响应均以此处类型为准

// ---------- 枚举（镜像 backend/app/models.py 的 str Enum）----------

/** 会议角色 */
export type Role =
  | 'moderator'
  | 'product_architect'
  | 'engineer'
  | 'security_expert'
  | 'data_engineer'
  | 'ux_designer'
  | 'marketing_expert'

/** 状态机六阶段 */
export type Stage =
  | 'clarify'
  | 'intra_team'
  | 'cross_team'
  | 'evidence_check'
  | 'arbitrate'
  | 'produce'

/** 会议运行状态 */
export type MeetingStatus = 'running' | 'paused' | 'aborted' | 'done'

/** 冲突类型 */
export type ConflictType = 'factual' | 'preference' | 'scope'

/** 论点类型 */
export type ClaimType = 'fact' | 'assumption' | 'constraint'

/** 证据支持方向 */
export type Supports = 'a' | 'b' | 'neutral' | 'irrelevant'

// 六阶段顺序（用于进度条高亮计算）
export const STAGE_ORDER: readonly Stage[] = [
  'clarify',
  'intra_team',
  'cross_team',
  'evidence_check',
  'arbitrate',
  'produce',
]

// 阶段中文标签
export const STAGE_LABELS: Record<Stage, string> = {
  clarify: '澄清议题',
  intra_team: '队内发言',
  cross_team: '跨队辩论',
  evidence_check: '证据对照',
  arbitrate: '仲裁裁决',
  produce: '产出物',
}

// 角色中文标签 + 配置（图标、糖果色、bias 标签）
export interface RoleMeta {
  label: string        // 中文名
  en: string           // 英文ID显示（短，用于节点副标签）
  bias: string         // 决策偏置标签（如 feasibility-first）
  candy: string        // 糖果色（低饱和，用于节点左侧色条/小圆点）
  candySoft: string    // 糖果色极浅版（用于节点背景）
  icon: string         // SVG path（简洁线性图标，非emoji）
}

export const ROLE_META: Record<Role, RoleMeta> = {
  moderator: {
    label: '主持人',
    en: 'moderator',
    bias: '中立',
    candy: '#8B8FC8',
    candySoft: '#F0F1FA',
    // 天平：简洁横线 + 两端小盘 + 支柱
    icon: 'M2 5h12M8 2v3M4 5l-2 4h4l-2-4M12 5l-2 4h4l-2-4M8 9v4',
  },
  product_architect: {
    label: '产品架构师',
    en: 'product_arch',
    bias: '价值导向',
    candy: '#B07FD1',
    candySoft: '#F6EFFA',
    // 靶心：同心圆
    icon: 'M8 3a5 5 0 100 10A5 5 0 008 3zm0 3a2 2 0 100 4 2 2 0 000-4z',
  },
  engineer: {
    label: '工程师',
    en: 'engineer',
    bias: '可行性',
    candy: '#5EAD8F',
    candySoft: '#ECF6F1',
    // 扳手（简洁版）
    icon: 'M10 3a3 3 0 00-3 3v1L3 11l2 2 4-4h1a3 3 0 003-3L10 3z',
  },
  security_expert: {
    label: '安全专家',
    en: 'security',
    bias: '安全优先',
    candy: '#D98A8A',
    candySoft: '#FAF0F0',
    // 盾牌
    icon: 'M8 2L3 4v4c0 4 2.5 6 5 7 2.5-1 5-3 5-7V4L8 2z',
  },
  data_engineer: {
    label: '数据工程师',
    en: 'data_eng',
    bias: '数据驱动',
    candy: '#6BA5C4',
    candySoft: '#ECF4F8',
    // 柱状图
    icon: 'M3 12h10M5 12V8M8 12V5M11 12V7',
  },
  ux_designer: {
    label: 'UX 设计师',
    en: 'ux_design',
    bias: '体验优先',
    candy: '#D9A86C',
    candySoft: '#FAF3EA',
    // 画笔
    icon: 'M3 13l2-1 8-8-2-2-8 8-1 3h1zM10 4l2 2',
  },
  marketing_expert: {
    label: '市场专家',
    en: 'marketing',
    bias: '增长导向',
    candy: '#C994B5',
    candySoft: '#F8EFF5',
    // 喇叭
    icon: 'M3 8l5-4v10L3 10V8zm6-3a4 4 0 010 8',
  },
}

// 兼容旧代码：ROLE_LABELS 映射
export const ROLE_LABELS: Record<Role, string> = {
  moderator: ROLE_META.moderator.label,
  product_architect: ROLE_META.product_architect.label,
  engineer: ROLE_META.engineer.label,
  security_expert: ROLE_META.security_expert.label,
  data_engineer: ROLE_META.data_engineer.label,
  ux_designer: ROLE_META.ux_designer.label,
  marketing_expert: ROLE_META.marketing_expert.label,
}

// ---------- 业务子结构 ----------

/** 团队组成项：{role, stance} */
export interface TeamMember {
  role: Role
  stance: string
}

/** 发言记录（GET /meetings/:id 的 messages[] 元素，及 snapshot.messages[]） */
export interface MeetingMessage {
  id: string
  meeting_id: string
  agent_role: Role
  stage: Stage
  content: string
  claim_refs: string[]
  evidence_refs: string[]
  created_at: string
}

/** 结构化论点 */
export interface Claim {
  id?: string
  agent_role?: Role
  text: string
  claim_type?: ClaimType
  evidence_ref?: string | null
  risk_level?: string | null
  type?: ClaimType
}

/** 冲突点 */
export interface Conflict {
  id: string
  conflict_type?: ConflictType
  type?: ConflictType
  summary: string
  side_a: string
  side_b: string
}

/** 证据评估条目 */
export interface EvidenceAssessment {
  conflict_id?: string
  evidence_id?: string
  quote?: string
  source?: string
  supports?: Supports
}

/** 单冲突的证据对照集合 */
export interface EvidenceSet {
  conflict_id: string
  assessments: EvidenceAssessment[]
}

/** 仲裁裁决单条 */
export interface Decision {
  conflict_id: string
  verdict: 'a' | 'b' | 'compromise'
  rationale: string
}

/** 裁决记录 */
export interface DecisionRecord {
  decisions: Decision[]
  adopted_claims: string[]
}

/** PRD 结构 */
export interface PRD {
  title?: string
  goal?: string
  scope?: string
  assumptions?: string[]
  constraints?: string[]
  api_endpoints?: string[]
  open_questions?: string[]
}

/** 会议产出物 */
export interface Artifact {
  meeting_id?: string
  prd?: PRD
  openapi?: string
  /** 产出物类型：prd_openapi / code_analysis / tested_system / deployable_service */
  deliverable_type?: string
  /** 产出文件附件列表（由 produce 节点扫描工作区生成） */
  attachments?: Array<{
    filename: string
    path: string
    size?: number
    ext?: string
    meeting_id?: string
  }>
}

// ---------- 领域事件信封 ----------

/** DomainEvent 信封：WS 推送的业务事件统一格式 */
export interface DomainEvent<T extends string = string, P = unknown> {
  type: T
  meeting_id: string
  payload: P
  ts: string
  trace_id?: string | null
}

// ---------- 各事件 payload ----------

export interface MeetingCreatedPayload {
  meeting_id: string
  topic: string
}

export interface StageChangedPayload {
  meeting_id: string
  from: Stage
  to: Stage
}

export interface AgentSpokePayload {
  meeting_id: string
  role: Role
  stage: Stage
  content: string
  claim_refs: string[]
  message_id: string
}

export interface EvidenceAttachedPayload {
  meeting_id: string
  conflict_id: string
  quote: string
  source: string
  supports?: Supports
}

export interface ArtifactGeneratedPayload {
  meeting_id: string
  prd: PRD
  openapi: string
}

/** control.signal 业务事件（服务端处理后的回执，经事件总线广播） */
export interface ControlSignalPayload {
  signal: string
  status: MeetingStatus
  payload?: Record<string, unknown>
}

/** 介入回复事件：主持人回复用户介入消息 */
export interface InterventionReplyPayload {
  meeting_id: string
  message: InterventionMessage
  intervention_messages: InterventionMessage[]
}

/** 自动批准借调事件 */
export interface BorrowAutoApprovedPayload {
  meeting_id: string
  request_id: string
  target_role: string
  target_role_name: string
  goal: string
  auto_borrow_count: number
}

/** 等待用户审批借调事件 */
export interface BorrowAwaitingUserPayload {
  meeting_id: string
  request_id: string
  target_role: string
  target_role_name: string
  goal: string
  necessary: string
  no_loan_cost: string
  auto_borrow_count: number
}

// ---------- WS 控制帧（非 DomainEvent，由后端直接 JSON 发送） ----------

/** 连接时回放的会议快照 */
export interface SnapshotFrame {
  type: 'snapshot'
  meeting_id: string
  payload: MeetingState
}

/** 历史事件回放结束标记 */
export interface ReplayDoneFrame {
  type: 'replay.done'
  meeting_id: string
  events: number
  /** 增量回放的起始 seq（0 表示完整回放） */
  from_seq?: number
  /** 当前会议最后事件的 seq */
  last_seq?: number
}

/** 控制信号回执（WS 端单独发送） */
export interface ControlAckFrame {
  type: 'control.ack'
  meeting_id: string
  signal: string
  status: MeetingStatus
}

/** 错误帧 */
export interface ErrorFrame {
  type: 'error'
  meeting_id?: string
  message: string
  code?: string
}

// ---------- 完整会议状态 ----------

/**
 * 完整会议状态：覆盖 snapshot() 的全部字段（GET /meetings/:id 返回其子集）。
 * 额外字段（injected_messages / claims 等）来自快照，统一设为可选。
 */
export interface MeetingState {
  meeting_id: string
  topic: string
  stage: Stage
  status: MeetingStatus
  clarified_topic?: string | null
  team_config?: TeamMember[]
  key_questions?: string[]
  messages?: MeetingMessage[]
  injected_messages?: Record<string, unknown>[]
  /** 用户介入对话：用户↔主持人 1v1 私密对话 */
  intervention_messages?: InterventionMessage[]
  team_conclusions?: Record<string, unknown>[]
  claims?: Claim[]
  conflicts?: Conflict[]
  evidence_set?: EvidenceSet[]
  decision_record?: DecisionRecord | null
  artifact?: Artifact | null
  paused_snapshot?: Record<string, unknown> | null
  doc_summaries?: string[]
  created_at?: string
  /** 各阶段置信度：high=一次通过 / low=重试后通过 / fallback=降级stub */
  confidence_flags?: Record<string, 'high' | 'low' | 'fallback'>
  /** 借调的 agent 列表（loan 信号裁决通过后追加） */
  borrowed_agents?: BorrowedAgent[]
  /** 自动借调已通过次数 */
  auto_borrow_count?: number
  /** 待用户审批的借调申请 */
  pending_borrow_request?: BorrowRequest | null
  /** 是否冻结借调（用户选择不再允许借调） */
  borrow_frozen?: boolean
  /** 借调申请历史 */
  borrow_request_history?: Array<BorrowRequest & { verdict?: string; approved_at?: string; rejected_at?: string; reject_reason?: string }>
  /** 议题路由计划：simple/standard/full */
  flow_plan?: string
  /** 辩论深度：light/standard/deep */
  debate_depth?: string
  /** 是否启用动态路由 */
  dynamic_routing?: boolean
  /** 产出物类型 */
  deliverable_type?: string
  /** 降级警告：有阶段使用了 StubLLM 兜底 */
  fallback_warning?: { stages: string[]; message: string } | null
}

/** 借调 agent 信息 */
export interface BorrowedAgent {
  role: string
  verdict?: string
  spoken: boolean
  request?: Record<string, unknown>
  auto_approved?: boolean
}

/** 借调申请（待用户审批） */
export interface BorrowRequest {
  id: string
  requester: string
  target_role: string
  goal: string
  necessary: string
  no_loan_cost: string
  requested_at: string
  stage: string
}

/** 介入对话消息 */
export interface InterventionMessage {
  id: string
  sender: 'user' | 'moderator'
  content: string
  reply_to_id?: string
  timestamp: string
  processed?: boolean
}

// ---------- REST 请求 / 响应 ----------

/** POST /meetings 响应 */
export interface CreateMeetingResponse {
  meeting_id: string
  topic: string
  stage: Stage
  status: MeetingStatus
}

/** Agent 角色定义 */
export interface AgentRole {
  id: string
  display_name: string
  perspective: string
  expertise_domains: string[]
  risk_appetite: 'conservative' | 'balanced' | 'aggressive'
  default_stance: string
  evidence_preference: string
  model_override: string
  background_brief: string
  prompt_template: string
  is_builtin: boolean
  is_active: boolean
  created_at: string
  updated_at: string
}

/** GET /agent-roles 响应 */
export interface AgentRoleListResponse {
  roles: AgentRole[]
  total: number
}

/** POST /agent-roles/generate 响应 */
export interface GenerateRolesResponse {
  roles: AgentRole[]
  generated_at: string
}

/** POST /meetings/:id/run 响应 */
export interface RunMeetingResponse {
  meeting_id: string
  stage: Stage
  status: MeetingStatus
  artifact?: Artifact | null
  messages_count: number
}

/** POST /meetings/:id/control 请求 */
export interface ControlRequest {
  signal: 'pause' | 'resume' | 'abort' | 'inject' | 'loan' | 'reject_user' | 'approve_borrow' | 'reject_borrow' | 'freeze_borrow'
  payload?: Record<string, unknown>
}

/** POST /meetings/:id/control 响应 */
export interface ControlResponse {
  meeting_id: string
  signal: string
  status: MeetingStatus
  stage: Stage
}

/** POST /meetings/:id/documents 响应 */
export interface UploadDocumentResponse {
  meeting_id: string
  doc_id: string
  chunks: number
  sections: string[]
  char_count: number
}

// ---------- 借调三问表单（loan 控制信号 payload） ----------

export interface BorrowRequestPayload {
  target_role: string
  goal: string
  necessary: string
  no_loan_cost: string
}
