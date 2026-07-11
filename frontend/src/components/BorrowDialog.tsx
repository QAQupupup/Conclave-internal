// 借调三问表单（模态）：提交时经 WS 发送 control signal loan
// 使用 AntD Modal + Form + Select + Input.TextArea + Alert + Button
import { useState, useEffect, useRef } from 'react'
import type { FormEvent } from 'react'
import { Modal, Form, Select, Input, Button, Alert, Space } from 'antd'
import { useMeeting } from '../store/MeetingContext.tsx'
import type { BorrowRequestPayload } from '../types/events.ts'

interface BorrowDialogProps {
  open: boolean
  onClose: () => void
}

type SubmitState = 'idle' | 'sending' | 'sent' | 'error'

const ROLE_OPTIONS = [
  { value: 'engineer', label: '工程师' },
  { value: 'product_architect', label: '产品架构师' },
  { value: 'moderator', label: '主持人' },
]

export function BorrowDialog({ open, onClose }: BorrowDialogProps) {
  const { sendBorrow, connected } = useMeeting()
  const [targetRole, setTargetRole] = useState('engineer')
  const [goal, setGoal] = useState('')
  const [necessary, setNecessary] = useState('')
  const [noLoanCost, setNoLoanCost] = useState('')
  const [submitState, setSubmitState] = useState<SubmitState>('idle')
  const sentTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    return () => {
      if (sentTimerRef.current) {
        clearTimeout(sentTimerRef.current)
        sentTimerRef.current = null
      }
    }
  }, [])

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

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
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
    sendBorrow(payload)
    if (sentTimerRef.current) clearTimeout(sentTimerRef.current)
    sentTimerRef.current = setTimeout(() => {
      setSubmitState('sent')
      sentTimerRef.current = null
    }, 500)
  }

  const handleClose = () => {
    if (submitState === 'sending') return
    onClose()
  }

  return (
    <Modal
      open={open}
      title="借调专家三问"
      onCancel={handleClose}
      footer={null}
      destroyOnClose
      maskClosable={submitState !== 'sending'}
    >
      <form onSubmit={handleSubmit}>
        <Form layout="vertical">
          <Form.Item label="目标角色">
            <Select value={targetRole} onChange={setTargetRole} options={ROLE_OPTIONS} />
          </Form.Item>
          <Form.Item label="借调目标" required>
            <Input.TextArea
              value={goal}
              onChange={(e) => setGoal(e.target.value)}
              placeholder="借调该专家要解决什么问题？"
              rows={2}
              required
            />
          </Form.Item>
          <Form.Item label="必要性" required>
            <Input.TextArea
              value={necessary}
              onChange={(e) => setNecessary(e.target.value)}
              placeholder="为什么必须借调，而非用现有角色？"
              rows={2}
              required
            />
          </Form.Item>
          <Form.Item label="不借调的代价" required>
            <Input.TextArea
              value={noLoanCost}
              onChange={(e) => setNoLoanCost(e.target.value)}
              placeholder="若不借调，会造成什么损失？"
              rows={2}
              required
            />
          </Form.Item>
        </Form>

        {submitState === 'error' && (
          <Alert
            message="WebSocket 未连接，无法发送借调请求。请检查会议是否正在运行。"
            type="error"
            showIcon
            style={{ marginBottom: 12 }}
          />
        )}
        {submitState === 'sent' && (
          <Alert
            message="借调请求已发送。后端将评估是否批准，请关注会议中的后续消息。"
            type="success"
            showIcon
            style={{ marginBottom: 12 }}
          />
        )}

        <Space style={{ display: 'flex', justifyContent: 'flex-end' }}>
          {submitState === 'sent' ? (
            <Button type="primary" onClick={onClose}>关闭</Button>
          ) : (
            <>
              <Button onClick={onClose} disabled={submitState === 'sending'}>取消</Button>
              <Button
                type="primary"
                htmlType="submit"
                loading={submitState === 'sending'}
                disabled={!connected}
              >
                提交借调
              </Button>
            </>
          )}
        </Space>
      </form>
    </Modal>
  )
}
