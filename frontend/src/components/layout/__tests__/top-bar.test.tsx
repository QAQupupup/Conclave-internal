/**
 * TopBar 组件测试
 *
 * 覆盖场景：
 * 1. TenantSwitcher 在 user 为 null 时不崩溃
 * 2. TenantSwitcher 在 tenants 为 undefined 时不崩溃
 * 3. TenantSwitcher 在 tenants 为空数组时不渲染
 * 4. TenantSwitcher 在 tenants 只有 1 个时不渲染
 * 5. TenantSwitcher 在 tenants 有多个时渲染切换器
 * 6. TopBar IIFE 中 user.tenants?.find() 在 tenants 为 undefined 时不崩溃
 * 7. TopBar 显示正确的用户名
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { screen } from '@testing-library/react';
import { TopBar } from '@/components/layout/top-bar';
import { useAuthStore } from '@/stores/auth-slice';
import { renderWithProviders, makeUserInfo } from '@/test/test-utils';

// Mock useTheme（避免 ThemeProvider 依赖）
vi.mock('@/providers/theme-context', () => ({
  useTheme: () => ({ theme: 'light', setTheme: vi.fn() }),
}));

// Mock wsClient
vi.mock('@/lib/ws', () => ({
  wsClient: { sendControl: vi.fn() },
}));

// Mock useToast
vi.mock('@/hooks/use-toast', () => ({
  useToast: () => ({ toast: vi.fn() }),
}));

// Mock DropdownMenu：在 jsdom 中始终渲染 children，不依赖 pointer events
// 这样可以直接测试 IIFE 和 TenantSwitcher 中的 .find() 代码路径
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

describe('TopBar', () => {
  beforeEach(() => {
    useAuthStore.setState({
      token: null,
      user: null,
      isAuthenticated: false,
      isLoading: false,
    });
    vi.clearAllMocks();
  });

  describe('user 为 null 时', () => {
    it('不崩溃，显示默认用户名 "用户"', () => {
      renderWithProviders(<TopBar />);

      // 头像区域应该显示 "用户" 的首字母
      expect(screen.getByTitle('用户')).toBeDefined();
    });
  });

  describe('user 存在但 tenants 为 undefined 时', () => {
    it('IIFE 中 user?.tenants?.find() 不崩溃，不渲染当前组织', () => {
      const userWithoutTenants = makeUserInfo();
      // 模拟 tenants 为 undefined 的情况
      (userWithoutTenants as Record<string, unknown>).tenants = undefined;

      useAuthStore.setState({ user: userWithoutTenants, token: 'test' });

      renderWithProviders(<TopBar />);

      // IIFE 因 tenants 为 undefined → ct 为 undefined → 返回 null
      // 不应出现 "默认组织" 文本（DropdownMenu 已 mock 为始终渲染 children）
      expect(screen.queryByText('默认组织')).toBeNull();
    });
  });

  describe('user 存在且 tenants 为空数组时', () => {
    it('TenantSwitcher 不渲染（tenants.length <= 1）', () => {
      const user = makeUserInfo({ tenants: [] });
      useAuthStore.setState({ user, token: 'test' });

      renderWithProviders(<TopBar />);

      // 不应该出现"切换租户"文本
      expect(screen.queryByText('切换租户')).toBeNull();
    });
  });

  describe('user 存在且 tenants 只有 1 个时', () => {
    it('TenantSwitcher 不渲染（tenants.length <= 1 → return null）', () => {
      const user = makeUserInfo({
        tenants: [{ id: 't1', name: '唯一组织', role: 'owner' }],
      });
      useAuthStore.setState({ user, token: 'test' });

      renderWithProviders(<TopBar />);

      // IIFE 渲染当前组织名称（tenants.find() 返回 t1 → "唯一组织"）
      // TenantSwitcher 不渲染（length <= 1 → return null）
      // 所以 "唯一组织" 只出现 1 次（来自 IIFE），而不是 2 次（IIFE + TenantSwitcher sub-trigger）
      const tenantTexts = screen.getAllByText('唯一组织');
      expect(tenantTexts).toHaveLength(1);
    });
  });

  describe('user 存在且有多个 tenants 时', () => {
    it('IIFE 渲染当前组织，TenantSwitcher 显示切换器', () => {
      const user = makeUserInfo({
        tenant_id: 't1',
        tenants: [
          { id: 't1', name: '当前组织', role: 'owner' },
          { id: 't2', name: '其他组织', role: 'member' },
        ],
      });
      useAuthStore.setState({ user, token: 'test' });

      renderWithProviders(<TopBar />);

      // IIFE 应渲染当前组织名称（user.tenants.find() 返回 t1 → "当前组织"）
      // DropdownMenu 已 mock 为始终渲染 children，无需打开
      const currentTenantTexts = screen.getAllByText('当前组织');
      expect(currentTenantTexts.length).toBeGreaterThanOrEqual(1);

      // TenantSwitcher 子菜单触发器也应显示当前组织名称
      // 子菜单内容（"其他组织"）在 SubContent 中也应可见
      expect(screen.getByText('其他组织')).toBeDefined();
    });
  });

  describe('用户名显示', () => {
    it('优先显示 display_name', () => {
      const user = makeUserInfo({ display_name: '张三', username: 'zhangsan' });
      useAuthStore.setState({ user, token: 'test' });

      renderWithProviders(<TopBar />);
      expect(screen.getByTitle('张三')).toBeDefined();
    });

    it('display_name 缺失时回退到 username', () => {
      const user = makeUserInfo({ display_name: '', username: 'zhangsan' });
      useAuthStore.setState({ user, token: 'test' });

      renderWithProviders(<TopBar />);
      expect(screen.getByTitle('zhangsan')).toBeDefined();
    });
  });
});
