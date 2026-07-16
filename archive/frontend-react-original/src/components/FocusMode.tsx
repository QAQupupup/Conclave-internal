// FocusMode：全屏聚焦模式，使用 AntD Modal
import { Modal } from 'antd'
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
  return (
    <Modal
      open={open}
      onCancel={onClose}
      title={title}
      footer={null}
      width={900}
      centered
      destroyOnClose
    >
      {hint && <div className="focus-mode-hint focus-mode-hint-extra">{hint}</div>}
      <div className="focus-mode-body">{children}</div>
    </Modal>
  )
}
