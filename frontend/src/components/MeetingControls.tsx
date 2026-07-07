// 会议控制按钮：暂停(橙) / 恢复(蓝) / 终止(红，带确认对话框)
// 按当前会议 status 决定显示哪些按钮，全部走 MeetingContext.controlMeeting（POST /meetings/:id/control）
import { useState } from 'react'
import { useMeeting } from '../store/MeetingContext.tsx'
import type { ControlRequest } from '../types/events.ts'

export function MeetingControls() {
  const { store, meetingId, controlMeeting } = useMeeting()
  const [loading, setLoading] = useState<string | null>(null)
  // 终止确认对话框
  const [abortConfirm, setAbortConfirm] = useState(false)

  // 无会议时 store.meeting 为 null，status 为 undefined，下方比较均不命中 → 不渲染按钮
  const status = store.meeting?.status

  const control = async (signal: ControlRequest['signal']) => {
    if (!meetingId) return
    setLoading(signal)
    try {
      await controlMeeting(meetingId, signal)
    } catch {
      // 静默：错误已在 reducer 中处理，避免阻塞 UI
    } finally {
      setLoading(null)
    }
  }

  // 已完成 / 已终止：不显示任何控制按钮
  if (status === 'done' || status === 'aborted') return null

  const busy = loading !== null

  return (
    <div className="meeting-controls">
      {status === 'running' && (
        <button
          type="button"
          className="btn btn-warn btn-sm"
          onClick={() => void control('pause')}
          disabled={busy}
        >
          {loading === 'pause' ? '…' : '暂停'}
        </button>
      )}
      {status === 'paused' && (
        <button
          type="button"
          className="btn btn-primary btn-sm"
          onClick={() => void control('resume')}
          disabled={busy}
        >
          {loading === 'resume' ? '…' : '恢复'}
        </button>
      )}
      {(status === 'running' || status === 'paused') && (
        <button
          type="button"
          className="btn btn-danger btn-sm"
          onClick={() => setAbortConfirm(true)}
          disabled={busy}
        >
          {loading === 'abort' ? '…' : '终止'}
        </button>
      )}

      {/* 终止确认对话框 */}
      {abortConfirm && (
        <div className="modal-overlay" onClick={() => setAbortConfirm(false)}>
          <div className="modal-card abort-confirm-modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-title">确认终止会议？</div>
            <p className="abort-confirm-text">
              终止是不可逆操作，会议将永久停止。已生成的产出物和聊天记录会保留。
            </p>
            <div className="abort-confirm-actions">
              <button
                type="button"
                className="btn btn-ghost"
                onClick={() => setAbortConfirm(false)}
              >
                取消
              </button>
              <button
                type="button"
                className="btn btn-danger"
                onClick={async () => {
                  setAbortConfirm(false)
                  await control('abort')
                }}
                disabled={busy}
              >
                {loading === 'abort' ? '终止中…' : '确认终止'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
