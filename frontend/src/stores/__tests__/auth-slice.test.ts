/**
 * auth-slice 单元测试
 *
 * 覆盖场景：
 * 1. fetchUser 正确解包插件路由的嵌套响应 { user: {...} }
 * 2. fetchUser 兼容旧路由的扁平响应 { id, username, ... }
 * 3. fetchUser 在 tenants 缺失时补为空数组（防止 .find() 崩溃）
 * 4. fetchUser 在无 token 时直接返回 null
 * 5. fetchUser 在 API 失败时清理状态
 * 6. logout 清理所有认证状态
 * 7. setAuth 正确设置所有字段
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { useAuthStore } from '@/stores/auth-slice';
import { api } from '@/lib/api';
import { makeUserInfo, makePluginAuthResponse, makeLegacyAuthResponse } from '@/test/test-utils';

// Mock api 模块
vi.mock('@/lib/api', () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
  },
  isDemoMode: () => false,
}));

const mockApiGet = vi.mocked(api.get);
const mockApiPost = vi.mocked(api.post);

describe('auth-slice', () => {
  beforeEach(() => {
    // 每个测试前重置 store 状态
    useAuthStore.setState({
      token: null,
      user: null,
      isAuthenticated: false,
      isLoading: true,
    });
    vi.clearAllMocks();
  });

  // ===== fetchUser 响应格式兼容 =====

  describe('fetchUser - 响应格式兼容', () => {
    it('正确解包插件路由的嵌套格式 { user: {...} }', async () => {
      const userInfo = makeUserInfo();
      mockApiGet.mockResolvedValue(makePluginAuthResponse(userInfo));

      useAuthStore.setState({ token: 'valid-token' });
      const result = await useAuthStore.getState().fetchUser();

      expect(result).not.toBeNull();
      expect(result!.username).toBe('testuser');
      expect(result!.tenants).toHaveLength(1);
      expect(result!.tenants[0].id).toBe('t1');

      // store 中的 user 也应该是解包后的
      const storeUser = useAuthStore.getState().user;
      expect(storeUser).not.toBeNull();
      expect(storeUser!.username).toBe('testuser');
      expect(useAuthStore.getState().isAuthenticated).toBe(true);
    });

    it('兼容旧路由的扁平格式 { id, username, tenants, ... }', async () => {
      const userInfo = makeUserInfo();
      mockApiGet.mockResolvedValue(makeLegacyAuthResponse(userInfo));

      useAuthStore.setState({ token: 'valid-token' });
      const result = await useAuthStore.getState().fetchUser();

      expect(result).not.toBeNull();
      expect(result!.username).toBe('testuser');
      expect(result!.tenants).toHaveLength(1);
    });

    it('当响应为空对象时，tenants 仍被补为空数组，不崩溃', async () => {
      // 极端情况：后端返回空对象 {}
      // fetchUser 逻辑: res.user ?? res → {} (truthy) → tenants 防御补为 []
      mockApiGet.mockResolvedValue({});

      useAuthStore.setState({ token: 'valid-token' });
      const result = await useAuthStore.getState().fetchUser();

      // 不应崩溃，tenants 必须是数组（核心防御）
      expect(result).not.toBeNull();
      expect(Array.isArray(result!.tenants)).toBe(true);
      expect(result!.tenants).toHaveLength(0);
      // store 状态应正确更新
      expect(useAuthStore.getState().isAuthenticated).toBe(true);
      expect(useAuthStore.getState().isLoading).toBe(false);
    });
  });

  // ===== tenants 防御 =====

  describe('fetchUser - tenants 防御', () => {
    it('后端未返回 tenants 字段时，补为空数组', async () => {
      // 模拟后端返回没有 tenants 的用户对象
      const userWithoutTenants = { id: 'u1', username: 'testuser', display_name: 'Test', tenant_id: 't1' };
      mockApiGet.mockResolvedValue({ user: userWithoutTenants });

      useAuthStore.setState({ token: 'valid-token' });
      const result = await useAuthStore.getState().fetchUser();

      expect(result).not.toBeNull();
      expect(Array.isArray(result!.tenants)).toBe(true);
      expect(result!.tenants).toHaveLength(0);
    });

    it('tenants 为 null 时，补为空数组', async () => {
      const userWithNullTenants = {
        id: 'u1', username: 'testuser', display_name: 'Test',
        tenant_id: 't1', tenants: null,
      };
      mockApiGet.mockResolvedValue({ user: userWithNullTenants });

      useAuthStore.setState({ token: 'valid-token' });
      const result = await useAuthStore.getState().fetchUser();

      expect(Array.isArray(result!.tenants)).toBe(true);
    });

    it('tenants 为非数组值时，补为空数组', async () => {
      const userWithStringTenants = {
        id: 'u1', username: 'testuser', display_name: 'Test',
        tenant_id: 't1', tenants: 'invalid',
      };
      mockApiGet.mockResolvedValue({ user: userWithStringTenants });

      useAuthStore.setState({ token: 'valid-token' });
      const result = await useAuthStore.getState().fetchUser();

      expect(Array.isArray(result!.tenants)).toBe(true);
    });

    it('tenants 正常时保持不变', async () => {
      const userInfo = makeUserInfo({
        tenants: [
          { id: 't1', name: '组织A', role: 'owner' },
          { id: 't2', name: '组织B', role: 'member' },
        ],
      });
      mockApiGet.mockResolvedValue(makePluginAuthResponse(userInfo));

      useAuthStore.setState({ token: 'valid-token' });
      const result = await useAuthStore.getState().fetchUser();

      expect(result!.tenants).toHaveLength(2);
      expect(result!.tenants[0].name).toBe('组织A');
    });
  });

  // ===== 边界条件 =====

  describe('fetchUser - 边界条件', () => {
    it('无 token 时直接返回 null，不发 API 请求', async () => {
      useAuthStore.setState({ token: null });
      const result = await useAuthStore.getState().fetchUser();

      expect(result).toBeNull();
      expect(mockApiGet).not.toHaveBeenCalled();
      expect(useAuthStore.getState().isLoading).toBe(false);
      expect(useAuthStore.getState().isAuthenticated).toBe(false);
    });

    it('API 返回 401 时清理状态并返回 null', async () => {
      mockApiGet.mockRejectedValue(new Error('认证失败'));
      useAuthStore.setState({ token: 'expired-token', user: makeUserInfo() });

      const result = await useAuthStore.getState().fetchUser();

      expect(result).toBeNull();
      expect(useAuthStore.getState().token).toBeNull();
      expect(useAuthStore.getState().user).toBeNull();
      expect(useAuthStore.getState().isAuthenticated).toBe(false);
    });

    it('API 网络错误时清理状态', async () => {
      mockApiGet.mockRejectedValue(new TypeError('Network error'));
      useAuthStore.setState({ token: 'some-token' });

      const result = await useAuthStore.getState().fetchUser();

      expect(result).toBeNull();
      expect(useAuthStore.getState().user).toBeNull();
    });
  });

  // ===== logout =====

  describe('logout', () => {
    it('清理所有认证状态并调用 logout API', () => {
      mockApiPost.mockResolvedValue(undefined as never);
      useAuthStore.setState({
        token: 'valid-token',
        user: makeUserInfo(),
        isAuthenticated: true,
      });

      useAuthStore.getState().logout();

      // 验证调用了后端 logout 端点
      expect(mockApiPost).toHaveBeenCalledWith('/auth/logout');
      // 验证所有认证状态被清理
      expect(useAuthStore.getState().token).toBeNull();
      expect(useAuthStore.getState().user).toBeNull();
      expect(useAuthStore.getState().isAuthenticated).toBe(false);
    });

    it('logout API 失败时仍清理本地状态', () => {
      mockApiPost.mockRejectedValue(new Error('Network error'));
      useAuthStore.setState({
        token: 'valid-token',
        user: makeUserInfo(),
        isAuthenticated: true,
      });

      useAuthStore.getState().logout();

      // 即使 API 失败，本地状态仍应清理（fire and forget）
      expect(useAuthStore.getState().token).toBeNull();
      expect(useAuthStore.getState().user).toBeNull();
      expect(useAuthStore.getState().isAuthenticated).toBe(false);
    });
  });

  // ===== setAuth =====

  describe('setAuth', () => {
    it('正确设置 token、user 和认证状态', () => {
      const userInfo = makeUserInfo();
      useAuthStore.getState().setAuth('new-token', userInfo);

      const state = useAuthStore.getState();
      expect(state.token).toBe('new-token');
      expect(state.user).toEqual(userInfo);
      expect(state.isAuthenticated).toBe(true);
      expect(state.isLoading).toBe(false);
    });
  });
});
