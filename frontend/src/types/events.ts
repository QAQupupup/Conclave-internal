// 镜像后端事件 schema 的 TypeScript 类型定义
// 对齐 backend/app/models.py 与 backend/app/events.py
// 前端所有 WS 事件、REST 响应均以此处类型为准

// ---------- 枚举（镜像 backend/app/models.py 的 str Enum）----------

/** 会议角色：主持人 / 产品架构师 / 工程师 */
export type Role = 'moderator' | 'product_architect' | 'engineer'

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

// 角色中文标签
export const ROLE_LABELS: Record<Role, string> = {
  moderator: '主持人',
  product_architect: '产品架构师',
  engineer: '工程师',
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
}

/** 借调 agent 信息 */
export interface BorrowedAgent {
  role: string
  verdict?: string
  spoken: boolean
  request?: Record<string, unknown>
}

// ---------- REST 请求 / 响应 ----------

/** POST /meetings 响应 */
export interface CreateMeetingResponse {
  meeting_id: string
  topic: string
  stage: Stage
  status: MeetingStatus
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
  signal: 'pause' | 'resume' | 'abort' | 'inject' | 'loan'
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
