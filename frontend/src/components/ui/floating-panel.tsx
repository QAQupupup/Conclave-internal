import * as React from 'react';
import { cn } from '@/lib/utils';
import { XIcon, MaximizeIcon } from '@/components/ui/svg-icons';
import { SIZE_ORDER, readTierWidths, snapWidthToSize } from '@/components/ui/floating-panel-sizing';
import type { FloatingPanelSize } from '@/components/ui/floating-panel-sizing';

/**
 * 悬浮画布（Floating Canvas）原语 —— M/L/XL 三档。
 *
 * 设计规格（见 ui_design_system.yaml 与设计讨论）：
 * - 档位：M = 28rem 右贴边默认档；L = 45rem 居中偏右沉浸档；
 *   XL = 62rem 近全屏"小页面"档（长文阅读、报告审阅）。
 * - 档位可双向切换（标题栏档位切换器），也可拖拽左缘自由调宽，
 *   松手后吸附到最近档位（档位即记忆，避免无约束的自由尺寸漂移）。
 * - 非模态：不设遮罩层，画布打开时对话流仍可操作（"边看边聊"）；
 *   单焦点由调用方状态层保证（同一时刻最多一个画布展开）。
 * - 关闭：ESC / 关闭按钮 / 打开其他画布时被替换。
 * - 动效：--duration-panel；开用软着陆（--ease-soft），关用标准缓动。
 * - 滚动：档内最多一条滚动条（内容区 overflow-y-auto）。
 * - 窄屏兜底：max-width = 100vw - 2rem。
 *
 * 档位纯逻辑（类型/常量/吸附函数）见 floating-panel-sizing.ts，
 * 本文件只导出组件（react-refresh/only-export-components 约束）。
 */
/** 拖拽最小宽度（px）：低于该值也吸附到 M 档 */
const MIN_DRAG_WIDTH = 320;
/** 拖拽时画布与视口左右各保留的最小间距（px） */
const DRAG_VIEWPORT_GAP = 32;

interface FloatingPanelProps {
  open: boolean;
  onClose: () => void;
  size: FloatingPanelSize;
  title: string;
  /** 传入才启用档位切换器与左缘拖拽调宽（松手吸附到最近档位） */
  onSizeChange?: (size: FloatingPanelSize) => void;
  /** 传入才启用"弹出"按钮：路由画布地址，新标签页打开（问题 4 路由画布入口） */
  popoutHref?: string;
  /** 标题栏徽标（如数量角标） */
  badge?: React.ReactNode;
  children: React.ReactNode;
}

/* 与 --duration-panel 保持一致：退出动画延迟卸载的时长 */
const PANEL_ANIM_MS = 200;

export function FloatingPanel({ open, onClose, onSizeChange, popoutHref, size, title, badge, children }: FloatingPanelProps) {
  const [rendered, setRendered] = React.useState(open);
  const [closing, setClosing] = React.useState(false);
  /** 拖拽中的临时尺寸（松手后清空并吸附档位） */
  const [drag, setDrag] = React.useState<{ width: number; rightOffset: number } | null>(null);
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

  // 左缘拖拽调宽：右缘锚定不动，松手吸附最近档位
  const startEdgeDrag = (e: React.MouseEvent) => {
    if (e.button !== 0 || !onSizeChange || !panelRef.current) return;
    e.preventDefault();
    const rect = panelRef.current.getBoundingClientRect();
    const maxW = Math.max(MIN_DRAG_WIDTH, window.innerWidth - DRAG_VIEWPORT_GAP);
    const rightOffset = window.innerWidth - rect.right;
    const clampW = (w: number) => Math.max(MIN_DRAG_WIDTH, Math.min(maxW, w));

    const onMove = (ev: MouseEvent) => {
      setDrag({ width: clampW(rect.right - ev.clientX), rightOffset });
    };
    const onUp = (ev: MouseEvent) => {
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      const finalWidth = clampW(rect.right - ev.clientX);
      setDrag(null);
      onSizeChange(snapWidthToSize(finalWidth, readTierWidths()));
    };
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
  };

  if (!rendered) return null;

  return (
    <div className="pointer-events-none fixed inset-0 z-(--z-panel)">
      <div
        ref={panelRef}
        role="dialog"
        aria-label={title}
        tabIndex={-1}
        style={
          drag
            ? { width: drag.width, right: drag.rightOffset, left: 'auto' }
            : undefined
        }
        className={cn(
          'pointer-events-auto absolute flex flex-col overflow-hidden rounded-lg border border-border-default bg-bg-elevated shadow-md outline-none',
          closing ? 'floating-panel-exit' : 'floating-panel-enter',
          size === 'M' && 'bottom-4 right-4 top-4 w-(--panel-width-m) max-w-[calc(100vw-2rem)]',
          // L 档居中偏右：面板中心位于视口中心右侧 2rem；窄屏时 left 不小于 1rem
          size === 'L' &&
            'bottom-4 top-4 left-[max(1rem,calc(50%-20.5rem))] w-(--panel-width-l) max-w-[calc(100vw-2rem)]',
          // XL 档近全屏"小页面"：居中，宽度 62rem（半宽 31rem）
          size === 'XL' &&
            'bottom-4 top-4 left-[max(1rem,calc(50%-31rem))] w-(--panel-width-xl) max-w-[calc(100vw-2rem)]',
        )}
      >
        {/* 左缘拖拽条：仅启用档位控制时出现 */}
        {onSizeChange && (
          <div
            onMouseDown={startEdgeDrag}
            aria-hidden="true"
            className="absolute inset-y-0 left-0 z-10 w-1.5 cursor-col-resize transition-colors duration-(--duration-hover) hover:bg-brand-500/20 active:bg-brand-500/30"
          />
        )}
        <div className="flex flex-shrink-0 items-center gap-2 border-b border-border-soft px-4 py-2.5">
          <h2 className="min-w-0 flex-1 truncate text-sm font-semibold text-text-primary">{title}</h2>
          {badge}
          {onSizeChange && (
            <div
              role="group"
              aria-label="画布档位"
              className="flex flex-shrink-0 items-center rounded-md border border-border-soft p-0.5"
            >
              {SIZE_ORDER.map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => s !== size && onSizeChange(s)}
                  aria-pressed={s === size}
                  aria-label={`切换到 ${s} 档`}
                  title={`切换到 ${s} 档`}
                  className={cn(
                    'rounded px-1.5 py-0.5 text-[10px] font-medium transition-colors duration-(--duration-hover)',
                    s === size
                      ? 'bg-brand-soft text-brand-600'
                      : 'text-text-tertiary hover:bg-bg-tertiary hover:text-text-secondary',
                  )}
                >
                  {s}
                </button>
              ))}
            </div>
          )}
          {popoutHref && (
            <a
              href={popoutHref}
              target="_blank"
              rel="noopener noreferrer"
              title="在新标签页打开"
              aria-label="在新标签页打开画布"
              className="flex h-6 w-6 flex-shrink-0 items-center justify-center rounded text-text-tertiary transition-colors duration-(--duration-hover) hover:bg-bg-tertiary hover:text-text-secondary"
            >
              <MaximizeIcon size={13} />
            </a>
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
