// 借调审批弹窗：主持人自动申请超过3次后，向用户弹出审批请求
// 用户可批准、拒绝借调，或冻结后续所有借调
import { useState, useEffect, useCallback } from 'react'
import type { FC } from 'react'
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

  // 弹窗打开时重置状态
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

  return (
    <div className="modal-overlay borrow-approval-overlay">
      <div className="modal borrow-approval-modal" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <h3>借调审批请求</h3>
        </div>
        <div className="borrow-approval-body">
          <div className="borrow-approval-icon">
            <svg width="40" height="40" viewBox="0 0 40 40" fill="none">
              <circle cx="20" cy="20" r="18" stroke="var(--accent)" strokeWidth="2" fill="var(--accent-light)" />
              <path d="M20 12v10M20 28v.01" stroke="var(--accent)" strokeWidth="2.5" strokeLinecap="round" />
            </svg>
          </div>
          <p className="borrow-approval-intro">
            主持人检测到当前讨论涉及 <strong>{roleName}</strong> 领域的专业问题，
            自动借调次数已达上限，需要您审批是否借调。
          </p>

          <div className="borrow-approval-detail">
            <div className="borrow-approval-row">
              <span className="borrow-approval-label">目标角色</span>
              <span className="borrow-approval-value borrow-approval-role">{roleName}</span>
            </div>
            <div className="borrow-approval-row">
              <span className="borrow-approval-label">借调目标</span>
              <span className="borrow-approval-value">{request.goal}</span>
            </div>
            <div className="borrow-approval-row">
              <span className="borrow-approval-label">必要性</span>
              <span className="borrow-approval-value">{request.necessary}</span>
            </div>
            <div className="borrow-approval-row">
              <span className="borrow-approval-label">不借调代价</span>
              <span className="borrow-approval-value borrow-approval-warn">{request.no_loan_cost}</span>
            </div>
          </div>

          {actionResult === 'approved' && (
            <div className="borrow-feedback borrow-success">已批准借调 {roleName}，该专家将立即加入讨论</div>
          )}
          {actionResult === 'rejected' && (
            <div className="borrow-feedback borrow-info">已拒绝本次借调请求</div>
          )}
          {actionResult === 'frozen' && (
            <div className="borrow-feedback borrow-warn">已冻结借调功能，本次会议后续不再自动申请借调</div>
          )}
          {!connected && (
            <div className="borrow-feedback borrow-error">WebSocket 未连接，无法审批</div>
          )}
        </div>
        <div className="modal-actions borrow-approval-actions">
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={handleFreeze}
            disabled={actionState !== 'idle' || !connected}
            title="冻结后本次会议不再自动申请借调"
          >
            冻结借调
          </button>
          <div className="borrow-approval-main-actions">
            <button
              type="button"
              className="btn btn-ghost"
              onClick={handleReject}
              disabled={actionState !== 'idle' || !connected}
            >
              拒绝
            </button>
            <button
              type="button"
              className="btn btn-primary"
              onClick={handleApprove}
              disabled={actionState !== 'idle' || !connected}
            >
              {actionState === 'processing' ? '处理中…' : `批准借调 ${roleName}`}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
