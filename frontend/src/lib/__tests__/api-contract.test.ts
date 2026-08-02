/**
 * API 契约测试：/auth/me 响应格式与 fetchUser 解包逻辑
 *
 * 本测试直接调用 auth-slice 的真实 fetchUser（mock api.get 返回值），
 * 验证不同后端响应格式经真实代码路径处理后，结果是否符合预期。
 * 不使用逻辑副本——所有断言都验证 useAuthStore.getState().fetchUser() 的真实行为。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { useAuthStore } from '@/stores/auth-slice';
import { api } from '@/lib/api';
import { makeUserInfo, makePluginAuthResponse, makeLegacyAuthResponse } from '@/test/test-utils';

vi.mock('@/lib/api', () => ({
  api: { get: vi.fn(), post: vi.fn() },
  isDemoMode: () => false,
}));

const mockApiGet = vi.mocked(api.get);

describe('API 契约测试 - fetchUser 真实代码路径', () => {
  beforeEach(() => {
    useAuthStore.setState({
      token: null,
      user: null,
      isAuthenticated: false,
      isLoading: true,
    });
    vi.clearAllMocks();
  });

  describe('插件路由格式 { user: {...} }', () => {
    it('fetchUser 正确解包嵌套 user 字段', async () => {
      const userInfo = makeUserInfo();
      mockApiGet.mockResolvedValue(makePluginAuthResponse(userInfo));

      useAuthStore.setState({ token: 'tok' });
      const result = await useAuthStore.getState().fetchUser();

      // 验证真实 fetchUser 返回的是解包后的 user 对象，不是 { user: {...} }
      expect(result).not.toBeNull();
      expect(result!.id).toBe('u1');
      expect(result!.username).toBe('testuser');
      expect(result!.display_name).toBe('测试用户');
      expect(result!.tenant_id).toBe('t1');

      // store 中的 user 也应该是解包后的
      expect(useAuthStore.getState().user).toEqual(result);
      expect(useAuthStore.getState().isAuthenticated).toBe(true);
    });

    it('tenants 数组在解包后被保留', async () => {
      const userInfo = makeUserInfo({
        tenants: [
          { id: 't1', name: '组织A', role: 'owner' },
          { id: 't2', name: '组织B', role: 'member' },
        ],
      });
      mockApiGet.mockResolvedValue(makePluginAuthResponse(userInfo));

      useAuthStore.setState({ token: 'tok' });
      const result = await useAuthStore.getState().fetchUser();

      expect(result!.tenants).toHaveLength(2);
      expect(result!.tenants[0].name).toBe('组织A');
      expect(result!.tenants[1].name).toBe('组织B');
    });
  });

  describe('旧路由扁平格式 { id, username, ... }', () => {
    it('fetchUser 兼容无 user 包裹的扁平响应', async () => {
      const userInfo = makeUserInfo();
      mockApiGet.mockResolvedValue(makeLegacyAuthResponse(userInfo));

      useAuthStore.setState({ token: 'tok' });
      const result = await useAuthStore.getState().fetchUser();

      expect(result).not.toBeNull();
      expect(result!.username).toBe('testuser');
      expect(result!.tenants).toHaveLength(1);
    });
  });

  describe('异常格式防御（真实 fetchUser 代码路径）', () => {
    it('tenants 缺失 → fetchUser 补为空数组', async () => {
      mockApiGet.mockResolvedValue({
        user: { id: 'u1', username: 'test', display_name: 'T', tenant_id: 't1' },
      });

      useAuthStore.setState({ token: 'tok' });
      const result = await useAuthStore.getState().fetchUser();

      expect(result).not.toBeNull();
      expect(Array.isArray(result!.tenants)).toBe(true);
      expect(result!.tenants).toHaveLength(0);
    });

    it('tenants 为 null → fetchUser 补为空数组', async () => {
      mockApiGet.mockResolvedValue({
        user: { id: 'u1', username: 'test', tenant_id: 't1', tenants: null },
      });

      useAuthStore.setState({ token: 'tok' });
      const result = await useAuthStore.getState().fetchUser();

      expect(Array.isArray(result!.tenants)).toBe(true);
      expect(result!.tenants).toHaveLength(0);
    });

    it('tenants 为字符串 → fetchUser 补为空数组', async () => {
      mockApiGet.mockResolvedValue({
        user: { id: 'u1', username: 'test', tenant_id: 't1', tenants: 'bad' },
      });

      useAuthStore.setState({ token: 'tok' });
      const result = await useAuthStore.getState().fetchUser();

      expect(Array.isArray(result!.tenants)).toBe(true);
      expect(result!.tenants).toHaveLength(0);
    });

    it('空对象响应 → fetchUser 不崩溃，tenants 补为空数组', async () => {
      mockApiGet.mockResolvedValue({});

      useAuthStore.setState({ token: 'tok' });
      const result = await useAuthStore.getState().fetchUser();

      // fetchUser 不应崩溃——返回的对象 tenants 应为数组
      expect(result).toBeDefined();
      expect(Array.isArray((result as { tenants?: unknown }).tenants)).toBe(true);
    });

    it('user 字段为 null → fetchUser 回退到整个响应', async () => {
      mockApiGet.mockResolvedValue({
        user: null,
        id: 'fallback',
        username: 'fallback-user',
        tenant_id: 't1',
      });

      useAuthStore.setState({ token: 'tok' });
      const result = await useAuthStore.getState().fetchUser();

      // null ?? response → 回退到 response 本身
      expect(result).toBeDefined();
      expect((result as { username?: string }).username).toBe('fallback-user');
      // tenants 在 response 上不存在 → 补为 []
      expect(Array.isArray((result as { tenants?: unknown }).tenants)).toBe(true);
    });
  });

  describe('UserInfo 关键字段完整性', () => {
    it('fetchUser 返回的对象上调用 tenants.find() 不崩溃', async () => {
      const userInfo = makeUserInfo();
      mockApiGet.mockResolvedValue(makePluginAuthResponse(userInfo));

      useAuthStore.setState({ token: 'tok' });
      const user = await useAuthStore.getState().fetchUser();

      // 这正是之前崩溃的代码路径：top-bar.tsx 中的 user.tenants.find(...)
      expect(() => {
        user!.tenants.find((t) => t.id === user!.tenant_id);
      }).not.toThrow();

      const current = user!.tenants.find((t) => t.id === user!.tenant_id);
      expect(current).toBeDefined();
      expect(current!.name).toBe('默认组织');
    });
  });
});
