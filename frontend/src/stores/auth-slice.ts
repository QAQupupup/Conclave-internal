import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { AuthState, UserInfo } from '@/types';
import { api } from '@/lib/api';

interface AuthStore extends AuthState {
  hasHydrated: boolean;
  setAuth: (token: string, user: UserInfo) => void;
  setToken: (token: string) => void;
  setUser: (user: UserInfo) => void;
  fetchUser: () => Promise<UserInfo | null>;
  switchTenant: (tenantId: string) => Promise<void>;
  logout: () => void;
  setLoading: (loading: boolean) => void;
  silentRefresh: () => Promise<boolean>;
}

export const useAuthStore = create<AuthStore>()(
  persist(
    (set, get) => ({
      token: null,
      user: null,
      isAuthenticated: false,
      isLoading: true,
      hasHydrated: false,
      setAuth: (token, user) => set({ token, user, isAuthenticated: true, isLoading: false }),
      setToken: (token) => set({ token }),
      setUser: (user) => set({ user }),
      setLoading: (loading) => set({ isLoading: loading }),
      fetchUser: async () => {
        const token = get().token;
        if (!token) {
          set({ isLoading: false, isAuthenticated: false, user: null });
          return null;
        }
        try {
          const AUTH_FETCH_TIMEOUT_MS = 10000;
          const fetchPromise = api.get<UserInfo | { user: UserInfo }>('/auth/me');
          const timeoutPromise = new Promise<never>((_, reject) =>
            setTimeout(() => reject(new Error('auth timeout')), AUTH_FETCH_TIMEOUT_MS)
          );
          const res = await Promise.race([fetchPromise, timeoutPromise]);
          const user: UserInfo = (res as { user?: UserInfo }).user ?? (res as UserInfo);
          if (user && !Array.isArray(user.tenants)) user.tenants = [];
          if (user && user.tenant_id == null) user.tenant_id = '';
          set({ user, isAuthenticated: true, isLoading: false });
          return user;
        } catch {
          set({ token: null, user: null, isAuthenticated: false, isLoading: false });
          return null;
        }
      },
      switchTenant: async (tenantId: string) => {
        const result = await api.post<{ access_token: string }>('/tenants/switch', { tenant_id: tenantId });
        await get().fetchUser();
        if (result.access_token) set({ token: result.access_token });
      },
      logout: () => {
        api.post('/auth/logout').catch(() => {});
        import('@/lib/ws').then(({ wsClient }) => wsClient.disconnect()).catch(() => {});
        set({ token: null, user: null, isAuthenticated: false, isLoading: false });
        window.location.href = '/login';
      },
      silentRefresh: async () => {
        try {
          const csrfMatch = typeof document !== 'undefined'
            ? document.cookie.match(/(?:^|;\s*)csrf_token=([^;]+)/)
            : null;
          const csrfToken = csrfMatch ? decodeURIComponent(csrfMatch[1]) : null;
          const headers: Record<string, string> = { 'Content-Type': 'application/json' };
          if (csrfToken) headers['X-CSRF-Token'] = csrfToken;
          const res = await fetch('/auth/refresh', {
            method: 'POST',
            headers,
            credentials: 'include',
          });
          if (!res.ok) return false;
          const data = await res.json();
          if (data.access_token) {
            set({ token: data.access_token });
            const user = await get().fetchUser();
            return !!user;
          }
          return false;
        } catch {
          return false;
        }
      },
    }),
    {
      name: 'conclave:auth',
      version: 1, // ⚠️ If you bump this version, you MUST also update PERSIST_VERSION in App.tsx AuthInit
      partialize: (state) => ({ token: state.token }),
      onRehydrateStorage: () => (state, error) => {
        // 只标记 hydration 完成，不在此处调用 fetchUser/silentRefresh。
        // 认证初始化由 App.tsx 的 AuthInit 组件统一处理，避免竞态条件。
        if (error) {
          useAuthStore.setState({ hasHydrated: true, isLoading: false });
          return;
        }
        useAuthStore.setState({ hasHydrated: true });
      },
      migrate: (persistedState: unknown, version: number) => {
        if (version < 1) {
          const s = persistedState as { token?: string | null } | undefined;
          return { token: s?.token ?? null };
        }
        return persistedState;
      },
    }
  )
);

