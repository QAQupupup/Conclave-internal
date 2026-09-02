/**
 * FloatingPanel 悬浮画布基元测试
 *
 * 覆盖场景：
 * 1. 关闭时不渲染（无 dialog 角色节点）
 * 2. 打开时渲染标题与内容，带 role=dialog + aria-label
 * 3. 点击关闭按钮触发 onClose
 * 4. ESC 键触发 onClose
 * 5. M 档显示升档按钮并触发 onUpgrade；L 档隐藏升档按钮
 * 6. 关闭后延迟一个动效时长再卸载（退场动画窗口）
 * 7. 退场动画中途重新打开会取消卸载（边界：快速开合不丢面板）
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { screen, fireEvent, act } from '@testing-library/react';
import { FloatingPanel } from '@/components/ui/floating-panel';
import { renderWithProviders } from '@/test/test-utils';

/* 与组件内 PANEL_ANIM_MS（= --duration-panel）保持一致 */
const PANEL_ANIM_MS = 200;

describe('FloatingPanel', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('关闭时不渲染任何画布节点', () => {
    renderWithProviders(
      <FloatingPanel open={false} onClose={vi.fn()} size="M" title="冲突与证据">
        <div>内容</div>
      </FloatingPanel>,
    );
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('打开时渲染标题与内容（role=dialog + aria-label）', () => {
    renderWithProviders(
      <FloatingPanel open onClose={vi.fn()} size="M" title="冲突与证据">
        <div>画布内容</div>
      </FloatingPanel>,
    );
    const dialog = screen.getByRole('dialog');
    expect(dialog.getAttribute('aria-label')).toBe('冲突与证据');
    expect(screen.getByText('画布内容')).toBeDefined();
  });

  it('点击关闭按钮触发 onClose', () => {
    const onClose = vi.fn();
    renderWithProviders(
      <FloatingPanel open onClose={onClose} size="M" title="测试">
        <div>x</div>
      </FloatingPanel>,
    );
    fireEvent.click(screen.getByLabelText('关闭画布'));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('按 ESC 触发 onClose', () => {
    const onClose = vi.fn();
    renderWithProviders(
      <FloatingPanel open onClose={onClose} size="M" title="测试">
        <div>x</div>
      </FloatingPanel>,
    );
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('关闭状态下面板不在场时，ESC 不触发 onClose（监听器已卸载）', () => {
    const onClose = vi.fn();
    renderWithProviders(
      <FloatingPanel open={false} onClose={onClose} size="M" title="测试">
        <div>x</div>
      </FloatingPanel>,
    );
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(onClose).not.toHaveBeenCalled();
  });

  it('M 档显示升档按钮，点击触发 onUpgrade', () => {
    const onUpgrade = vi.fn();
    renderWithProviders(
      <FloatingPanel open onClose={vi.fn()} size="M" title="测试" onUpgrade={onUpgrade}>
        <div>x</div>
      </FloatingPanel>,
    );
    fireEvent.click(screen.getByLabelText('展开为大画布'));
    expect(onUpgrade).toHaveBeenCalledTimes(1);
  });

  it('L 档不显示升档按钮（只可升档不可降档）', () => {
    renderWithProviders(
      <FloatingPanel open onClose={vi.fn()} size="L" title="测试" onUpgrade={vi.fn()}>
        <div>x</div>
      </FloatingPanel>,
    );
    expect(screen.queryByLabelText('展开为大画布')).toBeNull();
  });

  it('关闭后延迟一个动效时长再卸载（退场动画窗口内仍在场）', () => {
    const { rerender } = renderWithProviders(
      <FloatingPanel open onClose={vi.fn()} size="M" title="测试">
        <div>内容</div>
      </FloatingPanel>,
    );
    rerender(
      <FloatingPanel open={false} onClose={vi.fn()} size="M" title="测试">
        <div>内容</div>
      </FloatingPanel>,
    );
    // 退场动画期间仍在 DOM 中
    expect(screen.getByRole('dialog')).toBeDefined();
    act(() => {
      vi.advanceTimersByTime(PANEL_ANIM_MS + 50);
    });
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('退场动画中途重新打开会取消卸载（快速开合边界）', () => {
    const { rerender } = renderWithProviders(
      <FloatingPanel open onClose={vi.fn()} size="M" title="测试">
        <div>内容</div>
      </FloatingPanel>,
    );
    rerender(
      <FloatingPanel open={false} onClose={vi.fn()} size="M" title="测试">
        <div>内容</div>
      </FloatingPanel>,
    );
    // 退场动画进行中
    act(() => {
      vi.advanceTimersByTime(PANEL_ANIM_MS / 2);
    });
    // 重新打开：卸载定时器应被取消
    rerender(
      <FloatingPanel open onClose={vi.fn()} size="M" title="测试">
        <div>内容</div>
      </FloatingPanel>,
    );
    act(() => {
      vi.advanceTimersByTime(PANEL_ANIM_MS * 2);
    });
    expect(screen.getByRole('dialog')).toBeDefined();
  });
});
