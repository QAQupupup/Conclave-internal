import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { AuthState, UserInfo, TenantInfo } from '@/types';
import { api } from '@/lib/api';

interface AuthStore extends AuthState {
  setAuth: (token: string, user: UserInfo) => void;
  setUser: (user: UserInfo) => void;
  fetchUser: () => Promise<UserInfo | null>;
  switchTenant: (tenantId: string) => Promise<void>;
  logout: () => void;
  setLoading: (loading: boolean) => void;
}

export const useAuthStore = create<AuthStore>()(
  persist(
    (set, get) => ({
      token: null,
      user: null,
      isAuthenticated: false,
      isLoading: true, // Start as loading until we verify token
      setAuth: (token, user) => set({ token, user, isAuthenticated: true, isLoading: false }),
      setUser: (user) => set({ user }),
      setLoading: (loading) => set({ isLoading: loading }),
      fetchUser: async () => {
        const token = get().token;
        if (!token) {
          set({ isLoading: false, isAuthenticated: false, user: null });
          return null;
        }
        try {
          const AUTH_FETCH_TIMEOUT_MS = 10_000;
          const fetchPromise = api.get<UserInfo | { user: UserInfo }>('/auth/me');
          const timeoutPromise = new Promise<never>((_, reject) =>
            setTimeout(() => reject(new Error('认证请求超时')), AUTH_FETCH_TIMEOUT_MS)
          );
          const res = await Promise.race([fetchPromise, timeoutPromise]);

          // 兼容两种响应格式：
          // - 旧路由 (app/routers/auth.py): MeResponse(**user_info) → 直接返回字段
          // - 插件路由 (plugins/builtin/auth/router.py): MeResponse(user={...}) → 嵌套在 user 字段
          const user: UserInfo = (res as { user?: UserInfo }).user ?? (res as UserInfo);
          // 确保 tenants 始终为数组（防止后端未返回该字段导致 .find() 崩溃）
          if (user && !Array.isArray(user.tenants)) {
            user.tenants = [];
          }
          // 确保 tenant_id 不为 null（前端类型声明为 string）
          if (user && user.tenant_id == null) {
            user.tenant_id = '';
          }
          set({ user, isAuthenticated: true, isLoading: false });
          return user;
        } catch {
          // Token invalid or timeout, logout
          set({ token: null, user: null, isAuthenticated: false, isLoading: false });
          return null;
        }
      },
      switchTenant: async (tenantId: string) => {
        const result = await api.post<{ access_token: string }>('/tenants/switch', { tenant_id: tenantId });
        // After switching, fetch updated user
        await get().fetchUser();
        // Update token if returned
        if (result.access_token) {
          set({ token: result.access_token });
        }
      },
      logout: () => {
        // Fire and forget logout API
        api.post('/auth/logout').catch(() => {});
        // 清理 WebSocket 连接（硬跳转前主动断开）
        import('@/lib/ws').then(({ wsClient }) => wsClient.disconnect()).catch(() => {});
        set({ token: null, user: null, isAuthenticated: false, isLoading: false });
        // Hard redirect 到登录页，自动清理所有内存状态
        window.location.href = '/login';
      },
    }),
    {
      name: 'conclave:auth',
      version: 1,
      // Only persist token, not user (we refetch on load) or loading state
      partialize: (state) => ({ token: state.token }),
      onRehydrateStorage: () => (state) => {
        // After rehydration, if we have a token, fetch user info
        if (state?.token) {
          state.fetchUser();
        } else {
          state?.setLoading(false);
        }
      },
      migrate: (persistedState: unknown, version: number) => {
        // Version 0 → 1: only keep token, discard everything else
        if (version < 1) {
          const s = persistedState as { token?: string | null } | undefined;
          return { token: s?.token ?? null };
        }
        return persistedState;
      },
    }
  )
);
