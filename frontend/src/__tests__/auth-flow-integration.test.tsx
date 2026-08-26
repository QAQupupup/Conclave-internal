/**
 * 认证流程集成测试
 *
 * 覆盖完整链路：login → fetchUser → store 状态更新 → 组件渲染
 * 验证从 API 响应到 UI 显示的端到端一致性。
 *
 * 场景：
 * 1. 有 token 时，fetchUser 成功后组件正确显示用户信息
 * 2. 无 token 时，组件显示默认状态
 * 3. fetchUser 失败时，组件正确降级
 * 4. tenants 缺失时，整条链路不崩溃
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { screen } from '@testing-library/react';
import { useAuthStore } from '@/stores/auth-slice';
import { api } from '@/lib/api';
import { renderWithProviders, makeUserInfo, makePluginAuthResponse } from '@/test/test-utils';
import { TopBar } from '@/components/layout/top-bar';

// Mock 所有外部依赖
vi.mock('@/lib/api', () => ({
  api: { get: vi.fn(), post: vi.fn() },
  isDemoMode: () => false,
}));

vi.mock('@/providers/theme-context', () => ({
  useTheme: () => ({ theme: 'light', setTheme: vi.fn() }),
}));

vi.mock('@/lib/ws', () => ({
  wsClient: { sendControl: vi.fn() },
}));

vi.mock('@/hooks/use-toast', () => ({
  useToast: () => ({ toast: vi.fn() }),
}));

// Mock DropdownMenu：在 jsdom 中始终渲染 children，不依赖 pointer events
vi.mock('@/components/ui/dropdown-menu', () => ({
  DropdownMenu: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  DropdownMenuTrigger: ({ children, _asChild, ...props }: Record<string, unknown>) => <div {...props}>{children as React.ReactNode}</div>,
  DropdownMenuContent: ({ children, _asChild, ...props }: Record<string, unknown>) => <div {...props}>{children as React.ReactNode}</div>,
  DropdownMenuItem: ({ children, _asChild, ...props }: Record<string, unknown>) => <div {...props}>{children as React.ReactNode}</div>,
  DropdownMenuLabel: ({ children, _asChild, ...props }: Record<string, unknown>) => <div {...props}>{children as React.ReactNode}</div>,
  DropdownMenuSeparator: () => <hr />,
  DropdownMenuSub: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  DropdownMenuSubContent: ({ children, _asChild, ...props }: Record<string, unknown>) => <div {...props}>{children as React.ReactNode}</div>,
  DropdownMenuSubTrigger: ({ children, _asChild, ...props }: Record<string, unknown>) => <div {...props}>{children as React.ReactNode}</div>,
}));

const mockApiGet = vi.mocked(api.get);

describe('认证流程集成测试', () => {
  beforeEach(() => {
    useAuthStore.setState({
      token: null,
      user: null,
      isAuthenticated: false,
      isLoading: true,
    });
    vi.clearAllMocks();
  });

  it('完整链路：token 存在 → fetchUser 成功 → TopBar 显示用户名', async () => {
    const userInfo = makeUserInfo({ display_name: '集成测试用户', username: 'integration' });
    mockApiGet.mockResolvedValue(makePluginAuthResponse(userInfo));

    // 模拟有 token 的场景
    useAuthStore.setState({ token: 'valid-token', isLoading: false });

    // 执行 fetchUser
    await useAuthStore.getState().fetchUser();

    // 验证 store 状态
    expect(useAuthStore.getState().isAuthenticated).toBe(true);
    expect(useAuthStore.getState().user).not.toBeNull();
    expect(useAuthStore.getState().user!.display_name).toBe('集成测试用户');

    // 渲染组件
    renderWithProviders(<TopBar />);

    // 组件应显示用户名
    expect(screen.getByTitle('集成测试用户')).toBeDefined();
  });

  it('完整链路：tenants 缺失 → fetchUser 补全 → TopBar IIFE 不渲染当前组织', async () => {
    // 模拟后端返回缺少 tenants 的用户
    const userWithoutTenants = {
      id: 'u1',
      username: 'notenant',
      display_name: '无组织用户',
      tenant_id: 't1',
    };
    mockApiGet.mockResolvedValue({ user: userWithoutTenants });

    useAuthStore.setState({ token: 'valid-token' });
    await useAuthStore.getState().fetchUser();

    // tenants 应被补为 []
    const user = useAuthStore.getState().user;
    expect(user).not.toBeNull();
    expect(Array.isArray(user!.tenants)).toBe(true);

    // 渲染 TopBar（DropdownMenu 已 mock 为始终渲染 children）
    renderWithProviders(<TopBar />);

    // IIFE 中 tenants 为 [] → find() 返回 undefined → 不渲染当前组织
    expect(screen.queryByText('默认组织')).toBeNull();

    expect(screen.getByTitle('无组织用户')).toBeDefined();
  });

  it('完整链路：fetchUser 失败 → store 清理 → TopBar 显示默认值', async () => {
    mockApiGet.mockRejectedValue(new Error('Network error'));

    useAuthStore.setState({ token: 'expired-token' });
    const result = await useAuthStore.getState().fetchUser();

    // fetchUser 应返回 null
    expect(result).toBeNull();
    expect(useAuthStore.getState().user).toBeNull();
    expect(useAuthStore.getState().isAuthenticated).toBe(false);

    // TopBar 应显示默认用户名
    renderWithProviders(<TopBar />);
    expect(screen.getByTitle('用户')).toBeDefined();
  });

  it('完整链路：多租户用户 → IIFE 渲染当前组织，TenantSwitcher 显示所有组织', async () => {
    const userInfo = makeUserInfo({
      display_name: '多租户用户',
      tenant_id: 't1',
      tenants: [
        { id: 't1', name: '主组织', role: 'owner' },
        { id: 't2', name: '副组织', role: 'member' },
      ],
    });
    mockApiGet.mockResolvedValue(makePluginAuthResponse(userInfo));

    useAuthStore.setState({ token: 'valid-token' });
    await useAuthStore.getState().fetchUser();

    // 验证 store 中 tenants 被正确设置
    expect(useAuthStore.getState().user!.tenants).toHaveLength(2);

    // 渲染 TopBar（DropdownMenu 已 mock 为始终渲染 children）
    renderWithProviders(<TopBar />);

    // IIFE 应渲染当前组织名称（tenants.find() 返回 t1 → "主组织"）
    const currentTenantTexts = screen.getAllByText('主组织');
    expect(currentTenantTexts.length).toBeGreaterThanOrEqual(1);

    // TenantSwitcher 应列出所有组织（SubContent 也已 mock 为始终渲染）
    expect(screen.getByText('副组织')).toBeDefined();
  });

  it('完整链路：单租户用户 → TenantSwitcher 不渲染', async () => {
    const userInfo = makeUserInfo({
      tenant_id: 't1',
      tenants: [{ id: 't1', name: '唯一组织', role: 'owner' }],
    });
    mockApiGet.mockResolvedValue(makePluginAuthResponse(userInfo));

    useAuthStore.setState({ token: 'valid-token' });
    await useAuthStore.getState().fetchUser();

    renderWithProviders(<TopBar />);

    // 单租户不应显示切换器
    expect(screen.queryByText('切换租户')).toBeNull();
  });

  it('store 状态一致性：fetchUser 后 isAuthenticated 和 user 同步', async () => {
    const userInfo = makeUserInfo();
    mockApiGet.mockResolvedValue(makePluginAuthResponse(userInfo));

    useAuthStore.setState({ token: 'valid-token' });

    // fetchUser 前
    expect(useAuthStore.getState().isAuthenticated).toBe(false);
    expect(useAuthStore.getState().user).toBeNull();

    await useAuthStore.getState().fetchUser();

    // fetchUser 后：两个状态必须同步更新
    const state = useAuthStore.getState();
    expect(state.isAuthenticated).toBe(true);
    expect(state.user).not.toBeNull();
    expect(state.isLoading).toBe(false);
  });
});
