/**
 * Settings 页面测试
 *
 * 覆盖场景：
 * 1. user?.tenants?.find() 在 user 为 null 时不崩溃（line 131）
 * 2. user?.tenants?.find() 在 tenants 为 undefined 时不崩溃
 * 3. user?.tenants?.find() 在 tenants 为空数组时不崩溃
 * 4. user?.tenants?.find() 正常匹配时显示当前组织信息
 * 5. user?.tenants?.find() 未匹配到时隐藏组织信息
 */
import * as React from 'react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { screen } from '@testing-library/react';
import { useAuthStore } from '@/stores/auth-slice';
import { renderWithProviders, makeUserInfo } from '@/test/test-utils';
import SettingsPage from '@/features/settings/page';

// Mock theme provider
vi.mock('@/providers/theme-context', () => ({
  useTheme: () => ({ theme: 'light', setTheme: vi.fn(), resolvedTheme: 'light' }),
}));

// Mock toast
vi.mock('@/hooks/use-toast', () => ({
  useToast: () => ({ toast: vi.fn() }),
}));

// Mock api
vi.mock('@/lib/api', () => ({
  api: { get: vi.fn(), post: vi.fn(), put: vi.fn() },
  isDemoMode: () => false,
}));

// Mock crypto（sha256Hash 依赖 Web Crypto API，jsdom 不保证支持）
vi.mock('@/lib/crypto', () => ({
  sha256Hash: vi.fn().mockResolvedValue('mocked-hash'),
}));

describe('SettingsPage - user?.tenants?.find() 崩溃路径', () => {
  beforeEach(() => {
    useAuthStore.setState({
      token: null,
      user: null,
      isAuthenticated: false,
      isLoading: false,
    });
    vi.clearAllMocks();
  });

  it('user 为 null → .find() 不执行，页面不崩溃', () => {
    renderWithProviders(<SettingsPage />);

    // 页面标题应正常渲染
    expect(screen.getByText('设置')).toBeDefined();
    // 不应显示"当前组织"（currentTenant 为 undefined）
    expect(screen.queryByText('当前组织')).toBeNull();
  });

  it('user 存在但 tenants 为 undefined → .find() 通过可选链跳过，不崩溃', () => {
    const user = makeUserInfo();
    (user as Record<string, unknown>).tenants = undefined;
    useAuthStore.setState({ user, token: 'test' });

    renderWithProviders(<SettingsPage />);

    expect(screen.getByText('设置')).toBeDefined();
    expect(screen.queryByText('当前组织')).toBeNull();
  });

  it('user 存在且 tenants 为空数组 → .find() 返回 undefined，不显示组织信息', () => {
    const user = makeUserInfo({ tenants: [] });
    useAuthStore.setState({ user, token: 'test' });

    renderWithProviders(<SettingsPage />);

    expect(screen.getByText('设置')).toBeDefined();
    expect(screen.queryByText('当前组织')).toBeNull();
  });

  it('user 存在且 tenants 有匹配项 → .find() 正确返回，显示当前组织名称和角色', () => {
    const user = makeUserInfo({
      tenant_id: 't1',
      tenants: [
        { id: 't1', name: '测试组织A', role: 'owner' },
        { id: 't2', name: '测试组织B', role: 'member' },
      ],
    });
    useAuthStore.setState({ user, token: 'test' });

    renderWithProviders(<SettingsPage />);

    // 应显示当前组织名称
    expect(screen.getByText('测试组织A')).toBeDefined();
    // 应显示"当前组织"标签
    expect(screen.getByText('当前组织')).toBeDefined();
    // owner 角色应显示为"所有者"
    expect(screen.getByText('(所有者)')).toBeDefined();
    // 有 2 个组织时应显示提示
    expect(screen.getByText(/你属于 2 个组织/)).toBeDefined();
  });

  it('user 存在但 tenant_id 不匹配任何 tenant → .find() 返回 undefined，不显示组织信息', () => {
    const user = makeUserInfo({
      tenant_id: 'non-existent',
      tenants: [
        { id: 't1', name: '测试组织A', role: 'owner' },
      ],
    });
    useAuthStore.setState({ user, token: 'test' });

    renderWithProviders(<SettingsPage />);

    expect(screen.getByText('设置')).toBeDefined();
    expect(screen.queryByText('当前组织')).toBeNull();
    expect(screen.queryByText('测试组织A')).toBeNull();
  });

  it('user 存在且 tenant role 为 member → 显示"成员"角色', () => {
    const user = makeUserInfo({
      tenant_id: 't2',
      tenants: [
        { id: 't1', name: '主组织', role: 'owner' },
        { id: 't2', name: '副组织', role: 'member' },
      ],
    });
    useAuthStore.setState({ user, token: 'test' });

    renderWithProviders(<SettingsPage />);

    expect(screen.getByText('副组织')).toBeDefined();
    expect(screen.getByText('(成员)')).toBeDefined();
  });
});
