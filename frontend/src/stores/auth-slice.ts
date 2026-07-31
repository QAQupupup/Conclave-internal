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
          const user = await api.get<UserInfo>('/auth/me');
          set({ user, isAuthenticated: true, isLoading: false });
          return user;
        } catch {
          // Token invalid, logout
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
        set({ token: null, user: null, isAuthenticated: false, isLoading: false });
        // Redirect to login
        window.location.href = '/login';
      },
    }),
    {
      name: 'conclave:auth',
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
    }
  )
);
