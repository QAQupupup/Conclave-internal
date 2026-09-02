/**
 * SidePanel 可折叠侧栏原语测试
 *
 * 覆盖场景：
 * 1. 展开时渲染 children；折叠时不渲染（手柄仍在场）
 * 2. 手柄同位：展开/折叠两态下均存在同一切换柄，aria-expanded 正确
 * 3. 点击手柄（无位移）触发 onToggle
 * 4. 拖拽手柄触发 onWidthChange 且不触发 onToggle（点击/拖拽分流）
 * 5. 右栏拖拽方向取反（鼠标左移变宽）
 * 6. 拖拽宽度受 minSize/maxSize 钳制（边界）
 * 7. 键盘：Enter 切换折叠；方向键调宽（左栏 → 变宽）
 * 8. 折叠态拖拽不产生调宽（异常路径防御）
 */
import { describe, it, expect, vi } from 'vitest';
import { screen, fireEvent } from '@testing-library/react';
import { SidePanel } from '@/components/ui/side-panel';
import { renderWithProviders } from '@/test/test-utils';

const renderPanel = (props: Partial<React.ComponentProps<typeof SidePanel>> = {}) =>
  renderWithProviders(
    <SidePanel
      side="left"
      collapsed={false}
      onToggle={vi.fn()}
      label="阶段时间线"
      width={260}
      onWidthChange={vi.fn()}
      minSize={200}
      maxSize={380}
      {...props}
    >
      <div>面板内容</div>
    </SidePanel>,
  );

describe('SidePanel', () => {
  it('展开时渲染 children，折叠时不渲染但手柄仍在场', () => {
    const { rerender, getByRole } = renderPanel();
    expect(screen.getByText('面板内容')).toBeDefined();

    rerender(
      <SidePanel
        side="left"
        collapsed
        onToggle={vi.fn()}
        label="阶段时间线"
        width={260}
        onWidthChange={vi.fn()}
      >
        <div>面板内容</div>
      </SidePanel>,
    );
    expect(screen.queryByText('面板内容')).toBeNull();
    // 手柄同位：折叠后切换柄仍存在（开与关是同一个地方）
    expect(getByRole('button')).toBeDefined();
  });

  it('aria-expanded 反映折叠状态', () => {
    renderPanel({ collapsed: false });
    expect(screen.getByRole('button').getAttribute('aria-expanded')).toBe('true');
  });

  it('点击手柄（无位移）触发 onToggle', () => {
    const onToggle = vi.fn();
    renderPanel({ onToggle });
    const handle = screen.getByRole('button');
    fireEvent.mouseDown(handle, { button: 0, clientX: 100 });
    fireEvent.mouseUp(document);
    expect(onToggle).toHaveBeenCalledTimes(1);
  });

  it('拖拽手柄触发 onWidthChange，不触发 onToggle', () => {
    const onToggle = vi.fn();
    const onWidthChange = vi.fn();
    renderPanel({ onToggle, onWidthChange, width: 260 });
    const handle = screen.getByRole('button');
    fireEvent.mouseDown(handle, { button: 0, clientX: 100 });
    fireEvent.mouseMove(document, { clientX: 150 });
    fireEvent.mouseUp(document);
    expect(onWidthChange).toHaveBeenCalledWith(310);
    expect(onToggle).not.toHaveBeenCalled();
  });

  it('右栏拖拽方向取反：鼠标左移变宽', () => {
    const onWidthChange = vi.fn();
    renderPanel({ side: 'right', onWidthChange, width: 340 });
    const handle = screen.getByRole('button');
    fireEvent.mouseDown(handle, { button: 0, clientX: 200 });
    fireEvent.mouseMove(document, { clientX: 160 });
    fireEvent.mouseUp(document);
    expect(onWidthChange).toHaveBeenCalledWith(380);
  });

  it('拖拽宽度受 minSize/maxSize 钳制', () => {
    const onWidthChange = vi.fn();
    renderPanel({ onWidthChange, width: 260, minSize: 200, maxSize: 380 });
    const handle = screen.getByRole('button');
    // 向右拖 500px：远超上限
    fireEvent.mouseDown(handle, { button: 0, clientX: 100 });
    fireEvent.mouseMove(document, { clientX: 600 });
    fireEvent.mouseUp(document);
    expect(onWidthChange).toHaveBeenLastCalledWith(380);
  });

  it('键盘 Enter 切换折叠，ArrowRight 调宽（左栏变宽）', () => {
    const onToggle = vi.fn();
    const onWidthChange = vi.fn();
    renderPanel({ onToggle, onWidthChange, width: 260 });
    const handle = screen.getByRole('button');
    fireEvent.keyDown(handle, { key: 'Enter' });
    expect(onToggle).toHaveBeenCalledTimes(1);
    fireEvent.keyDown(handle, { key: 'ArrowRight' });
    expect(onWidthChange).toHaveBeenCalledWith(276);
  });

  it('折叠态拖拽不产生调宽（防御：无宽度语义时仅切换）', () => {
    const onToggle = vi.fn();
    const onWidthChange = vi.fn();
    renderPanel({ collapsed: true, onToggle, onWidthChange });
    const handle = screen.getByRole('button');
    fireEvent.mouseDown(handle, { button: 0, clientX: 100 });
    fireEvent.mouseMove(document, { clientX: 200 });
    fireEvent.mouseUp(document);
    expect(onWidthChange).not.toHaveBeenCalled();
    expect(onToggle).toHaveBeenCalledTimes(1);
  });
});
