import * as React from 'react';
import { cn } from '@/lib/utils';

interface ResizableHandleProps {
  onResize: (newSize: number) => void;
  direction?: 'horizontal' | 'vertical';
  className?: string;
  minSize?: number;
  maxSize?: number;
  currentSize?: number;
  /** 反向调整：拖拽正方向时面板缩小（用于右侧/底部面板的左/上边缘拖拽条） */
  reverse?: boolean;
}

export function ResizableHandle({
  onResize,
  direction = 'horizontal',
  className,
  minSize = 180,
  maxSize = 600,
  currentSize,
  reverse = false,
}: ResizableHandleProps) {
  const isHorizontal = direction === 'horizontal';
  const startPosRef = React.useRef(0);
  const startSizeRef = React.useRef(0);

  const onMouseDown = (e: React.MouseEvent) => {
    e.preventDefault();
    startPosRef.current = isHorizontal ? e.clientX : e.clientY;
    startSizeRef.current = currentSize ?? (isHorizontal ? 260 : 200);

    const onMouseMove = (ev: MouseEvent) => {
      const current = isHorizontal ? ev.clientX : ev.clientY;
      const delta = current - startPosRef.current;
      const adjustedDelta = reverse ? -delta : delta;
      const newSize = Math.max(minSize, Math.min(maxSize, startSizeRef.current + adjustedDelta));
      onResize(newSize);
    };
    const onMouseUp = () => {
      document.removeEventListener('mousemove', onMouseMove);
      document.removeEventListener('mouseup', onMouseUp);
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    };
    document.addEventListener('mousemove', onMouseMove);
    document.addEventListener('mouseup', onMouseUp);
    document.body.style.cursor = isHorizontal ? 'col-resize' : 'row-resize';
    document.body.style.userSelect = 'none';
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    const step = 16;
    let delta = 0;
    if (isHorizontal) {
      if (e.key === 'ArrowRight') delta = step;
      else if (e.key === 'ArrowLeft') delta = -step;
    } else {
      if (e.key === 'ArrowDown') delta = step;
      else if (e.key === 'ArrowUp') delta = -step;
    }
    if (delta === 0) return;
    e.preventDefault();
    const base = currentSize ?? (isHorizontal ? 260 : 200);
    const adjustedDelta = reverse ? -delta : delta;
    const newSize = Math.max(minSize, Math.min(maxSize, base + adjustedDelta));
    onResize(newSize);
  };

  return (
    // 窗口分割条（window splitter）采用 W3C ARIA 规范的可聚焦 separator 模式：
    // role="separator" + tabIndex + aria-orientation/valuenow + 鼠标/方向键处理器。
    // jsx-a11y 未将 separator 归为 widget，故针对该交互处理器做局部放行。
    // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions
    <div
      onMouseDown={onMouseDown}
      onKeyDown={onKeyDown}
      role="separator"
      aria-orientation={isHorizontal ? 'vertical' : 'horizontal'}
      aria-valuemin={minSize}
      aria-valuemax={maxSize}
      aria-valuenow={currentSize ?? (isHorizontal ? 260 : 200)}
      tabIndex={0}
      className={cn(
        'group relative flex-shrink-0 z-10',
        isHorizontal ? 'w-1 cursor-col-resize' : 'h-1 cursor-row-resize',
        'hover:bg-brand-500/20 active:bg-brand-500/30 transition-colors',
        'before:absolute before:inset-y-0 before:-left-1 before:w-3',
        className
      )}
    >
      <div
        className={cn(
          'absolute top-1/2 -translate-y-1/2 rounded-full bg-border-default opacity-0 transition-opacity group-hover:opacity-100',
          isHorizontal ? 'left-1/2 -translate-x-1/2 h-8 w-0.5' : 'top-1/2 -translate-y-1/2 h-0.5 w-8'
        )}
      />
    </div>
  );
}
