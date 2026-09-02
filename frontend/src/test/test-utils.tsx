/**
 * 测试工具集：提供 render with providers、mock factory 等通用能力。
 *
 * 解决的核心问题：
 * - 组件依赖 router / store / theme 等 context，单独 render 会崩溃
 * - API 调用需要 mock，避免真实网络请求
 * - Zustand store 需要在每个测试前重置
 */
import * as React from 'react';
import { render, type RenderOptions } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

/**
 * 创建带所有 provider 的 wrapper（router + react-query）
 */
export function createWrapper(initialEntries: string[] = ['/']) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  return function Wrapper({ children }: { children: React.ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={initialEntries}>{children}</MemoryRouter>
      </QueryClientProvider>
    );
  };
}

/**
 * 带 provider 的 render 快捷方法
 */
export function renderWithProviders(
  ui: React.ReactElement,
  options?: Omit<RenderOptions, 'wrapper'> & { initialEntries?: string[] },
) {
  const { initialEntries = ['/'], ...renderOptions } = options ?? {};
  return render(ui, { wrapper: createWrapper(initialEntries), ...renderOptions });
}

/**
 * 构造合法的 UserInfo 对象（所有必填字段都有值）
 */
export function makeUserInfo(overrides: Partial<{
  id: string;
  username: string;
  display_name: string;
  tenant_id: string;
  tenants: Array<{ id: string; name: string; role: string }>;
  email: string;
  role: string;
}> = {}) {
  return {
    id: 'u1',
    username: 'testuser',
    display_name: '测试用户',
    tenant_id: 't1',
    tenants: [{ id: 't1', name: '默认组织', role: 'owner' }],
    email: 'test@example.com',
    role: 'member',
    ...overrides,
  };
}

/**
 * 模拟后端插件路由的 /auth/me 响应格式（嵌套在 user 字段下）
 */
export function makePluginAuthResponse(userInfo = makeUserInfo()) {
  return { user: userInfo };
}

/**
 * 模拟旧路由的 /auth/me 响应格式（扁平字段直接返回）
 */
export function makeLegacyAuthResponse(userInfo = makeUserInfo()) {
  return { ...userInfo };
}

/**
 * 重置所有 zustand store 到初始状态
 * 每个测试的 beforeEach 中调用，避免测试间状态泄漏
 */
export async function resetAllStores() {
  // 动态 import 避免循环依赖
  const { useAuthStore } = await import('@/stores/auth-slice');
  const { useMeetingStore } = await import('@/stores/meeting-slice');
  const { useUIStore } = await import('@/stores/ui-slice');

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
  // UI store 重置到默认（不强制，避免影响 UI 测试）
  useUIStore.setState({
    commandPaletteOpen: false,
    activeCanvas: null,
    insightsCanvasSize: 'M',
  });
}
