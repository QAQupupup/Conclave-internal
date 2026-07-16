// 借调审批弹窗：主持人自动申请超过3次后，向用户弹出审批请求
// 使用 AntD Modal + Descriptions + Button + Alert + Space + Tag
import { useState, useEffect, useCallback } from 'react'
import type { FC } from 'react'
import { Modal, Descriptions, Button, Alert, Space, Tag } from 'antd'
import { ExclamationCircleOutlined } from '@ant-design/icons'
import { useMeeting } from '../store/MeetingContext.tsx'
import type { BorrowRequest } from '../types/events.ts'

interface Props {
  request: BorrowRequest | null
  onClose: () => void
}

const ROLE_DISPLAY_NAMES: Record<string, string> = {
  security_expert: '安全专家',
  data_engineer: '数据工程师',
  ux_designer: 'UX设计师',
  marketing_expert: '市场专家',
  engineer: '工程师',
  product_architect: '产品架构师',
  moderator: '主持人',
}

function getRoleDisplay(roleId: string): string {
  return ROLE_DISPLAY_NAMES[roleId] || roleId
}

export const BorrowApprovalDialog: FC<Props> = ({ request, onClose }) => {
  const { approveBorrow, rejectBorrow, freezeBorrow, connected } = useMeeting()
  const [actionState, setActionState] = useState<'idle' | 'processing' | 'done'>('idle')
  const [actionResult, setActionResult] = useState<string | null>(null)

  useEffect(() => {
    if (request) {
      setActionState('idle')
      setActionResult(null)
    }
  }, [request?.id])

  const handleApprove = useCallback(() => {
    if (!request || !connected) return
    setActionState('processing')
    approveBorrow(request.id)
    setTimeout(() => {
      setActionState('done')
      setActionResult('approved')
      setTimeout(onClose, 800)
    }, 500)
  }, [request, connected, approveBorrow, onClose])

  const handleReject = useCallback(() => {
    if (!request || !connected) return
    setActionState('processing')
    rejectBorrow(request.id, '用户认为现有团队已足够覆盖该议题')
    setTimeout(() => {
      setActionState('done')
      setActionResult('rejected')
      setTimeout(onClose, 800)
    }, 500)
  }, [request, connected, rejectBorrow, onClose])

  const handleFreeze = useCallback(() => {
    if (!connected) return
    setActionState('processing')
    freezeBorrow()
    setTimeout(() => {
      setActionState('done')
      setActionResult('frozen')
      setTimeout(onClose, 800)
    }, 500)
  }, [connected, freezeBorrow, onClose])

  if (!request) return null

  const roleName = getRoleDisplay(request.target_role)
  const disabled = actionState !== 'idle' || !connected

  return (
    <Modal
      open
      title={
        <Space>
          <ExclamationCircleOutlined className="borrow-approval-dialog-warn-color" />
          <span>借调审批请求</span>
        </Space>
      }
      onCancel={onClose}
      footer={
        <div className="borrow-approval-dialog-footer">
          <Button onClick={onClose} disabled={disabled}>
            稍后处理
          </Button>
          <Space>
            <Button
              onClick={handleFreeze}
              disabled={disabled}
              title="冻结后本次会议不再自动申请借调"
            >
              冻结借调
            </Button>
            <Button onClick={handleReject} disabled={disabled}>拒绝</Button>
            <Button
              type="primary"
              onClick={handleApprove}
              loading={actionState === 'processing'}
              disabled={disabled}
            >
              批准借调 {roleName}
            </Button>
          </Space>
        </div>
      }
      closable={true}
      maskClosable={true}
    >
      <p className="borrow-approval-dialog-desc">
        主持人检测到当前讨论涉及 <Tag color="blue">{roleName}</Tag> 领域的专业问题，
        自动借调次数已达上限，需要您审批是否借调。
      </p>

      <Descriptions column={1} size="small" bordered>
        <Descriptions.Item label="目标角色">
          <Tag color="blue">{roleName}</Tag>
        </Descriptions.Item>
        <Descriptions.Item label="借调目标">{request.goal}</Descriptions.Item>
        <Descriptions.Item label="必要性">{request.necessary}</Descriptions.Item>
        <Descriptions.Item label="不借调代价">
          <span className="borrow-approval-dialog-warn-color">{request.no_loan_cost}</span>
        </Descriptions.Item>
      </Descriptions>

      {actionResult === 'approved' && (
        <Alert message={`已批准借调 ${roleName}，该专家将立即加入讨论`} type="success" showIcon className="borrow-approval-dialog-alert" />
      )}
      {actionResult === 'rejected' && (
        <Alert message="已拒绝本次借调请求" type="info" showIcon className="borrow-approval-dialog-alert" />
      )}
      {actionResult === 'frozen' && (
        <Alert message="已冻结借调功能，本次会议后续不再自动申请借调" type="warning" showIcon className="borrow-approval-dialog-alert" />
      )}
      {!connected && (
        <Alert message="WebSocket 未连接，无法审批" type="error" showIcon className="borrow-approval-dialog-alert" />
      )}
    </Modal>
  )
}
