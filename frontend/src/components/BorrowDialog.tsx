// 借调三问表单（模态）：提交时经 WS 发送 control signal loan
// 借调三问：目标角色 / 借调目标 / 必要性 / 不借调的代价
import { useState, useEffect } from 'react'
import type { FormEvent } from 'react'
import { useMeeting } from '../store/MeetingContext.tsx'
import type { BorrowRequestPayload } from '../types/events.ts'

interface BorrowDialogProps {
  open: boolean
  onClose: () => void
}

export function BorrowDialog({ open, onClose }: BorrowDialogProps) {
  const { sendBorrow } = useMeeting()
  const [targetRole, setTargetRole] = useState('engineer')
  const [goal, setGoal] = useState('')
  const [necessary, setNecessary] = useState('')
  const [noLoanCost, setNoLoanCost] = useState('')

  // 打开时重置表单
  useEffect(() => {
    if (open) {
      setTargetRole('engineer')
      setGoal('')
      setNecessary('')
      setNoLoanCost('')
    }
  }, [open])

  if (!open) return null

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault()
    const payload: BorrowRequestPayload = {
      target_role: targetRole,
      goal,
      necessary,
      no_loan_cost: noLoanCost,
    }
    // 经 WS 发送 loan 控制信号
    sendBorrow(payload)
    onClose()
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal borrow-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3>借调专家三问</h3>
          <button type="button" className="modal-close" onClick={onClose} aria-label="关闭">
            ×
          </button>
        </div>
        <form className="borrow-form" onSubmit={handleSubmit}>
          <label className="form-row">
            <span className="field-label">目标角色</span>
            <select value={targetRole} onChange={(e) => setTargetRole(e.target.value)}>
              <option value="engineer">工程师</option>
              <option value="product_architect">产品架构师</option>
              <option value="moderator">主持人</option>
            </select>
          </label>
          <label className="form-row">
            <span className="field-label">借调目标</span>
            <textarea
              value={goal}
              onChange={(e) => setGoal(e.target.value)}
              placeholder="借调该专家要解决什么问题？"
              rows={2}
              required
            />
          </label>
          <label className="form-row">
            <span className="field-label">必要性</span>
            <textarea
              value={necessary}
              onChange={(e) => setNecessary(e.target.value)}
              placeholder="为什么必须借调，而非用现有角色？"
              rows={2}
              required
            />
          </label>
          <label className="form-row">
            <span className="field-label">不借调的代价</span>
            <textarea
              value={noLoanCost}
              onChange={(e) => setNoLoanCost(e.target.value)}
              placeholder="若不借调，会造成什么损失？"
              rows={2}
              required
            />
          </label>
          <div className="modal-actions">
            <button type="button" className="btn btn-ghost" onClick={onClose}>
              取消
            </button>
            <button type="submit" className="btn btn-primary">
              提交借调
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
