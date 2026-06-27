// FocusMode：全屏聚焦模式
// 任何子组件被包在里面，点击"展开"按钮后进入全屏覆盖层
// 视觉：半透明黑色 backdrop + 居中卡片 + scale-up 动画
// 交互：Esc 关闭 / 点击 backdrop 关闭 / X 按钮关闭
import { useEffect } from 'react'
import type { ReactNode } from 'react'

export function FocusMode({
  open,
  onClose,
  title,
  hint,
  children,
}: {
  open: boolean
  onClose: () => void
  title?: ReactNode
  hint?: ReactNode
  children: ReactNode
}) {
  // Esc 键关闭
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    // 锁定 body 滚动
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      window.removeEventListener('keydown', onKey)
      document.body.style.overflow = prev
    }
  }, [open, onClose])

  if (!open) return <>{children}</>

  return (
    <div
      className="focus-mode-backdrop"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
    >
      <div className="focus-mode-card" onClick={(e) => e.stopPropagation()}>
        {(title || hint) && (
          <div className="focus-mode-header">
            <div className="focus-mode-title">{title}</div>
            <div className="focus-mode-actions">
              {hint && <div className="focus-mode-hint">{hint}</div>}
              <button
                type="button"
                className="focus-mode-close"
                onClick={onClose}
                aria-label="关闭聚焦模式"
                title="关闭 (Esc)"
              >
                <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
                  <path
                    d="M4 4L14 14M14 4L4 14"
                    stroke="currentColor"
                    strokeWidth="1.6"
                    strokeLinecap="round"
                  />
                </svg>
              </button>
            </div>
          </div>
        )}
        <div className="focus-mode-body">{children}</div>
      </div>
    </div>
  )
}
