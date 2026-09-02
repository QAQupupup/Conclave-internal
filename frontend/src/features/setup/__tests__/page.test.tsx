/**
 * SetupPage 表单范式测试（react-hook-form + 字段级错误）
 *
 * 覆盖场景：
 * 1. 两次密码不一致 → 确认密码字段级错误（非正向）
 * 2. 密码长度不足 6 位 → 密码字段级错误（非正向）
 * 3. 合法输入 → 以预哈希密码调用 /setup
 */
import * as React from 'react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { screen, fireEvent, waitFor } from '@testing-library/react';
import { renderWithProviders } from '@/test/test-utils';
import SetupPage from '@/features/setup/page';
import { api } from '@/lib/api';

vi.mock('@/lib/api', () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
  },
}));

vi.mock('@/lib/crypto', () => ({
  sha256Hash: vi.fn().mockResolvedValue('mocked-hash'),
}));

const apiGet = api.get as ReturnType<typeof vi.fn>;
const apiPost = api.post as ReturnType<typeof vi.fn>;

describe('SetupPage 表单校验', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiGet.mockResolvedValue({ needs_setup: true, has_admin: false });
    apiPost.mockResolvedValue({});
  });

  it('两次密码不一致 → 确认密码字段展示错误，不发起请求', async () => {
    renderWithProviders(<SetupPage />);

    fireEvent.change(await screen.findByLabelText('管理员用户名'), { target: { value: 'admin' } });
    fireEvent.change(screen.getByLabelText('密码'), { target: { value: '123456' } });
    fireEvent.change(screen.getByLabelText('确认密码'), { target: { value: '654321' } });
    fireEvent.click(screen.getByRole('button', { name: '创建管理员账号' }));

    expect(await screen.findByText('两次输入的密码不一致')).toBeDefined();
    expect(apiPost).not.toHaveBeenCalled();
  });

  it('密码长度不足 6 位 → 密码字段展示错误，不发起请求', async () => {
    renderWithProviders(<SetupPage />);

    fireEvent.change(await screen.findByLabelText('管理员用户名'), { target: { value: 'admin' } });
    fireEvent.change(screen.getByLabelText('密码'), { target: { value: '123' } });
    fireEvent.change(screen.getByLabelText('确认密码'), { target: { value: '123' } });
    fireEvent.click(screen.getByRole('button', { name: '创建管理员账号' }));

    expect(await screen.findByText('密码长度至少 6 位')).toBeDefined();
    expect(apiPost).not.toHaveBeenCalled();
  });

  it('合法输入 → 以预哈希密码调用 /setup', async () => {
    renderWithProviders(<SetupPage />);

    fireEvent.change(await screen.findByLabelText('管理员用户名'), { target: { value: 'admin' } });
    fireEvent.change(screen.getByLabelText('密码'), { target: { value: '123456' } });
    fireEvent.change(screen.getByLabelText('确认密码'), { target: { value: '123456' } });
    fireEvent.click(screen.getByRole('button', { name: '创建管理员账号' }));

    await waitFor(() => expect(apiPost).toHaveBeenCalledTimes(1));
    expect(apiPost).toHaveBeenCalledWith('/setup', expect.objectContaining({
      username: 'admin',
      password: 'mocked-hash',
    }));
  });
});
