// 浮动徽标：证据/产出/报告/Token/议题 五个功能入口
// 鼠标移入显示名称，点击弹出模态面板
import { useState, useCallback } from 'react'
import type { ReactNode } from 'react'

export interface BadgeItem {
  id: string
  label: string
  icon: ReactNode
  /** 可选的未读数或状态标识 */
  badge?: string
}

interface FloatingBadgesProps {
  badges: BadgeItem[]
  activeId: string | null
  onSelect: (id: string) => void
}

/** 面板弹窗：点击徽标后弹出，标题 + 内容 */
export function PanelModal({
  open,
  title,
  onClose,
  children,
}: {
  open: boolean
  title: string
  onClose: () => void
  children: ReactNode
}) {
  if (!open) return null

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal panel-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3>{title}</h3>
          <button type="button" className="modal-close" onClick={onClose} aria-label="关闭">
            ×
          </button>
        </div>
        <div className="panel-modal-body">
          {children}
        </div>
      </div>
    </div>
  )
}

export function FloatingBadges({ badges, activeId, onSelect }: FloatingBadgesProps) {
  const [hoveredId, setHoveredId] = useState<string | null>(null)

  const handleClick = useCallback(
    (id: string) => {
      if (activeId === id) {
        onSelect('') // 再次点击关闭
      } else {
        onSelect(id)
      }
    },
    [activeId, onSelect],
  )

  return (
    <div className="floating-badges">
      {badges.map((b) => (
        <button
          key={b.id}
          type="button"
          className={`floating-badge${activeId === b.id ? ' active' : ''}`}
          onClick={() => handleClick(b.id)}
          onMouseEnter={() => setHoveredId(b.id)}
          onMouseLeave={() => setHoveredId(null)}
          title={b.label}
          aria-label={b.label}
        >
          <span className="floating-badge-icon">{b.icon}</span>
          {hoveredId === b.id && (
            <span className="floating-badge-tooltip">{b.label}</span>
          )}
          {b.badge && (
            <span className="floating-badge-dot">{b.badge}</span>
          )}
        </button>
      ))}
    </div>
  )
}