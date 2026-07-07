// 通用可折叠面板：用于报告区、右侧面板标题栏等场景
// 设计：通过 max-height + opacity 实现平滑动画，避免 display:none 硬切
// 用法：<CollapsibleSection title="标题" defaultOpen>内容</CollapsibleSection>
import { useCallback, useRef, useState, useEffect } from 'react'
import type { ReactNode } from 'react'

interface CollapsibleSectionProps {
  /** 标题文字 */
  title: string
  /** 子内容 */
  children: ReactNode
  /** 默认是否展开（非受控模式） */
  defaultOpen?: boolean
  /** 受控模式下的展开状态 */
  open?: boolean
  /** 受控模式下的切换回调 */
  onToggle?: (open: boolean) => void
  /** 附加到根元素的 class（用于场景定制） */
  className?: string
  /** 标题右侧的附加内容（如计数、操作按钮） */
  headerExtra?: ReactNode
}

export function CollapsibleSection({
  title,
  children,
  defaultOpen = false,
  open: controlledOpen,
  onToggle,
  className = '',
  headerExtra,
}: CollapsibleSectionProps) {
  // 非受控内部状态
  const [internalOpen, setInternalOpen] = useState(defaultOpen)
  const isControlled = controlledOpen !== undefined
  const isOpen = isControlled ? controlledOpen : internalOpen

  // 测量内容高度用于 max-height 动画
  const bodyRef = useRef<HTMLDivElement | null>(null)
  const [bodyHeight, setBodyHeight] = useState<number | undefined>(undefined)

  useEffect(() => {
    const el = bodyRef.current
    if (!el) return
    // 测量 scrollHeight 用于动画目标值
    const measure = () => setBodyHeight(el.scrollHeight)
    measure()
    // 内容变化时重新测量（简易方案：100ms 后再测一次）
    const timer = setTimeout(measure, 100)
    return () => clearTimeout(timer)
  }, [children, isOpen])

  const handleToggle = useCallback(() => {
    const next = !isOpen
    if (!isControlled) setInternalOpen(next)
    onToggle?.(next)
  }, [isOpen, isControlled, onToggle])

  return (
    <div className={`collapsible-section ${isOpen ? 'is-open' : ''} ${className}`.trim()}>
      <div className="collapsible-header" onClick={handleToggle}>
        <span className={`collapsible-arrow ${isOpen ? 'is-open' : ''}`}>
          <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
            <path
              d="M3 1.5L7 5L3 8.5"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </span>
        <span className="collapsible-title">{title}</span>
        {headerExtra && <span className="collapsible-extra">{headerExtra}</span>}
      </div>
      <div
        ref={bodyRef}
        className="collapsible-body"
        style={{
          maxHeight: isOpen ? (bodyHeight ? `${bodyHeight}px` : 'none') : '0px',
          opacity: isOpen ? 1 : 0,
        }}
      >
        <div className="collapsible-body-inner">{children}</div>
      </div>
    </div>
  )
}
