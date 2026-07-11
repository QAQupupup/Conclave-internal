// 浮动徽标：证据/产出/报告/Token/议题 五个功能入口
// 使用 AntD Button + Tooltip + Modal + Badge
import { useCallback } from 'react'
import { Button, Tooltip, Modal, Badge } from 'antd'
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
  return (
    <Modal
      open={open}
      title={title}
      onCancel={onClose}
      footer={null}
      width={720}
      centered
      destroyOnClose
    >
      {children}
    </Modal>
  )
}

export function FloatingBadges({ badges, activeId, onSelect }: FloatingBadgesProps) {
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
    <div className="floating-badges" style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {badges.map((b) => {
        const isActive = activeId === b.id
        const btn = (
          <Badge key={b.id} count={b.badge || 0} size="small" offset={[-4, 4]}>
            <Button
              type={isActive ? 'primary' : 'default'}
              shape="circle"
              icon={b.icon}
              onClick={() => handleClick(b.id)}
              aria-label={b.label}
              style={{ width: 40, height: 40 }}
            />
          </Badge>
        )
        return (
          <Tooltip key={b.id} title={b.label} placement="left">
            {btn}
          </Tooltip>
        )
      })}
    </div>
  )
}
