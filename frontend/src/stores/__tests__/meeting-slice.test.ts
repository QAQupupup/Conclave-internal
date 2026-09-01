/**
 * meeting-slice 单元测试
 *
 * 覆盖场景：
 * 1. addMessage 去重（相同 id 不重复添加）
 * 2. appendMessageDelta 追加内容
 * 3. appendMessageDelta 在不存在的消息上创建新消息
 * 4. finalizeMessage 更新内容和思考
 * 5. updateAgentState 更新指定 agent 状态
 * 6. setMeeting 重置并初始化
 * 7. selectMessage 设置选中消息
 * 8. Tool call 生命周期管理
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { useMeetingStore } from '@/stores/meeting-slice';
import type { MeetingMessage, AgentInfo } from '@/types';

describe('meeting-slice', () => {
  beforeEach(() => {
    useMeetingStore.setState({
      currentMeetingId: null,
      title: '',
      status: 'pending',
      stage: 'clarification',
      startedAt: null,
      paused: false,
      agents: [],
      messages: [],
      borrowRequest: null,
      selectedMessageId: null,
      toolCalls: [],
      takeoverRequest: null,
    });
  });

  // ===== 消息管理 =====

  describe('addMessage', () => {
    it('添加新消息', () => {
      const msg: MeetingMessage = {
        id: 'msg1',
        agentId: 'a1',
        content: 'Hello',
        timestamp: Date.now(),
      };
      useMeetingStore.getState().addMessage(msg);

      expect(useMeetingStore.getState().messages).toHaveLength(1);
      expect(useMeetingStore.getState().messages[0].content).toBe('Hello');
    });

    it('相同 id 的消息不重复添加', () => {
      const msg: MeetingMessage = { id: 'msg1', content: 'Hello', timestamp: 1 };
      useMeetingStore.getState().addMessage(msg);
      useMeetingStore.getState().addMessage(msg); // 重复

      expect(useMeetingStore.getState().messages).toHaveLength(1);
    });

    it('不同 id 的消息正常追加', () => {
      useMeetingStore.getState().addMessage({ id: 'msg1', content: 'A', timestamp: 1 });
      useMeetingStore.getState().addMessage({ id: 'msg2', content: 'B', timestamp: 2 });

      expect(useMeetingStore.getState().messages).toHaveLength(2);
    });
  });

  describe('appendMessageDelta', () => {
    it('追加内容到已有消息', () => {
      useMeetingStore.getState().addMessage({ id: 'msg1', content: 'Hello', timestamp: 1 });
      useMeetingStore.getState().appendMessageDelta('msg1', ' World');

      expect(useMeetingStore.getState().messages[0].content).toBe('Hello World');
    });

    it('追加思考内容', () => {
      useMeetingStore.getState().addMessage({
        id: 'msg1',
        content: '',
        thinking: '思考',
        timestamp: 1,
      });
      useMeetingStore.getState().appendMessageDelta('msg1', '中...', true);

      expect(useMeetingStore.getState().messages[0].thinking).toBe('思考中...');
    });

    it('消息不存在时创建新消息', () => {
      useMeetingStore.getState().appendMessageDelta('new-msg', '新内容');

      const messages = useMeetingStore.getState().messages;
      expect(messages).toHaveLength(1);
      expect(messages[0].id).toBe('new-msg');
      expect(messages[0].content).toBe('新内容');
    });

    it('消息不存在时创建思考消息', () => {
      useMeetingStore.getState().appendMessageDelta('think-msg', '思考内容', true);

      const messages = useMeetingStore.getState().messages;
      expect(messages).toHaveLength(1);
      expect(messages[0].thinking).toBe('思考内容');
      expect(messages[0].isThinking).toBe(true);
    });
  });

  describe('finalizeMessage', () => {
    it('更新消息内容和思考', () => {
      useMeetingStore.getState().addMessage({
        id: 'msg1',
        content: 'partial',
        thinking: 'partial thought',
        isThinking: true,
        timestamp: 1,
      });

      useMeetingStore.getState().finalizeMessage('msg1', 'final content', 'final thought');

      const msg = useMeetingStore.getState().messages[0];
      expect(msg.content).toBe('final content');
      expect(msg.thinking).toBe('final thought');
      expect(msg.isThinking).toBe(false);
    });

    it('不存在的消息不受影响', () => {
      useMeetingStore.getState().addMessage({ id: 'msg1', content: 'A', timestamp: 1 });
      useMeetingStore.getState().finalizeMessage('non-existent', 'B', 'C');

      expect(useMeetingStore.getState().messages).toHaveLength(1);
      expect(useMeetingStore.getState().messages[0].content).toBe('A');
    });
  });

  // ===== Agent 管理 =====

  describe('setAgents / updateAgentState', () => {
    it('setAgents 设置所有 agent', () => {
      const agents: AgentInfo[] = [
        { id: 'a1', name: 'Arch', role: 'architect', state: 'idle' },
        { id: 'a2', name: 'Eng', role: 'engineer', state: 'idle' },
      ];
      useMeetingStore.getState().setAgents(agents);

      expect(useMeetingStore.getState().agents).toHaveLength(2);
    });

    it('updateAgentState 只更新指定 agent', () => {
      const agents: AgentInfo[] = [
        { id: 'a1', name: 'Arch', role: 'architect', state: 'idle' },
        { id: 'a2', name: 'Eng', role: 'engineer', state: 'idle' },
      ];
      useMeetingStore.getState().setAgents(agents);
      useMeetingStore.getState().updateAgentState('a1', 'thinking');

      const updated = useMeetingStore.getState().agents;
      expect(updated[0].state).toBe('thinking');
      expect(updated[1].state).toBe('idle');
    });

    it('updateAgentState 对不存在的 agent 无影响', () => {
      useMeetingStore.getState().setAgents([
        { id: 'a1', name: 'Arch', role: 'architect', state: 'idle' },
      ]);
      useMeetingStore.getState().updateAgentState('non-existent', 'speaking');

      expect(useMeetingStore.getState().agents[0].state).toBe('idle');
    });
  });

  // ===== 会议生命周期 =====

  describe('setMeeting / resetMeeting', () => {
    it('setMeeting 初始化会议并重置其他状态', () => {
      // 先添加一些数据
      useMeetingStore.getState().setAgents([
        { id: 'a1', name: 'Arch', role: 'architect', state: 'idle' },
      ]);
      useMeetingStore.getState().addMessage({ id: 'msg1', content: 'old', timestamp: 1 });

      // 设置新会议
      useMeetingStore.getState().setMeeting('meeting-1', '新会议');

      const state = useMeetingStore.getState();
      expect(state.currentMeetingId).toBe('meeting-1');
      expect(state.title).toBe('新会议');
      expect(state.status).toBe('running');
      expect(state.agents).toHaveLength(0); // 被重置
      expect(state.messages).toHaveLength(0); // 被重置
    });

    it('resetMeeting 恢复到初始状态', () => {
      useMeetingStore.getState().setMeeting('meeting-1', '会议');
      useMeetingStore.getState().setStage('produce');

      useMeetingStore.getState().resetMeeting();

      const state = useMeetingStore.getState();
      expect(state.currentMeetingId).toBeNull();
      expect(state.title).toBe('');
      expect(state.status).toBe('pending');
      expect(state.stage).toBe('clarification');
    });

    it('重进同一会议时不清空消息与状态', () => {
      // 模拟已进入会议并积累了消息/状态
      useMeetingStore.getState().setMeeting('m-x', '会议X');
      useMeetingStore.getState().addMessage({ id: 'msgA', content: 'hi', timestamp: 1 });
      useMeetingStore.getState().setStage('produce');
      useMeetingStore.getState().setStatus('done');

      // 重进同一会议（id 相同）
      useMeetingStore.getState().setMeeting('m-x', '会议X');

      const state = useMeetingStore.getState();
      expect(state.currentMeetingId).toBe('m-x');
      expect(state.messages).toHaveLength(1); // 消息保留
      expect(state.stage).toBe('produce'); // 阶段保留
      expect(state.status).toBe('done'); // 状态保留
    });

    it('切换到不同会议时清空消息并复位状态', () => {
      useMeetingStore.getState().setMeeting('m-x', '会议X');
      useMeetingStore.getState().addMessage({ id: 'msgA', content: 'hi', timestamp: 1 });
      useMeetingStore.getState().setStage('produce');

      useMeetingStore.getState().setMeeting('m-y', '会议Y');

      const state = useMeetingStore.getState();
      expect(state.currentMeetingId).toBe('m-y');
      expect(state.messages).toHaveLength(0); // 切换清空
      expect(state.stage).toBe('clarification'); // 复位
      expect(state.status).toBe('running'); // 复位
    });
  });

  // ===== 消息选择 =====

  describe('selectMessage', () => {
    it('设置选中的消息 ID', () => {
      useMeetingStore.getState().selectMessage('msg1');
      expect(useMeetingStore.getState().selectedMessageId).toBe('msg1');
    });

    it('设置为 null 取消选择', () => {
      useMeetingStore.getState().selectMessage('msg1');
      useMeetingStore.getState().selectMessage(null);
      expect(useMeetingStore.getState().selectedMessageId).toBeNull();
    });
  });

  // ===== Tool Call 管理 =====

  describe('Tool Call 生命周期', () => {
    it('startToolCall 创建新的 tool call 记录', () => {
      useMeetingStore.getState().startToolCall({
        id: 'tc1',
        toolName: 'web_search',
        agentId: 'a1',
        iteration: 1,
        arguments: { query: 'test' },
      });

      const calls = useMeetingStore.getState().toolCalls;
      expect(calls).toHaveLength(1);
      expect(calls[0].status).toBe('running');
      expect(calls[0].steps).toHaveLength(0);
    });

    it('startToolCall 不重复创建相同 id 的记录', () => {
      const call = { id: 'tc1', toolName: 'web_search', iteration: 1, arguments: {} };
      useMeetingStore.getState().startToolCall(call);
      useMeetingStore.getState().startToolCall(call);

      expect(useMeetingStore.getState().toolCalls).toHaveLength(1);
    });

    it('addToolStep 添加步骤到已有的 tool call', () => {
      useMeetingStore.getState().startToolCall({
        id: 'tc1',
        toolName: 'web_search',
        iteration: 1,
        arguments: {},
      });
      useMeetingStore.getState().addToolStep('tc1', {
        stepType: 'search_started',
        label: '开始搜索',
        status: 'completed',
      });

      const call = useMeetingStore.getState().toolCalls[0];
      expect(call.steps).toHaveLength(1);
      expect(call.steps[0].stepType).toBe('search_started');
    });

    it('addToolStep 对不存在的 tool call 无影响', () => {
      useMeetingStore.getState().addToolStep('non-existent', {
        stepType: 'info',
        label: 'test',
        status: 'completed',
      });

      expect(useMeetingStore.getState().toolCalls).toHaveLength(0);
    });

    it('addToolSteps 批量追加步骤且顺序与 id 单调递增', () => {
      useMeetingStore.getState().startToolCall({
        id: 'tc1',
        toolName: 'web_search',
        iteration: 1,
        arguments: {},
      });
      useMeetingStore.getState().addToolSteps('tc1', [
        { stepType: 'search_started', label: '搜索开始', status: 'completed' },
        { stepType: 'fetch_started', label: '抓取开始', status: 'running' },
        { stepType: 'content_extracted', label: '提取完成', status: 'completed' },
      ]);

      const call = useMeetingStore.getState().toolCalls[0];
      expect(call.steps).toHaveLength(3);
      expect(call.steps.map((s) => s.id)).toEqual([
        'tc1-step-0',
        'tc1-step-1',
        'tc1-step-2',
      ]);
      expect(call.steps.map((s) => s.stepType)).toEqual([
        'search_started',
        'fetch_started',
        'content_extracted',
      ]);
    });

    it('addToolSteps 对不存在的 tool call 无影响', () => {
      useMeetingStore.getState().addToolSteps('non-existent', [
        { stepType: 'info', label: 'test', status: 'completed' },
      ]);

      expect(useMeetingStore.getState().toolCalls).toHaveLength(0);
    });

    it('completeToolCall 更新状态为 completed', () => {
      useMeetingStore.getState().startToolCall({
        id: 'tc1',
        toolName: 'web_search',
        iteration: 1,
        arguments: {},
      });
      useMeetingStore.getState().completeToolCall('tc1', true, { latencyMs: 1500 });

      const call = useMeetingStore.getState().toolCalls[0];
      expect(call.status).toBe('completed');
      expect(call.success).toBe(true);
      expect(call.latencyMs).toBe(1500);
    });

    it('failToolCall 更新状态为 failed', () => {
      useMeetingStore.getState().startToolCall({
        id: 'tc1',
        toolName: 'web_search',
        iteration: 1,
        arguments: {},
      });
      useMeetingStore.getState().failToolCall('tc1', 'Network error');

      const call = useMeetingStore.getState().toolCalls[0];
      expect(call.status).toBe('failed');
      expect(call.success).toBe(false);
      expect(call.error).toBe('Network error');
    });
  });
});
