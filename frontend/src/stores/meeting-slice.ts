import { create } from 'zustand';
import type { StageId, MeetingStatus, MeetingMessage, BorrowRequest, AgentInfo, ToolCallRecord, ToolStep } from '@/types';

interface MeetingState {
  currentMeetingId: string | null;
  title: string;
  status: MeetingStatus;
  stage: StageId;
  startedAt: number | null;
  paused: boolean;
  agents: AgentInfo[];
  messages: MeetingMessage[];
  borrowRequest: BorrowRequest | null;
  selectedMessageId: string | null;
  toolCalls: ToolCallRecord[];
  takeoverRequest: { callId: string; toolName: string } | null;

  setMeeting: (id: string, title: string) => void;
  resetMeeting: () => void;
  setStatus: (status: MeetingStatus) => void;
  setStage: (stage: StageId) => void;
  setPaused: (paused: boolean) => void;
  setAgents: (agents: AgentInfo[]) => void;
  updateAgentState: (agentId: string, state: AgentInfo['state']) => void;
  addMessage: (msg: MeetingMessage) => void;
  appendMessageDelta: (messageId: string, delta: string, thinking?: boolean) => void;
  finalizeMessage: (messageId: string, content: string, thinking?: string) => void;
  setBorrowRequest: (req: BorrowRequest | null) => void;
  selectMessage: (id: string | null) => void;

  // Tool call 管理
  startToolCall: (call: Omit<ToolCallRecord, 'status' | 'steps' | 'startedAt'> & { startedAt?: string }) => void;
  addToolStep: (callId: string, step: Omit<ToolStep, 'id' | 'callId' | 'timestamp'> & { timestamp?: string }) => void;
  completeToolCall: (callId: string, success: boolean, data: { error?: string; latencyMs?: number; summary?: Record<string, unknown> }) => void;
  failToolCall: (callId: string, error: string) => void;
  setTakeoverRequest: (req: { callId: string; toolName: string } | null) => void;
}

const initialState = {
  currentMeetingId: null,
  title: '',
  status: 'pending' as MeetingStatus,
  stage: 'clarification' as StageId,
  startedAt: null,
  paused: false,
  agents: [],
  messages: [],
  borrowRequest: null,
  selectedMessageId: null,
  toolCalls: [],
  takeoverRequest: null,
};

export const useMeetingStore = create<MeetingState>((set, get) => ({
  ...initialState,

  setMeeting: (id, title) =>
    set({
      ...initialState,
      currentMeetingId: id,
      title,
      status: 'running',
      startedAt: Date.now(),
    }),

  resetMeeting: () => set(initialState),

  setStatus: (status) => set({ status }),

  setStage: (stage) => set({ stage }),

  setPaused: (paused) => set({ paused }),

  setAgents: (agents) => set({ agents }),

  updateAgentState: (agentId, state) =>
    set((s) => ({
      agents: s.agents.map((a) => (a.id === agentId ? { ...a, state } : a)),
    })),

  addMessage: (msg) => {
    const exists = get().messages.some((m) => m.id === msg.id);
    if (exists) return;
    set((s) => ({ messages: [...s.messages, msg] }));
  },

  appendMessageDelta: (messageId, delta, thinking = false) => {
    set((s) => {
      const idx = s.messages.findIndex((m) => m.id === messageId);
      if (idx === -1) {
        return {
          messages: [
            ...s.messages,
            {
              id: messageId,
              content: thinking ? '' : delta,
              thinking: thinking ? delta : '',
              timestamp: Date.now(),
              isThinking: true,
            } as MeetingMessage,
          ],
        };
      }
      const updated = [...s.messages];
      const field = thinking ? 'thinking' : 'content';
      updated[idx] = { ...updated[idx], [field]: (updated[idx][field as keyof MeetingMessage] as string) + delta };
      return { messages: updated };
    });
  },

  finalizeMessage: (messageId, content, thinking) => {
    set((s) => ({
      messages: s.messages.map((m) =>
        m.id === messageId
          ? { ...m, content, thinking: thinking ?? m.thinking, isThinking: false }
          : m
      ),
    }));
  },

  setBorrowRequest: (borrowRequest) => set({ borrowRequest }),

  selectMessage: (selectedMessageId) => set({ selectedMessageId }),

  // ===== Tool Call 管理 =====

  startToolCall: (call) => {
    set((s) => {
      const exists = s.toolCalls.some((tc) => tc.id === call.id);
      if (exists) return s;
      const record: ToolCallRecord = {
        ...call,
        status: 'running',
        steps: [],
        startedAt: call.startedAt || new Date().toISOString(),
      };
      return { toolCalls: [...s.toolCalls, record] };
    });
  },

  addToolStep: (callId, step) => {
    set((s) => {
      const idx = s.toolCalls.findIndex((tc) => tc.id === callId);
      if (idx === -1) return s;
      const updated = [...s.toolCalls];
      const stepRecord: ToolStep = {
        id: `${callId}-step-${updated[idx].steps.length}`,
        callId,
        timestamp: step.timestamp || new Date().toISOString(),
        status: step.status || 'completed',
        stepType: step.stepType,
        label: step.label || step.stepType,
        data: step.data,
        screenshot: step.screenshot,
        url: step.url,
      };
      updated[idx] = {
        ...updated[idx],
        steps: [...updated[idx].steps, stepRecord],
      };
      return { toolCalls: updated };
    });
  },

  completeToolCall: (callId, success, data) => {
    set((s) => ({
      toolCalls: s.toolCalls.map((tc) =>
        tc.id === callId
          ? {
              ...tc,
              status: success ? 'completed' : 'failed',
              success,
              completedAt: new Date().toISOString(),
              error: data.error,
              latencyMs: data.latencyMs,
              summary: data.summary,
            }
          : tc
      ),
    }));
  },

  failToolCall: (callId, error) => {
    set((s) => ({
      toolCalls: s.toolCalls.map((tc) =>
        tc.id === callId
          ? { ...tc, status: 'failed', success: false, error, completedAt: new Date().toISOString() }
          : tc
      ),
    }));
  },

  setTakeoverRequest: (takeoverRequest) => set({ takeoverRequest }),
}));
