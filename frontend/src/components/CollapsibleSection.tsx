// 通用可折叠面板：使用 AntD Collapse 组件
import { useCallback, useState } from 'react'
import type { ReactNode } from 'react'
import { Collapse } from 'antd'

interface CollapsibleSectionProps {
  title: string
  children: ReactNode
  defaultOpen?: boolean
  open?: boolean
  onToggle?: (open: boolean) => void
  className?: string
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
  const [internalOpen, setInternalOpen] = useState(defaultOpen)
  const isControlled = controlledOpen !== undefined
  const isOpen = isControlled ? controlledOpen : internalOpen

  const handleToggle = useCallback(() => {
    const next = !isOpen
    if (!isControlled) setInternalOpen(next)
    onToggle?.(next)
  }, [isOpen, isControlled, onToggle])

  return (
    <Collapse
      activeKey={isOpen ? ['1'] : []}
      onChange={(keys) => {
        const nextOpen = keys.includes('1')
        if (nextOpen !== isOpen) handleToggle()
      }}
      items={[{
        key: '1',
        label: (
          <span>
            <span className="collapsible-title">{title}</span>
            {headerExtra && <span className="collapsible-extra" style={{ marginLeft: 8 }}>{headerExtra}</span>}
          </span>
        ),
        children: <div className="collapsible-body-inner">{children}</div>,
      }]}
      className={`collapsible-section ${className}`.trim()}
      bordered={false}
    />
  )
}
