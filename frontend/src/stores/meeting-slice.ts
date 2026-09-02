import { create } from 'zustand';
import type { StageId, MeetingStatus, MeetingMessage, BorrowRequest, AgentInfo, ToolCallRecord, ToolStep } from '@/types';
import { normalizeStageId } from '@/lib/constants';
import { mergeAgentUpdates } from '@/lib/agent-merge';

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
  /** 按 id 合并 agents 增量（STATE_DELTA 瘦身负载不抹掉 name/role），见 lib/agent-merge */
  mergeAgents: (incoming: AgentInfo[]) => void;
  updateAgentState: (agentId: string, state: AgentInfo['state']) => void;
  addMessage: (msg: MeetingMessage) => void;
  appendMessageDelta: (messageId: string, delta: string, thinking?: boolean) => void;
  finalizeMessage: (messageId: string, content: string, thinking?: string) => void;
  setBorrowRequest: (req: BorrowRequest | null) => void;
  selectMessage: (id: string | null) => void;

  // Tool call 管理
  startToolCall: (call: Omit<ToolCallRecord, 'status' | 'steps' | 'startedAt'> & { startedAt?: string }) => void;
  addToolStep: (callId: string, step: Omit<ToolStep, 'id' | 'callId' | 'timestamp'> & { timestamp?: string }) => void;
  addToolSteps: (callId: string, steps: (Omit<ToolStep, 'id' | 'callId' | 'timestamp'> & { timestamp?: string })[]) => void;
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

  // 进入/切换会议时初始化 store。
  // 关键修复：仅当切换到「不同」会议(id 变化)时才清空消息历史并复位状态机；
  // 重进同一个会议(id 相同)时只更新标题，保留已有的消息与状态，
  // 避免全局 store 跨路由仍保留的消息被清空，导致对话流白屏/阶段闪烁错态。
  setMeeting: (id, title) => {
    const prev = get();
    if (prev.currentMeetingId === id) {
      set({ title });
      return;
    }
    set({
      ...initialState,
      currentMeetingId: id,
      title,
      status: 'running',
      startedAt: Date.now(),
    });
  },

  resetMeeting: () => set(initialState),

  setStatus: (status) => set({ status }),

  setStage: (stage) => set({ stage: normalizeStageId(stage) as StageId }),

  setPaused: (paused) => set({ paused }),

  setAgents: (agents) => set({ agents }),

  mergeAgents: (incoming) => set((s) => ({ agents: mergeAgentUpdates(s.agents, incoming) })),

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

  addToolStep: (callId, step) => get().addToolSteps(callId, [step]),

  addToolSteps: (callId, steps) => {
    if (steps.length === 0) return;
    set((s) => {
      const idx = s.toolCalls.findIndex((tc) => tc.id === callId);
      if (idx === -1) return s;
      const updated = [...s.toolCalls];
      const baseLen = updated[idx].steps.length;
      const stepRecords: ToolStep[] = steps.map((step, i) => ({
        id: `${callId}-step-${baseLen + i}`,
        callId,
        timestamp: step.timestamp || new Date().toISOString(),
        status: step.status || 'completed',
        stepType: step.stepType,
        label: step.label || step.stepType,
        data: step.data,
        screenshot: step.screenshot,
        screenshotRef: step.screenshotRef,
        url: step.url,
      }));
      updated[idx] = {
        ...updated[idx],
        steps: [...updated[idx].steps, ...stepRecords],
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
