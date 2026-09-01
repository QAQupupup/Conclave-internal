export type StageId =
  | 'pending'
  | 'clarify'
  | 'clarification'
  | 'intra_team'
  | 'cross_team'
  | 'evidence_check'
  | 'arbitrate'
  | 'produce'
  | 'done'
  | 'paused'
  | 'error'
  | 'aborted';

export type MeetingStatus = 'pending' | 'running' | 'paused' | 'done' | 'error' | 'aborted';

export type AgentRole =
  | 'moderator'
  | 'product_architect'
  | 'architect'
  | 'engineer'
  | 'security_expert'
  | 'security'
  | 'data_engineer'
  | 'data'
  | 'ux_designer'
  | 'ux'
  | 'marketing_expert'
  | 'marketing'
  | 'tech_lead'
  | 'sre'
  | 'pm'
  | 'dba'
  | 'ml_engineer'
  | 'search_expert'
  | 'evaluator';

export type AgentState = 'idle' | 'thinking' | 'speaking' | 'waiting' | 'done' | 'paused';

export type WsConnectionStatus = 'connected' | 'connecting' | 'disconnected';

export interface AgentInfo {
  id: string;
  name: string;
  role: AgentRole;
  state: AgentState;
  avatar?: string;
}

export interface WsMessage {
  type: string;
  [key: string]: unknown;
}

export interface MeetingMessage {
  id: string;
  meeting_id?: string;
  agentId?: string;
  agent_id?: string;
  agentName?: string;
  agent_name?: string;
  agentRole?: AgentRole;
  agent_role?: AgentRole;
  role?: 'system' | 'user' | 'assistant' | 'tool_call';
  content: string;
  thinking?: string;
  stage?: StageId;
  timestamp: number | string;
  isUser?: boolean;
  isThinking?: boolean;
  reactions?: Record<string, number>;
  replyTo?: string;
  metadata?: Record<string, unknown>;
}

export interface Meeting {
  id: string;
  title: string;
  topic?: string;
  description?: string;
  status: MeetingStatus;
  stage: StageId;
  createdAt?: number;
  /** @deprecated Use camelCase `createdAt` (number timestamp). Kept for legacy component compatibility. */
  created_at?: string;
  updatedAt?: number;
  /** @deprecated Use camelCase `updatedAt`. */
  updated_at?: string;
  startedAt?: number;
  endedAt?: number;
  createdBy?: string;
  /** @deprecated Use camelCase `createdBy`. */
  created_by?: string;
  deliverableType?: string;
  agents: AgentInfo[];
  messageCount?: number;
  /** @deprecated Use camelCase `messageCount`. Kept for legacy component compatibility; new code must use `messageCount`. */
  message_count?: number;
  summary?: string | null;
  metadata?: Record<string, unknown>;
}

export interface BorrowRequest {
  id: string;
  fromAgent: string;
  toAgent: string;
  reason: string;
  taskDescription: string;
}

export interface TenantInfo {
  id: string;
  name: string;
  role: string; // owner / admin / member / maintainer / reporter
  my_role?: string;
  slug?: string;
}

export interface UserInfo {
  id: string;
  uid?: string | number;
  username: string;
  display_name: string;
  tenant_id: string;
  tenants: TenantInfo[];
  email?: string;
  role?: string; // 旧字段：'admin' | 'owner' | 'member'
  system_role?: 'system_owner' | 'system_admin' | 'user' | string;
  domain?: string; // RBAC domain
  roles?: string[]; // 当前 Team 角色
  avatar_url?: string;
  is_system_admin?: boolean;
}

export interface AuthState {
  token: string | null;
  user: UserInfo | null;
  isAuthenticated: boolean;
  isLoading: boolean;
}

// ===== 工具调用（Tool Call）类型 =====

export type ToolCallStatus = 'pending' | 'running' | 'completed' | 'failed';

export interface ToolStep {
  id: string;
  callId: string;
  stepType: string;       // 'search_started' | 'results_found' | 'page_navigated' | 'content_extracted' | 'captcha_detected' | 'screenshot_taken' | 'error' | 'info'
  label: string;          // 人类可读的步骤描述
  data?: Record<string, unknown>;
  screenshot?: string;    // base64 截图（可选，降级路径）
  screenshotRef?: string; // 截图落盘后的相对 URL 路径引用（如 /meetings/{id}/recordings/{file}.png）
  url?: string;
  status: 'pending' | 'running' | 'completed' | 'failed' | 'skipped';
  timestamp: string;
  durationMs?: number;
}

export interface ToolCallRecord {
  id: string;             // call_id
  toolName: string;       // 'web_search' | 'web_fetch' | 'browser.goto' | ...
  agentId?: string;
  agentName?: string;
  iteration: number;
  status: ToolCallStatus;
  arguments: Record<string, unknown>;
  reason?: string;
  startedAt: string;
  completedAt?: string;
  latencyMs?: number;
  success?: boolean;
  error?: string;
  summary?: Record<string, unknown>;
  steps: ToolStep[];
}

