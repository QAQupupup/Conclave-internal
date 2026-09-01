import type { AgentInfo, StageId, MeetingStatus, BorrowRequest } from './meeting';

export type AGUIEventType =
  | 'RUN_STARTED'
  | 'RUN_FINISHED'
  | 'RUN_FAILED'
  | 'TEXT_MESSAGE_START'
  | 'TEXT_MESSAGE_DELTA'
  | 'TEXT_MESSAGE_END'
  | 'THINKING_START'
  | 'THINKING_DELTA'
  | 'THINKING_END'
  | 'TOOL_CALL_START'
  | 'TOOL_CALL_STEP'
  | 'TOOL_CALL_END'
  | 'STATE_DELTA'
  | 'INTERRUPT'
  | 'CUSTOM';

export interface AGUIEvent {
  type: AGUIEventType;
  timestamp: number;
  [key: string]: unknown;
}

export interface TextMessageStartEvent extends AGUIEvent {
  type: 'TEXT_MESSAGE_START';
  messageId: string;
  agentId?: string;
  agentName?: string;
  agentRole?: string;
  stage?: StageId;
}

export interface TextMessageDeltaEvent extends AGUIEvent {
  type: 'TEXT_MESSAGE_DELTA';
  messageId: string;
  delta: string;
}

export interface TextMessageEndEvent extends AGUIEvent {
  type: 'TEXT_MESSAGE_END';
  messageId: string;
  content: string;
}

export interface ThinkingStartEvent extends AGUIEvent {
  type: 'THINKING_START';
  messageId: string;
  agentId?: string;
}

export interface ThinkingDeltaEvent extends AGUIEvent {
  type: 'THINKING_DELTA';
  messageId: string;
  delta: string;
}

export interface ThinkingEndEvent extends AGUIEvent {
  type: 'THINKING_END';
  messageId: string;
}

export interface StateDeltaEvent extends AGUIEvent {
  type: 'STATE_DELTA';
  stage?: StageId;
  status?: MeetingStatus;
  agents?: AgentInfo[];
  title?: string;
  borrowRequest?: BorrowRequest | null;
}

export interface InterruptEvent extends AGUIEvent {
  type: 'INTERRUPT';
  interruptType: 'borrow' | 'approve' | 'clarify' | 'takeover';
  data: BorrowRequest | Record<string, unknown>;
}

export interface ToolCallStartEvent extends AGUIEvent {
  type: 'TOOL_CALL_START';
  callId: string;
  toolName: string;
  arguments: Record<string, unknown>;
  reason?: string;
  iteration: number;
}

export interface ToolCallStepEvent extends AGUIEvent {
  type: 'TOOL_CALL_STEP';
  callId: string;
  toolName: string;
  stepType: string;
  label: string;
  data?: Record<string, unknown>;
  screenshot?: string;
  screenshotRef?: string;
  url?: string;
  status?: 'running' | 'completed' | 'failed';
}

export interface ToolCallEndEvent extends AGUIEvent {
  type: 'TOOL_CALL_END';
  callId: string;
  toolName: string;
  success: boolean;
  error?: string;
  latencyMs?: number;
  summary?: Record<string, unknown>;
}

export interface CustomEvent extends AGUIEvent {
  type: 'CUSTOM';
  eventType: string;
  payload: Record<string, unknown>;
}
