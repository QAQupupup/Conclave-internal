/**
 * ThoughtTree 组件测试
 *
 * 覆盖场景：
 * 1. messages 为 undefined/null 时不崩溃
 * 2. agents 为空时显示 "Agent 正在加入..."
 * 3. messages 有数据时正确分组到对应 agent
 * 4. selectedMessageId 匹配时 agent 高亮
 * 5. selectedMessageId 不匹配时不高亮
 * 6. borrowRequest 存在时显示借调请求卡片
 * 7. messages 中 agentId 缺失的消息被正确过滤
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { screen } from '@testing-library/react';
import { ThoughtTree } from '@/components/meeting/thought-tree';
import { useMeetingStore } from '@/stores/meeting-slice';
import { renderWithProviders } from '@/test/test-utils';
import type { AgentInfo, MeetingMessage } from '@/types';

// Mock SVG icons（避免复杂 SVG 渲染）
vi.mock('@/components/ui/svg-icons', () => ({
  AgentAvatar: ({ agentId }: { agentId: string }) => (
    <div data-testid={`avatar-${agentId}`} />
  ),
  StatusDot: ({ status }: { status: string }) => (
    <div data-testid="status-dot">{status}</div>
  ),
}));

describe('ThoughtTree', () => {
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
    vi.clearAllMocks();
  });

  describe('空状态', () => {
    it('agents 为空时显示 "Agent 正在加入..."', () => {
      useMeetingStore.setState({ agents: [], messages: [] });

      renderWithProviders(<ThoughtTree />);
      expect(screen.getByText('Agent 正在加入...')).toBeDefined();
    });

    it('显示 agent 数量', () => {
      const agents: AgentInfo[] = [
        { id: 'a1', name: '架构师', role: 'architect', state: 'idle' },
        { id: 'a2', name: '工程师', role: 'engineer', state: 'thinking' },
      ];
      useMeetingStore.setState({ agents });

      renderWithProviders(<ThoughtTree />);
      expect(screen.getByText('2 位 Agent')).toBeDefined();
    });
  });

  describe('Agent 渲染', () => {
    it('正确渲染每个 agent 的名称', () => {
      const agents: AgentInfo[] = [
        { id: 'a1', name: '小明', role: 'architect', state: 'idle' },
        { id: 'a2', name: '小红', role: 'engineer', state: 'speaking' },
      ];
      useMeetingStore.setState({ agents, messages: [] });

      renderWithProviders(<ThoughtTree />);
      expect(screen.getByText('小明')).toBeDefined();
      expect(screen.getByText('小红')).toBeDefined();
    });

    it('正确显示 agent 状态标签', () => {
      const agents: AgentInfo[] = [
        { id: 'a1', name: '思考者', role: 'architect', state: 'thinking' },
        { id: 'a2', name: '等待者', role: 'engineer', state: 'waiting' },
      ];
      useMeetingStore.setState({ agents, messages: [] });

      renderWithProviders(<ThoughtTree />);
      expect(screen.getByText('思考中')).toBeDefined();
      expect(screen.getByText('等待中')).toBeDefined();
    });
  });

  describe('messages 防御', () => {
    it('messages 为空数组时 → Agent 正常渲染', () => {
      const agents: AgentInfo[] = [
        { id: 'a1', name: 'Agent1', role: 'architect', state: 'idle' },
      ];
      useMeetingStore.setState({ agents, messages: [] });

      renderWithProviders(<ThoughtTree />);
      expect(screen.getByText('Agent1')).toBeDefined();
    });

    it('messages 有数据但 agentId 缺失时 → 消息被过滤，Agent 仍正常渲染', () => {
      const agents: AgentInfo[] = [
        { id: 'a1', name: 'Agent1', role: 'architect', state: 'idle' },
      ];
      const messages: MeetingMessage[] = [
        {
          id: 'msg1',
          content: '无 agentId 的消息',
          timestamp: Date.now(),
          // 没有 agentId
        },
      ];
      useMeetingStore.setState({ agents, messages });

      renderWithProviders(<ThoughtTree />);
      expect(screen.getByText('Agent1')).toBeDefined();
    });

    it('messages 中 isThinking 为 true 的消息被过滤 → Agent 仍正常渲染', () => {
      const agents: AgentInfo[] = [
        { id: 'a1', name: 'Agent1', role: 'architect', state: 'thinking' },
      ];
      const messages: MeetingMessage[] = [
        {
          id: 'msg1',
          agentId: 'a1',
          content: '思考内容',
          timestamp: Date.now(),
          isThinking: true,
        },
      ];
      useMeetingStore.setState({ agents, messages });

      renderWithProviders(<ThoughtTree />);
      expect(screen.getByText('Agent1')).toBeDefined();
      expect(screen.getByText('思考中')).toBeDefined();
    });
  });

  describe('highlight 逻辑', () => {
    it('selectedMessageId 为 null 时 → 无 agent 高亮', () => {
      const agents: AgentInfo[] = [
        { id: 'a1', name: 'Agent1', role: 'architect', state: 'idle' },
      ];
      const messages: MeetingMessage[] = [
        { id: 'msg1', agentId: 'a1', content: 'Hello', timestamp: Date.now() },
      ];
      useMeetingStore.setState({ agents, messages, selectedMessageId: null });

      renderWithProviders(<ThoughtTree />);
      const agentCard = screen.getByText('Agent1').closest('div[class*="rounded-md"]');
      expect(agentCard?.className).not.toContain('border-brand-500');
    });

    it('selectedMessageId 匹配某 agent 的消息时 → 该 agent 高亮，其他不高亮', () => {
      const agents: AgentInfo[] = [
        { id: 'a1', name: 'Agent1', role: 'architect', state: 'idle' },
        { id: 'a2', name: 'Agent2', role: 'engineer', state: 'idle' },
      ];
      const messages: MeetingMessage[] = [
        { id: 'msg1', agentId: 'a1', content: '来自 Agent1', timestamp: Date.now() },
        { id: 'msg2', agentId: 'a2', content: '来自 Agent2', timestamp: Date.now() },
      ];
      useMeetingStore.setState({ agents, messages, selectedMessageId: 'msg1' });

      renderWithProviders(<ThoughtTree />);

      // Agent1 应高亮（border-brand-500/30 class）
      const agent1Card = screen.getByText('Agent1').closest('div[class*="rounded-md"]');
      expect(agent1Card?.className).toContain('border-brand-500');

      // Agent2 不应高亮
      const agent2Card = screen.getByText('Agent2').closest('div[class*="rounded-md"]');
      expect(agent2Card?.className).not.toContain('border-brand-500');
    });

    it('selectedMessageId 不匹配任何消息时 → 无 agent 高亮', () => {
      const agents: AgentInfo[] = [
        { id: 'a1', name: 'Agent1', role: 'architect', state: 'idle' },
      ];
      const messages: MeetingMessage[] = [
        { id: 'msg1', agentId: 'a1', content: 'Hello', timestamp: Date.now() },
      ];
      useMeetingStore.setState({ agents, messages, selectedMessageId: 'non-existent' });

      renderWithProviders(<ThoughtTree />);
      const agentCard = screen.getByText('Agent1').closest('div[class*="rounded-md"]');
      expect(agentCard?.className).not.toContain('border-brand-500');
    });
  });

  describe('borrowRequest', () => {
    it('borrowRequest 为 null 时不显示借调区域', () => {
      useMeetingStore.setState({ agents: [], borrowRequest: null });

      renderWithProviders(<ThoughtTree />);
      expect(screen.queryByText('需要您介入')).toBeNull();
    });

    it('borrowRequest 存在时显示借调请求', () => {
      const agents: AgentInfo[] = [
        { id: 'a1', name: '小明', role: 'architect', state: 'idle' },
        { id: 'a2', name: '小红', role: 'engineer', state: 'idle' },
      ];
      useMeetingStore.setState({
        agents,
        borrowRequest: {
          id: 'br1',
          fromAgent: 'a1',
          toAgent: 'a2',
          reason: '需要工程支持',
          taskDescription: '协助实现',
        },
      });

      renderWithProviders(<ThoughtTree />);
      expect(screen.getByText('需要您介入')).toBeDefined();
      expect(screen.getByText('小明 请求借调 小红')).toBeDefined();
      expect(screen.getByText('需要工程支持')).toBeDefined();
    });
  });

  describe('消息分组逻辑', () => {
    it('每个 agent 有多条消息时 → recentByAgent 正确计算，highlight 仍正常工作', () => {
      const agents: AgentInfo[] = [
        { id: 'a1', name: 'Agent1', role: 'architect', state: 'idle' },
      ];
      // 5 条消息，recentByAgent 应只保留最后 3 条（useMemo 中 slice(-3)）
      const messages: MeetingMessage[] = [
        { id: 'msg1', agentId: 'a1', content: '1', timestamp: 1 },
        { id: 'msg2', agentId: 'a1', content: '2', timestamp: 2 },
        { id: 'msg3', agentId: 'a1', content: '3', timestamp: 3 },
        { id: 'msg4', agentId: 'a1', content: '4', timestamp: 4 },
        { id: 'msg5', agentId: 'a1', content: '5', timestamp: 5 },
      ];
      useMeetingStore.setState({ agents, messages, selectedMessageId: 'msg5' });

      renderWithProviders(<ThoughtTree />);

      // Agent 仍正常渲染
      expect(screen.getByText('Agent1')).toBeDefined();

      // 选中第 5 条消息时，Agent1 应高亮（messages?.find() 在全量消息上查找）
      const agentCard = screen.getByText('Agent1').closest('div[class*="rounded-md"]');
      expect(agentCard?.className).toContain('border-brand-500');
    });

    it('消息分布在不同 agent 时 → 各自独立分组，highlight 精确匹配', () => {
      const agents: AgentInfo[] = [
        { id: 'a1', name: 'Agent1', role: 'architect', state: 'idle' },
        { id: 'a2', name: 'Agent2', role: 'engineer', state: 'idle' },
      ];
      const messages: MeetingMessage[] = [
        { id: 'msg1', agentId: 'a1', content: 'A1-1', timestamp: 1 },
        { id: 'msg2', agentId: 'a2', content: 'A2-1', timestamp: 2 },
        { id: 'msg3', agentId: 'a1', content: 'A1-2', timestamp: 3 },
        { id: 'msg4', agentId: 'a2', content: 'A2-2', timestamp: 4 },
      ];
      useMeetingStore.setState({ agents, messages, selectedMessageId: 'msg2' });

      renderWithProviders(<ThoughtTree />);

      // msg2 属于 Agent2，只有 Agent2 高亮
      const agent1Card = screen.getByText('Agent1').closest('div[class*="rounded-md"]');
      expect(agent1Card?.className).not.toContain('border-brand-500');

      const agent2Card = screen.getByText('Agent2').closest('div[class*="rounded-md"]');
      expect(agent2Card?.className).toContain('border-brand-500');
    });
  });
});
