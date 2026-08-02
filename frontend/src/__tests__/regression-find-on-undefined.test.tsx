/**
 * 回归测试：.find() on undefined 崩溃路径
 *
 * 本次事故根因：user.tenants 为 undefined 时，代码调用 .find() 导致
 * "Cannot read properties of undefined (reading 'find')" 崩溃。
 *
 * 本文件覆盖所有涉及 .find() 调用的真实代码路径，确保此类崩溃不再发生。
 * 每个测试都调用真实的业务代码（store action / 组件渲染 / client 方法），
 * 不测试 JavaScript 语言特性。
 *
 * 涉及文件：
 * - auth-slice.ts: fetchUser 中 tenants 防御（ROOT FIX：确保 tenants 始终为数组）
 * - thought-tree.tsx: messages?.find() 用于高亮判断
 * - ag-ui/client.ts: dispatchToStore 中 messages?.find() 用于消息查找
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { screen } from '@testing-library/react';
import { useAuthStore } from '@/stores/auth-slice';
import { useMeetingStore } from '@/stores/meeting-slice';
import { api } from '@/lib/api';
import { makeUserInfo } from '@/test/test-utils';
import { agUIClient } from '@/lib/ag-ui/client';
import { ThoughtTree } from '@/components/meeting/thought-tree';
import { renderWithProviders } from '@/test/test-utils';
import type { AgentInfo, MeetingMessage } from '@/types';

vi.mock('@/lib/api', () => ({
  api: { get: vi.fn(), post: vi.fn() },
  isDemoMode: () => false,
}));

// Mock SVG icons（ThoughtTree 依赖）
vi.mock('@/components/ui/svg-icons', () => ({
  AgentAvatar: ({ agentId }: { agentId: string }) => (
    <div data-testid={`avatar-${agentId}`} />
  ),
  StatusDot: ({ status }: { status: string }) => (
    <div data-testid="status-dot">{status}</div>
  ),
}));

const mockApiGet = vi.mocked(api.get);

describe('回归测试：.find() on undefined 崩溃路径', () => {
  beforeEach(() => {
    useAuthStore.setState({
      token: null,
      user: null,
      isAuthenticated: false,
      isLoading: true,
    });
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

  // ===== auth-slice: fetchUser tenants 防御（ROOT FIX）=====
  // fetchUser 确保 tenants 始终为数组，防止下游 .find() 崩溃

  describe('auth-slice fetchUser - tenants 必须为数组', () => {
    it('后端未返回 tenants → fetchUser 补为 []，后续 .find() 不崩溃', async () => {
      mockApiGet.mockResolvedValue({ user: { id: 'u1', username: 'test', tenant_id: 't1' } });
      useAuthStore.setState({ token: 'tok' });

      const user = await useAuthStore.getState().fetchUser();

      expect(user).not.toBeNull();
      expect(Array.isArray(user!.tenants)).toBe(true);
      expect(user!.tenants).toHaveLength(0);
      // 直接调用 .find() 验证不会崩溃
      expect(user!.tenants.find((t) => t.id === 't1')).toBeUndefined();
    });

    it('tenants 为 null → fetchUser 补为 []', async () => {
      mockApiGet.mockResolvedValue({
        user: { id: 'u1', username: 'test', tenant_id: 't1', tenants: null },
      });
      useAuthStore.setState({ token: 'tok' });

      const user = await useAuthStore.getState().fetchUser();

      expect(Array.isArray(user!.tenants)).toBe(true);
      expect(user!.tenants).toHaveLength(0);
    });

    it('tenants 为非数组 → fetchUser 补为 []', async () => {
      mockApiGet.mockResolvedValue({
        user: { id: 'u1', username: 'test', tenant_id: 't1', tenants: 'bad' },
      });
      useAuthStore.setState({ token: 'tok' });

      const user = await useAuthStore.getState().fetchUser();

      expect(Array.isArray(user!.tenants)).toBe(true);
    });

    it('tenants 为正常数组 → 保持不变，.find() 正常工作', async () => {
      const userInfo = makeUserInfo({
        tenants: [
          { id: 't1', name: '组织A', role: 'owner' },
          { id: 't2', name: '组织B', role: 'member' },
        ],
      });
      mockApiGet.mockResolvedValue({ user: userInfo });
      useAuthStore.setState({ token: 'tok' });

      const user = await useAuthStore.getState().fetchUser();

      expect(user!.tenants).toHaveLength(2);
      const current = user!.tenants.find((t) => t.id === user!.tenant_id);
      expect(current).toBeDefined();
      expect(current!.name).toBe('组织A');
    });
  });

  // ===== thought-tree: messages?.find() 高亮逻辑 =====
  // 真实渲染组件，验证 .find() 在空数组和有数据时都不崩溃

  describe('ThoughtTree - messages?.find() 高亮路径', () => {
    it('messages 为空数组 + selectedMessageId 有值 → 不崩溃，无 agent 高亮', () => {
      const agents: AgentInfo[] = [
        { id: 'a1', name: 'Agent1', role: 'architect', state: 'idle' },
      ];
      useMeetingStore.setState({
        agents,
        messages: [],
        selectedMessageId: 'non-existent',
      });

      renderWithProviders(<ThoughtTree />);

      // Agent 正常渲染，不高亮（无 border-brand-500/30 class）
      expect(screen.getByText('Agent1')).toBeDefined();
      const agentCard = screen.getByText('Agent1').closest('div[class*="rounded-md"]');
      expect(agentCard?.className).not.toContain('border-brand-500');
    });

    it('messages 有数据 + selectedMessageId 匹配 → 对应 agent 高亮', () => {
      const agents: AgentInfo[] = [
        { id: 'a1', name: 'Agent1', role: 'architect', state: 'idle' },
        { id: 'a2', name: 'Agent2', role: 'engineer', state: 'idle' },
      ];
      const messages: MeetingMessage[] = [
        { id: 'msg1', agentId: 'a1', content: '来自 Agent1', timestamp: 1 },
        { id: 'msg2', agentId: 'a2', content: '来自 Agent2', timestamp: 2 },
      ];
      useMeetingStore.setState({ agents, messages, selectedMessageId: 'msg1' });

      renderWithProviders(<ThoughtTree />);

      // Agent1 应该高亮（有 border-brand-500/30 class）
      const agent1Card = screen.getByText('Agent1').closest('div[class*="rounded-md"]');
      expect(agent1Card?.className).toContain('border-brand-500');

      // Agent2 不应该高亮
      const agent2Card = screen.getByText('Agent2').closest('div[class*="rounded-md"]');
      expect(agent2Card?.className).not.toContain('border-brand-500');
    });

    it('messages 有数据 + selectedMessageId 不匹配 → 无 agent 高亮', () => {
      const agents: AgentInfo[] = [
        { id: 'a1', name: 'Agent1', role: 'architect', state: 'idle' },
      ];
      const messages: MeetingMessage[] = [
        { id: 'msg1', agentId: 'a1', content: 'Hello', timestamp: 1 },
      ];
      useMeetingStore.setState({ agents, messages, selectedMessageId: 'non-existent' });

      renderWithProviders(<ThoughtTree />);

      const agentCard = screen.getByText('Agent1').closest('div[class*="rounded-md"]');
      expect(agentCard?.className).not.toContain('border-brand-500');
    });

    it('selectedMessageId 为 null → 无 agent 高亮', () => {
      const agents: AgentInfo[] = [
        { id: 'a1', name: 'Agent1', role: 'architect', state: 'idle' },
      ];
      const messages: MeetingMessage[] = [
        { id: 'msg1', agentId: 'a1', content: 'Hello', timestamp: 1 },
      ];
      useMeetingStore.setState({ agents, messages, selectedMessageId: null });

      renderWithProviders(<ThoughtTree />);

      const agentCard = screen.getByText('Agent1').closest('div[class*="rounded-md"]');
      expect(agentCard?.className).not.toContain('border-brand-500');
    });
  });

  // ===== ag-ui/client.ts: dispatchToStore 中 messages?.find() =====
  // 调用真实的 handleRawMessage，验证 .find() 在空消息列表时不崩溃

  describe('ag-ui/client.ts - dispatchToStore 中 messages?.find()', () => {
    it('TEXT_MESSAGE_END 在 messages 为空时 → .find() 返回 undefined，不崩溃', () => {
      // messages 为空数组
      useMeetingStore.setState({ messages: [] });

      // 模拟后端发送 agent.speak 消息（包含 is_start + content，触发 TEXT_MESSAGE_END）
      expect(() => {
        agUIClient.handleRawMessage({
          type: 'agent.speak',
          agent_id: 'a1',
          agent_name: 'Agent1',
          agent_role: 'architect',
          message_id: 'msg-end-1',
          content: '完整消息',
          is_start: true,
        });
      }).not.toThrow();

      // 消息应被正确添加到 store
      const messages = useMeetingStore.getState().messages;
      expect(messages).toHaveLength(1);
      expect(messages[0].id).toBe('msg-end-1');
      expect(messages[0].content).toBe('完整消息');
    });

    it('THINKING_END 在 messages 为空时 → .find() 返回 undefined，不崩溃', () => {
      useMeetingStore.setState({ messages: [] });

      // 模拟 agent.thinking 消息（包含 is_start + is_end，触发 THINKING_START + THINKING_END）
      expect(() => {
        agUIClient.handleRawMessage({
          type: 'agent.thinking',
          agent_id: 'a1',
          message_id: 'thinking-end-1',
          delta: '思考内容',
          is_start: true,
          is_end: true,
        });
      }).not.toThrow();

      // 思考消息应被添加（THINKING_START 添加，THINKING_END 调用 finalizeMessage）
      const messages = useMeetingStore.getState().messages;
      const thinkingMsg = messages.find((m) => m.id === 'thinking-end-1');
      expect(thinkingMsg).toBeDefined();
      // finalizeMessage 将 isThinking 设为 false（思考已结束）
      expect(thinkingMsg?.isThinking).toBe(false);
      // thinking 内容应被保留
      expect(thinkingMsg?.thinking).toBe('思考内容');
    });

    it('TEXT_MESSAGE_END 在 messages 有匹配项时 → .find() 正确返回消息', () => {
      // 先添加一条消息（通过 TEXT_MESSAGE_START）
      agUIClient.handleRawMessage({
        type: 'agent.speak',
        agent_id: 'a1',
        agent_name: 'Agent1',
        agent_role: 'architect',
        message_id: 'msg-existing',
        is_start: true,
      });

      // 确认消息已添加
      expect(useMeetingStore.getState().messages).toHaveLength(1);

      // 再发送 delta 和 end
      agUIClient.handleRawMessage({
        type: 'agent.speak',
        agent_id: 'a1',
        message_id: 'msg-existing',
        delta: '增量内容',
      });

      agUIClient.handleRawMessage({
        type: 'agent.speak',
        agent_id: 'a1',
        message_id: 'msg-existing',
        content: '最终内容',
        is_end: true,
      });

      // 消息应被 finalize
      const msg = useMeetingStore.getState().messages.find((m) => m.id === 'msg-existing');
      expect(msg).toBeDefined();
      expect(msg?.content).toBe('最终内容');
    });
  });
});
