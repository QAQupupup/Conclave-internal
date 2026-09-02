/**
 * form-feedback 组件测试（FieldError / FormAlert）
 *
 * 覆盖场景：
 * 1. FieldError 渲染错误文本并带 role="alert"（无障碍播报）
 * 2. FieldError 无内容/空字符串时不渲染（非正向）
 * 3. FieldError 透传 id 供 aria-describedby 关联
 * 4. FormAlert 渲染表单级错误横幅
 * 5. FormAlert 空内容不渲染（非正向）
 */
import * as React from 'react';
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { FieldError, FormAlert } from '@/components/ui/form-feedback';

describe('FieldError', () => {
  it('渲染错误文本，带 role="alert" 与 id', () => {
    render(<FieldError id="name-error">请输入名称</FieldError>);
    const el = screen.getByRole('alert');
    expect(el.textContent).toBe('请输入名称');
    expect(el.id).toBe('name-error');
  });

  it('children 为 undefined 时不渲染任何内容', () => {
    const { container } = render(<FieldError id="e1">{undefined}</FieldError>);
    expect(container.innerHTML).toBe('');
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('children 为空字符串时不渲染（错误清除后占位移除）', () => {
    const { container } = render(<FieldError id="e2">{''}</FieldError>);
    expect(container.innerHTML).toBe('');
  });
});

describe('FormAlert', () => {
  it('渲染表单级错误横幅，带 role="alert"', () => {
    render(<FormAlert>用户名或密码错误</FormAlert>);
    const el = screen.getByRole('alert');
    expect(el.textContent).toBe('用户名或密码错误');
  });

  it('children 为空时不渲染（无服务端错误时不占位）', () => {
    const { container } = render(<FormAlert>{''}</FormAlert>);
    expect(container.innerHTML).toBe('');
  });
});
