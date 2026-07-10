// 借调三问表单（模态）：提交时经 WS 发送 control signal loan
// 借调三问：目标角色 / 借调目标 / 必要性 / 不借调的代价
// 提交后显示反馈状态（发送中/已发送/连接失败），不立即关闭
import { useState, useEffect, useRef } from 'react'
import type { FormEvent } from 'react'
import { useMeeting } from '../store/MeetingContext.tsx'
import type { BorrowRequestPayload } from '../types/events.ts'

interface BorrowDialogProps {
  open: boolean
  onClose: () => void
}

type SubmitState = 'idle' | 'sending' | 'sent' | 'error'

export function BorrowDialog({ open, onClose }: BorrowDialogProps) {
  const { sendBorrow, connected } = useMeeting()
  const [targetRole, setTargetRole] = useState('engineer')
  const [goal, setGoal] = useState('')
  const [necessary, setNecessary] = useState('')
  const [noLoanCost, setNoLoanCost] = useState('')
  const [submitState, setSubmitState] = useState<SubmitState>('idle')
  const sentTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // 清理 timer（组件卸载或对话框关闭时）
  useEffect(() => {
    return () => {
      if (sentTimerRef.current) {
        clearTimeout(sentTimerRef.current)
        sentTimerRef.current = null
      }
    }
  }, [])

  // 打开时重置表单
  useEffect(() => {
    if (open) {
      setTargetRole('engineer')
      setGoal('')
      setNecessary('')
      setNoLoanCost('')
      setSubmitState('idle')
      if (sentTimerRef.current) {
        clearTimeout(sentTimerRef.current)
        sentTimerRef.current = null
      }
    }
  }, [open])

  if (!open) return null

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    // 连接检查：WS 未连接时不提交
    if (!connected) {
      setSubmitState('error')
      return
    }
    const payload: BorrowRequestPayload = {
      target_role: targetRole,
      goal,
      necessary,
      no_loan_cost: noLoanCost,
    }
    setSubmitState('sending')
    // 经 WS 发送 loan 控制信号
    sendBorrow(payload)
    // 短暂等待后显示已发送状态（WS send 是异步的，无法精确确认后端接收）
    if (sentTimerRef.current) clearTimeout(sentTimerRef.current)
    sentTimerRef.current = setTimeout(() => {
      setSubmitState('sent')
      sentTimerRef.current = null
    }, 500)
  }

  const handleClose = () => {
    if (submitState === 'sending') return // 发送中不允许关闭
    onClose()
  }

  return (
    <div className="modal-overlay" onClick={handleClose}>
      <div className="modal borrow-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3>借调专家三问</h3>
          <button type="button" className="modal-close" onClick={handleClose} aria-label="关闭">
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

          {/* 反馈状态 */}
          {submitState === 'error' && (
            <div className="borrow-feedback borrow-error">
              WebSocket 未连接，无法发送借调请求。请检查会议是否正在运行。
            </div>
          )}
          {submitState === 'sent' && (
            <div className="borrow-feedback borrow-success">
              借调请求已发送。后端将评估是否批准，请关注会议中的后续消息。
            </div>
          )}

          <div className="modal-actions">
            {submitState === 'sent' ? (
              <button type="button" className="btn btn-primary" onClick={onClose}>
                关闭
              </button>
            ) : (
              <>
                <button
                  type="button"
                  className="btn btn-ghost"
                  onClick={onClose}
                  disabled={submitState === 'sending'}
                >
                  取消
                </button>
                <button
                  type="submit"
                  className="btn btn-primary"
                  disabled={submitState === 'sending' || !connected}
                >
                  {submitState === 'sending' ? '发送中…' : '提交借调'}
                </button>
              </>
            )}
          </div>
        </form>
      </div>
    </div>
  )
}
