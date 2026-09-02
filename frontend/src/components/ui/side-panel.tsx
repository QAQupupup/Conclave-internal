import * as React from 'react';
import { cn } from '@/lib/utils';
import { ChevronIcon } from '@/components/ui/svg-icons';

/**
 * 可折叠侧栏原语（SidePanel）—— 会议视图左右两栏的统一骨架。
 *
 * 设计要点（回应"开关按钮不同位、反人性"的反馈）：
 * - 同位切换柄：展开与折叠共用同一个竖条手柄，位于面板内缘
 *   （左栏在右缘、右栏在左缘）。折叠后手柄停在原面板边缘位置，
 *   点击同一位置即可还原——开与关永远是同一个地方。
 * - 手柄即拖拽条：展开态下横向拖动同一手柄可调整宽度
 *   （位移 < 4px 视为点击 → 折叠；超过阈值进入拖拽 → 调宽），
 *   不再需要独立的 ResizableHandle。
 * - 键盘可达：Enter/Space 切换折叠；方向键调整宽度（步进 16px）。
 * - 样式遵循设计红线：无重阴影、无 width 动画（折叠为瞬时切换）、
 *   悬停仅颜色过渡（--duration-hover）。
 */

/** 点击/拖拽判定位移阈值（px）：小于该值视为点击切换 */
const CLICK_DRAG_THRESHOLD = 4;
/** 方向键调宽步进（px），与 ResizableHandle 保持一致 */
const KEYBOARD_STEP = 16;

interface SidePanelProps {
  side: 'left' | 'right';
  collapsed: boolean;
  onToggle: () => void;
  /** 面板显示名，用于手柄 aria-label 与 title */
  label: string;
  /** 展开宽度（collapsed 时忽略） */
  width: number;
  /** 传入才启用拖拽/方向键调宽 */
  onWidthChange?: (width: number) => void;
  minSize?: number;
  maxSize?: number;
  children: React.ReactNode;
  className?: string;
}

export function SidePanel({
  side,
  collapsed,
  onToggle,
  label,
  width,
  onWidthChange,
  minSize = 180,
  maxSize = 600,
  children,
  className,
}: SidePanelProps) {
  const dragRef = React.useRef({ startX: 0, startW: 0, moved: false });
  const canResize = !collapsed && !!onWidthChange;

  const clamp = (w: number) => Math.max(minSize, Math.min(maxSize, w));

  const handleMouseDown = (e: React.MouseEvent) => {
    if (e.button !== 0) return;
    e.preventDefault();
    dragRef.current = { startX: e.clientX, startW: width, moved: false };

    const onMove = (ev: MouseEvent) => {
      const dx = ev.clientX - dragRef.current.startX;
      if (!dragRef.current.moved && Math.abs(dx) < CLICK_DRAG_THRESHOLD) return;
      dragRef.current.moved = true;
      document.body.style.cursor = 'col-resize';
      document.body.style.userSelect = 'none';
      if (!canResize) return;
      // 左栏：鼠标右移变宽；右栏：鼠标左移变宽
      const delta = side === 'left' ? dx : -dx;
      onWidthChange!(clamp(dragRef.current.startW + delta));
    };
    const onUp = () => {
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      // 未产生有效位移 → 视为点击：切换折叠；
      // 折叠态无调宽语义，拖动同样回退为点击切换（手柄上的按压几乎必然是交互意图）
      if (!dragRef.current.moved || !canResize) onToggle();
    };
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      onToggle();
      return;
    }
    if (!canResize) return;
    let delta = 0;
    if (e.key === 'ArrowRight') delta = KEYBOARD_STEP;
    else if (e.key === 'ArrowLeft') delta = -KEYBOARD_STEP;
    if (delta === 0) return;
    e.preventDefault();
    // 左栏：→ 变宽；右栏：→ 变窄（方向键语义与视觉一致）
    const adjusted = side === 'left' ? delta : -delta;
    onWidthChange!(clamp(width + adjusted));
  };

  // 箭头指向动作方向：展开态点击将折叠（指向面板外侧），折叠态点击将展开（指向面板内侧）
  const chevronDirection =
    side === 'left' ? (collapsed ? 'right' : 'left') : collapsed ? 'left' : 'right';
  const handleTitle = collapsed
    ? `展开${label}`
    : canResize
      ? `折叠${label}（拖动调整宽度）`
      : `折叠${label}`;

  const handle = (
    <div
      role="button"
      tabIndex={0}
      aria-expanded={!collapsed}
      aria-label={handleTitle}
      title={handleTitle}
      onMouseDown={handleMouseDown}
      onKeyDown={handleKeyDown}
      className={cn(
        'group relative flex w-4 flex-shrink-0 items-center justify-center border-border-soft bg-bg-primary transition-colors duration-(--duration-hover) hover:bg-bg-secondary focus-visible:bg-bg-secondary focus-visible:outline-none',
        side === 'left' ? 'border-r' : 'border-l',
        canResize ? 'cursor-col-resize' : 'cursor-pointer',
      )}
    >
      {/* 中央胶囊：视觉抓取点，悬停时品牌色描边提示可交互 */}
      <span
        aria-hidden="true"
        className="flex h-10 w-3.5 items-center justify-center rounded-full border border-border-soft bg-bg-primary text-text-tertiary transition-colors duration-(--duration-hover) group-hover:border-brand-500/40 group-hover:text-brand-600"
      >
        <ChevronIcon direction={chevronDirection} size={11} />
      </span>
    </div>
  );

  const body = !collapsed && (
    <div className="flex min-h-0 flex-col bg-bg-primary" style={{ width }}>
      <div className="min-h-0 flex-1">{children}</div>
    </div>
  );

  return (
    <div className={cn('flex h-full flex-shrink-0', className)}>
      {side === 'left' ? (
        <>
          {body}
          {handle}
        </>
      ) : (
        <>
          {handle}
          {body}
        </>
      )}
    </div>
  );
}
