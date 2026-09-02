/**
 * LoginPage 表单范式测试（react-hook-form + 字段级错误 + 表单级横幅）
 *
 * 覆盖场景：
 * 1. 空表单提交 → 字段级错误（非正向），且不发起登录请求
 * 2. 服务端拒绝（401）→ 表单级横幅展示，不归属单一字段（非正向）
 * 3. 正常提交 → 发送 SHA-256 预哈希密码，明文不出端
 */
import * as React from 'react';
import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import { screen, fireEvent, waitFor } from '@testing-library/react';
import { renderWithProviders, makeUserInfo } from '@/test/test-utils';
import LoginPage from '@/features/login/page';

vi.mock('@/lib/api', () => ({
  api: { get: vi.fn() },
}));

// sha256Hash 依赖 Web Crypto API，jsdom 不保证支持
vi.mock('@/lib/crypto', () => ({
  sha256Hash: vi.fn().mockResolvedValue('mocked-hash'),
}));

vi.mock('@/hooks/use-toast', () => ({
  useToast: () => ({ toast: vi.fn() }),
}));

const fetchMock = vi.fn();

describe('LoginPage 表单校验', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('清空字段后提交 → 展示字段级错误，且不发起登录请求', async () => {
    renderWithProviders(<LoginPage />);

    // DEV 模式默认预填 admin/admin123，先清空构造空表单
    fireEvent.change(screen.getByLabelText('用户名'), { target: { value: '' } });
    fireEvent.change(screen.getByLabelText('密码'), { target: { value: '' } });
    fireEvent.click(screen.getByRole('button', { name: '登录' }));

    expect(await screen.findByText('请输入用户名')).toBeDefined();
    expect(await screen.findByText('请输入密码')).toBeDefined();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('服务端拒绝（401）→ 表单级横幅展示错误，而非字段级', async () => {
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 401,
      json: async () => ({ detail: '用户名或密码错误' }),
    });
    renderWithProviders(<LoginPage />);

    fireEvent.click(screen.getByRole('button', { name: '登录' }));

    const banner = await screen.findByRole('alert');
    expect(banner.textContent).toBe('用户名或密码错误');
    // 字段级错误不应出现
    expect(screen.queryByText('请输入用户名')).toBeNull();
    expect(screen.queryByText('请输入密码')).toBeNull();
  });

  it('正常提交 → 请求体携带 SHA-256 预哈希，不发送明文密码', async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ access_token: 'tk-1', user: makeUserInfo() }),
    });
    renderWithProviders(<LoginPage />);

    fireEvent.click(screen.getByRole('button', { name: '登录' }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    const body = JSON.parse(init.body as string);
    expect(body.password).toBe('mocked-hash');
    expect(body.password).not.toBe('admin123');
    expect(body.username).toBe('admin');
  });
});
