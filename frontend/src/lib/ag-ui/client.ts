import { useMeetingStore } from '@/stores/meeting-slice';
import { ROLE_LABELS, normalizeStageId } from '@/lib/constants';
import type {
  AGUIEvent,
  TextMessageStartEvent,
  TextMessageDeltaEvent,
  TextMessageEndEvent,
  ThinkingStartEvent,
  ThinkingDeltaEvent,
  ThinkingEndEvent,
  ToolCallStartEvent,
  ToolCallStepEvent,
  ToolCallEndEvent,
  StateDeltaEvent,
  InterruptEvent,
  CustomEvent,
  AgentRole,
  BorrowRequest,
  StageId,
} from '@/types';

type EventListener = (event: AGUIEvent) => void;

class AGUIClient {
  private listeners: Set<EventListener> = new Set();
  private activeMessages: Map<string, { content: string; thinking: string; agentId?: string; agentName?: string; agentRole?: string; stage?: string }> = new Map();

  // 高频 tool.step 批量缓冲：合并短窗口内的步骤事件，降低 store.set() 与 React 重渲染频率
  private pendingSteps: ToolCallStepEvent[] = [];
  private stepFlushTimer: ReturnType<typeof setTimeout> | null = null;
  private static readonly STEP_FLUSH_DELAY_MS = 24;

  /**
   * 注册事件监听器，返回取消订阅函数
   */
  subscribe(listener: EventListener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  /**
   * 处理后端原始 WS 消息，转换为 AG-UI 标准事件并分发给 store 和监听器
   */
  handleRawMessage(raw: Record<string, unknown>) {
    const events = this.convertToAGUIEvents(raw);
    for (const event of events) {
      if (event.type === 'TOOL_CALL_STEP') {
        // 高频步骤事件进入缓冲，稍后合并批量写入 store（见 flushSteps）
        this.bufferStep(event as ToolCallStepEvent);
        continue;
      }
      // 非 step 事件先冲刷缓冲，保证步骤先于后续生命周期/消息事件应用，维持事件时序
      this.flushSteps();
      this.dispatchToStore(event);
      this.emit(event);
    }
  }

  /** 将单个 TOOL_CALL_STEP 事件入缓冲，并调度一次延迟冲刷（已定时则不重复调度）。 */
  private bufferStep(event: ToolCallStepEvent): void {
    this.pendingSteps.push(event);
    if (this.stepFlushTimer === null) {
      this.stepFlushTimer = setTimeout(() => this.flushSteps(), AGUIClient.STEP_FLUSH_DELAY_MS);
    }
  }

  /** 冲刷缓冲中的步骤事件：按 callId 聚合后批量写入 store（单次 set()），再按到达顺序逐条 emit。 */
  private flushSteps(): void {
    if (this.stepFlushTimer !== null) {
      clearTimeout(this.stepFlushTimer);
      this.stepFlushTimer = null;
    }
    const steps = this.pendingSteps;
    if (steps.length === 0) return;
    this.pendingSteps = [];

    // 按 callId 聚合，每个 call 只触发一次 addToolSteps（单次 set()），避免逐条 set() 引发大量重渲染
    const byCall = new Map<string, ToolCallStepEvent[]>();
    for (const e of steps) {
      const arr = byCall.get(e.callId) ?? [];
      arr.push(e);
      byCall.set(e.callId, arr);
    }
    const store = useMeetingStore.getState();
    for (const [callId, evts] of byCall) {
      store.addToolSteps(
        callId,
        evts.map((e) => ({
          stepType: e.stepType,
          label: e.label,
          data: e.data,
          url: e.url,
          screenshot: e.screenshot,
          screenshotRef: e.screenshotRef,
          status: e.status || 'completed',
        })),
      );
    }
    // 按到达顺序逐条 emit，保证外部监听者（回放/接管/操作监控）拿到全序事件流
    for (const e of steps) {
      this.emit(e);
    }
  }

  private emit(event: AGUIEvent) {
    this.listeners.forEach((l) => {
      try {
        l(event);
      } catch (e) {
        console.error('[ag-ui] listener error', e);
      }
    });
  }

  /**
   * 将 Conclave 后端事件映射为 AG-UI 事件序列
   * 后端事件类型（来自 orchestrator WebSocket 协议）:
   *   - stage.changed         -> STATE_DELTA
   *   - meeting.started       -> STATE_DELTA (status=running)
   *   - meeting.ended         -> RUN_FINISHED
   *   - meeting.paused        -> STATE_DELTA (paused=true)
   *   - meeting.resumed       -> STATE_DELTA (paused=false)
   *   - agent.thinking        -> THINKING_START/THINKING_DELTA/THINKING_END
   *   - agent.speak           -> TEXT_MESSAGE_START/TEXT_MESSAGE_DELTA/TEXT_MESSAGE_END
   *   - agent.state           -> STATE_DELTA (agents update)
   *   - borrow.request        -> INTERRUPT
   *   - borrow.resolved       -> STATE_DELTA (borrowRequest=null)
   *   - error                 -> RUN_FAILED
   */
  private convertToAGUIEvents(raw: Record<string, unknown>): AGUIEvent[] {
    const type = raw.type as string;
    const ts = Date.now();
    const events: AGUIEvent[] = [];

    switch (type) {
      // ---- Snapshot: 后端重启/首次连接时发送的完整状态快照 ----
      case 'snapshot': {
        const payload = (raw.payload as Record<string, unknown>) || {};
        // 从 snapshot 中恢复会议状态
        const sStage = payload.stage as string | undefined;
        const sStatus = payload.status as string | undefined;
        const sMessages = (payload.messages as Record<string, unknown>[]) || [];
        const sAgents = payload.agents as Record<string, unknown>[] | undefined;
        const sTopic = payload.topic as string | undefined;

        // 1. 恢复 stage 和 status
        if (sStage || sStatus || sTopic) {
          events.push({
            type: 'STATE_DELTA',
            timestamp: ts,
            stage: sStage ? normalizeStageId(sStage) : undefined,
            status: sStatus,
            title: sTopic,
            agents: sAgents,
          } as StateDeltaEvent);
        }

        // 2. 将每条历史消息转换为 TEXT_MESSAGE 事件
        // 后端消息字段: id, role, stage, content, created_at, claim_refs, evidence_refs
        // 前端需要: agentId, agentName, agentRole
        // 使用 constants.ROLE_LABELS 统一映射，覆盖所有后端角色

        const allSnapshotMessages = [
          ...sMessages,
          ...((payload.injected_messages as Record<string, unknown>[]) || []),
        ];

        for (let i = 0; i < allSnapshotMessages.length; i++) {
          const msg = allSnapshotMessages[i];
          const msgId = (msg.id as string) || `snap-msg-${i}`;
          const agentRole = (msg.agent_role as string) || (msg.role as string) || '';
          const agentName = (msg.agent_name as string) || ROLE_LABELS[agentRole] || agentRole || 'Agent';
          const agentId = (msg.agent_id as string) || agentRole || `agent-${i}`;
          const msgStage = (msg.stage as string) || '';
          const content = (msg.content as string) || '';
          const createdAt = (msg.created_at as string) || ts;

          events.push({
            type: 'TEXT_MESSAGE_START',
            timestamp: typeof createdAt === 'string' ? new Date(createdAt).getTime() : ts,
            messageId: msgId,
            agentId,
            agentName,
            agentRole,
            stage: msgStage ? normalizeStageId(msgStage) : undefined,
          } as TextMessageStartEvent);
          events.push({
            type: 'TEXT_MESSAGE_END',
            timestamp: typeof createdAt === 'string' ? new Date(createdAt).getTime() : ts,
            messageId: msgId,
            content,
          } as TextMessageEndEvent);
        }
        break;
      }

      // ---- replay.done: 后端回放完成标记，前端可用于触发 UI 刷新 ----
      case 'replay.done': {
        events.push({
          type: 'CUSTOM',
          timestamp: ts,
          eventType: 'replay.done',
          payload: raw,
        } as CustomEvent);
        break;
      }

      case 'stage.changed': {
        events.push({
          type: 'STATE_DELTA',
          timestamp: ts,
          stage: raw.stage ? normalizeStageId(raw.stage as string) : undefined,
        } as StateDeltaEvent);
        break;
      }

      case 'meeting.started': {
        events.push({
          type: 'STATE_DELTA',
          timestamp: ts,
          status: 'running',
          title: raw.title,
        } as StateDeltaEvent);
        break;
      }

      case 'meeting.ended': {
        events.push({
          type: 'RUN_FINISHED',
          timestamp: ts,
          status: raw.status || 'done',
        } as AGUIEvent);
        break;
      }

      case 'meeting.paused': {
        events.push({ type: 'STATE_DELTA', timestamp: ts, status: 'paused' } as StateDeltaEvent);
        break;
      }

      case 'meeting.resumed': {
        events.push({ type: 'STATE_DELTA', timestamp: ts, status: 'running' } as StateDeltaEvent);
        break;
      }

      case 'meeting.error': {
        events.push({
          type: 'RUN_FAILED',
          timestamp: ts,
          error: raw.message || raw.error,
        } as AGUIEvent);
        events.push({ type: 'STATE_DELTA', timestamp: ts, status: 'error' } as StateDeltaEvent);
        break;
      }

      case 'agent.thinking': {
        const agentId = raw.agent_id as string;
        const agentName = raw.agent_name as string;
        const agentRole = raw.agent_role as string;
        const delta = raw.delta as string;
        const isStart = raw.is_start === true;
        const isEnd = raw.is_end === true;
        const msgId = (raw.message_id as string) || `thinking-${agentId}-${ts}`;

        if (isStart) {
          this.activeMessages.set(msgId, { content: '', thinking: '', agentId, agentName, agentRole });
          events.push({ type: 'THINKING_START', timestamp: ts, messageId: msgId, agentId } as ThinkingStartEvent);
        }
        if (delta) {
          const m = this.activeMessages.get(msgId);
          if (m) m.thinking += delta;
          events.push({ type: 'THINKING_DELTA', timestamp: ts, messageId: msgId, delta } as ThinkingDeltaEvent);
        }
        if (isEnd) {
          events.push({ type: 'THINKING_END', timestamp: ts, messageId: msgId } as ThinkingEndEvent);
        }
        break;
      }

      case 'agent.speak': {
        const agentId = raw.agent_id as string;
        const agentName = raw.agent_name as string;
        const agentRole = raw.agent_role as string;
        const stage = raw.stage as string;
        const delta = raw.delta as string;
        const content = raw.content as string;
        const isStart = raw.is_start === true;
        const isEnd = raw.is_end === true || content !== undefined;
        const msgId = (raw.message_id as string) || `msg-${agentId}-${ts}`;

        if (isStart) {
          this.activeMessages.set(msgId, { content: '', thinking: '', agentId, agentName, agentRole, stage });
          events.push({
            type: 'TEXT_MESSAGE_START',
            timestamp: ts,
            messageId: msgId,
            agentId,
            agentName,
            agentRole,
            stage,
          } as TextMessageStartEvent);
        }
        if (delta) {
          const m = this.activeMessages.get(msgId);
          if (m) m.content += delta;
          events.push({ type: 'TEXT_MESSAGE_DELTA', timestamp: ts, messageId: msgId, delta } as TextMessageDeltaEvent);
        }
        if (isEnd) {
          const finalContent = content ?? this.activeMessages.get(msgId)?.content ?? '';
          events.push({
            type: 'TEXT_MESSAGE_END',
            timestamp: ts,
            messageId: msgId,
            content: finalContent,
          } as TextMessageEndEvent);
          this.activeMessages.delete(msgId);
        }
        break;
      }

      // 后端实际发布的事件类型是 agent.spoke（过去式），payload 包含完整发言
      case 'agent.spoke': {
        const p = (raw.payload as Record<string, unknown>) || raw;
        const agentRole = (p.role as string) || (p.agent_role as string) || '';
        const agentName = (p.agent_name as string) || ROLE_LABELS[agentRole] || agentRole || 'Agent';
        const agentId = (p.agent_id as string) || agentRole || `agent-${ts}`;
        const stage = (p.stage as string) || '';
        const content = (p.content as string) || '';
        const msgId = (p.message_id as string) || `msg-${agentId}-${ts}`;

        events.push({
          type: 'TEXT_MESSAGE_START',
          timestamp: ts,
          messageId: msgId,
          agentId,
          agentName,
          agentRole,
          stage,
        } as TextMessageStartEvent);
        events.push({
          type: 'TEXT_MESSAGE_END',
          timestamp: ts,
          messageId: msgId,
          content,
        } as TextMessageEndEvent);
        break;
      }

      case 'agent.state': {
        events.push({
          type: 'STATE_DELTA',
          timestamp: ts,
          agents: raw.agents,
        } as StateDeltaEvent);
        break;
      }

      case 'borrow.request': {
        events.push({
          type: 'INTERRUPT',
          timestamp: ts,
          interruptType: 'borrow',
          data: raw.request,
        } as InterruptEvent);
        break;
      }

      case 'borrow.resolved': {
        events.push({
          type: 'STATE_DELTA',
          timestamp: ts,
          borrowRequest: null,
        } as StateDeltaEvent);
        break;
      }

      case 'tool.started': {
        events.push({
          type: 'TOOL_CALL_START',
          timestamp: ts,
          callId: raw.call_id as string,
          toolName: raw.tool_name as string,
          arguments: (raw.arguments as Record<string, unknown>) || {},
          reason: raw.reason as string | undefined,
          iteration: (raw.iteration as number) || 0,
        } as ToolCallStartEvent);
        break;
      }

      case 'tool.step': {
        const stepData = (raw.data as Record<string, unknown>) || {};
        // 从 step data 中提取 label/url/screenshot
        const label = (stepData.label as string) ||
          (stepData.message as string) ||
          (raw.step_type as string) ||
          '';
        events.push({
          type: 'TOOL_CALL_STEP',
          timestamp: ts,
          callId: raw.call_id as string,
          toolName: raw.tool_name as string,
          stepType: raw.step_type as string,
          label,
          data: stepData,
          url: stepData.url as string | undefined,
          screenshot: stepData.screenshot as string | undefined,
          screenshotRef: stepData.screenshot_ref as string | undefined,
          status: (stepData.status as 'running' | 'completed' | 'failed') || 'completed',
        } as ToolCallStepEvent);
        break;
      }

      case 'tool.completed': {
        events.push({
          type: 'TOOL_CALL_END',
          timestamp: ts,
          callId: raw.call_id as string,
          toolName: raw.tool_name as string,
          success: raw.success !== false,
          latencyMs: raw.latency_ms as number | undefined,
          summary: raw.summary as Record<string, unknown> | undefined,
        } as ToolCallEndEvent);
        break;
      }

      case 'tool.failed': {
        events.push({
          type: 'TOOL_CALL_END',
          timestamp: ts,
          callId: raw.call_id as string,
          toolName: raw.tool_name as string,
          success: false,
          error: raw.error as string,
          latencyMs: raw.latency_ms as number | undefined,
        } as ToolCallEndEvent);
        break;
      }

      default:
        // 未识别事件作为 CUSTOM 透传
        events.push({
          type: 'CUSTOM',
          timestamp: ts,
          eventType: type,
          payload: raw,
        } as CustomEvent);
        break;
    }

    return events;
  }

  private dispatchToStore(event: AGUIEvent) {
    const store = useMeetingStore.getState();

    switch (event.type) {
      case 'TEXT_MESSAGE_START': {
        const e = event as TextMessageStartEvent;
        store.addMessage({
          id: e.messageId,
          agentId: e.agentId,
          agentName: e.agentName,
          agentRole: e.agentRole as AgentRole | undefined,
          // 事件未携带阶段时回退为当前 store 阶段（stage.changed 已先行更新），
          // 保证对话流的阶段分隔行在实时路径下可派生
          stage: e.stage ? (normalizeStageId(e.stage) as StageId) : store.stage,
          content: '',
          thinking: '',
          timestamp: e.timestamp,
          isThinking: false,
        });
        if (e.agentId) {
          store.updateAgentState(e.agentId, 'speaking');
        }
        break;
      }

      case 'TEXT_MESSAGE_DELTA': {
        const e = event as TextMessageDeltaEvent;
        store.appendMessageDelta(e.messageId, e.delta, false);
        break;
      }

      case 'TEXT_MESSAGE_END': {
        const e = event as TextMessageEndEvent;
        const existing = useMeetingStore.getState().messages?.find((m) => m.id === e.messageId);
        store.finalizeMessage(e.messageId, e.content, existing?.thinking);
        if (existing?.agentId) {
          store.updateAgentState(existing.agentId, 'waiting');
        }
        break;
      }

      case 'THINKING_START': {
        const e = event as ThinkingStartEvent;
        store.addMessage({
          id: e.messageId,
          agentId: e.agentId,
          content: '',
          thinking: '',
          timestamp: e.timestamp,
          isThinking: true,
        });
        if (e.agentId) {
          store.updateAgentState(e.agentId, 'thinking');
        }
        break;
      }

      case 'THINKING_DELTA': {
        const e = event as ThinkingDeltaEvent;
        store.appendMessageDelta(e.messageId, e.delta, true);
        break;
      }

      case 'THINKING_END': {
        const e = event as ThinkingEndEvent;
        const existing = useMeetingStore.getState().messages?.find((m) => m.id === e.messageId);
        if (existing) {
          store.finalizeMessage(e.messageId, existing.content, existing.thinking);
        }
        break;
      }

      case 'STATE_DELTA': {
        const e = event as StateDeltaEvent;
        if (e.stage) store.setStage(e.stage);
        if (e.status) store.setStatus(e.status);
        // 按 id 合并而非整体替换：STATE_DELTA 可能仅携带 {id, state} 瘦身负载，
        // 整体替换会抹掉 name/role，导致头像退化为 "?"（见 lib/agent-merge）
        if (e.agents) store.mergeAgents(e.agents);
        if (e.title) {
          // 不直接 setMeeting，只更新 title
          useMeetingStore.setState({ title: e.title });
        }
        if ('borrowRequest' in e) {
          store.setBorrowRequest(e.borrowRequest ?? null);
        }
        break;
      }

      case 'RUN_FINISHED': {
        store.setStatus('done');
        break;
      }

      case 'RUN_FAILED': {
        store.setStatus('error');
        break;
      }

      case 'INTERRUPT': {
        const e = event as InterruptEvent;
        if (e.interruptType === 'borrow' && e.data) {
          store.setBorrowRequest(e.data as BorrowRequest);
        }
        if (e.interruptType === 'takeover' && e.data) {
          store.setTakeoverRequest(e.data as { callId: string; toolName: string });
        }
        break;
      }

      case 'TOOL_CALL_START': {
        const e = event as ToolCallStartEvent;
        store.startToolCall({
          id: e.callId,
          toolName: e.toolName,
          arguments: e.arguments,
          reason: e.reason,
          iteration: e.iteration,
        });
        break;
      }

      case 'TOOL_CALL_STEP': {
        const e = event as ToolCallStepEvent;
        store.addToolStep(e.callId, {
          stepType: e.stepType,
          label: e.label,
          data: e.data,
          url: e.url,
          screenshot: e.screenshot,
          screenshotRef: e.screenshotRef,
          status: e.status || 'completed',
        });
        break;
      }

      case 'TOOL_CALL_END': {
        const e = event as ToolCallEndEvent;
        store.completeToolCall(e.callId, e.success, {
          error: e.error,
          latencyMs: e.latencyMs,
          summary: e.summary,
        });
        break;
      }
    }
  }
}

export const agUIClient = new AGUIClient();
