import * as React from 'react';
import { cn } from '@/lib/utils';
import { XIcon, MaximizeIcon } from '@/components/ui/svg-icons';

/**
 * 悬浮画布（Floating Canvas）原语 —— M/L 两档。
 *
 * 设计规格（见 ui_design_system.yaml 与设计讨论）：
 * - 档位：M = 28rem 右贴边默认档；L = 45rem 居中偏右沉浸档。档位由内容类型决定，
 *   用户仅可升档（M → L），不可降档或自由缩放。
 * - 非模态：不设遮罩层，画布打开时对话流仍可操作（"边看边聊"）；
 *   单焦点由调用方状态层保证（同一时刻最多一个画布展开）。
 * - 关闭：ESC / 关闭按钮 / 打开其他画布时被替换。
 * - 动效：--duration-panel；开用软着陆（--ease-soft），关用标准缓动。
 * - 滚动：档内最多一条滚动条（内容区 overflow-y-auto）。
 * - 窄屏兜底：max-width = 100vw - 2rem。
 */
export type FloatingPanelSize = 'M' | 'L';

interface FloatingPanelProps {
  open: boolean;
  onClose: () => void;
  size: FloatingPanelSize;
  title: string;
  /** 仅 M 档传入：升档到 L 的回调（升档按钮只在 M 档显示） */
  onUpgrade?: () => void;
  /** 标题栏徽标（如数量角标） */
  badge?: React.ReactNode;
  children: React.ReactNode;
}

/* 与 --duration-panel 保持一致：退出动画延迟卸载的时长 */
const PANEL_ANIM_MS = 200;

export function FloatingPanel({ open, onClose, onUpgrade, size, title, badge, children }: FloatingPanelProps) {
  const [rendered, setRendered] = React.useState(open);
  const [closing, setClosing] = React.useState(false);
  const panelRef = React.useRef<HTMLDivElement>(null);

  // 退出动画：open 变 false 后延迟一个 --duration-panel 再卸载
  React.useEffect(() => {
    if (open) {
      setRendered(true);
      setClosing(false);
      return;
    }
    if (!rendered) return;
    setClosing(true);
    const timer = window.setTimeout(() => {
      setRendered(false);
      setClosing(false);
    }, PANEL_ANIM_MS);
    return () => window.clearTimeout(timer);
  }, [open, rendered]);

  // ESC 关闭
  React.useEffect(() => {
    if (!open) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [open, onClose]);

  // 打开时聚焦画布（键盘可访问性）
  React.useEffect(() => {
    if (open) panelRef.current?.focus();
  }, [open]);

  if (!rendered) return null;

  return (
    <div className="pointer-events-none fixed inset-0 z-(--z-panel)">
      <div
        ref={panelRef}
        role="dialog"
        aria-label={title}
        tabIndex={-1}
        className={cn(
          'pointer-events-auto absolute flex flex-col overflow-hidden rounded-lg border border-border-default bg-bg-elevated shadow-md outline-none',
          closing ? 'floating-panel-exit' : 'floating-panel-enter',
          size === 'M' && 'bottom-4 right-4 top-4 w-(--panel-width-m) max-w-[calc(100vw-2rem)]',
          // L 档居中偏右：面板中心位于视口中心右侧 2rem；窄屏时 left 不小于 1rem
          size === 'L' &&
            'bottom-4 top-4 left-[max(1rem,calc(50%-20.5rem))] w-(--panel-width-l) max-w-[calc(100vw-2rem)]',
        )}
      >
        <div className="flex flex-shrink-0 items-center gap-2 border-b border-border-soft px-4 py-2.5">
          <h2 className="min-w-0 flex-1 truncate text-sm font-semibold text-text-primary">{title}</h2>
          {badge}
          {size === 'M' && onUpgrade && (
            <button
              type="button"
              onClick={onUpgrade}
              title="展开为大画布"
              aria-label="展开为大画布"
              className="flex h-6 w-6 flex-shrink-0 items-center justify-center rounded text-text-tertiary transition-colors duration-(--duration-hover) hover:bg-bg-tertiary hover:text-text-secondary"
            >
              <MaximizeIcon size={13} />
            </button>
          )}
          <button
            type="button"
            onClick={onClose}
            title="关闭（Esc）"
            aria-label="关闭画布"
            className="flex h-6 w-6 flex-shrink-0 items-center justify-center rounded text-text-tertiary transition-colors duration-(--duration-hover) hover:bg-bg-tertiary hover:text-text-secondary"
          >
            <XIcon size={14} />
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto">{children}</div>
      </div>
    </div>
  );
}
