// 顶部 Header：会议标题、六阶段进度条、pause/resume/abort 控场按钮、连接状态
import { useMeeting } from '../store/MeetingContext.tsx'
import { STAGE_LABELS, STAGE_ORDER } from '../types/events.ts'

export function Header() {
  const { store, meetingId, connected, connectionError, controlMeeting } = useMeeting()
  const m = store.meeting
  if (!m) return null

  const currentIdx = STAGE_ORDER.indexOf(m.stage)

  // 按当前状态决定按钮可用性
  const canPause = m.status === 'running'
  const canResume = m.status === 'paused'
  const canAbort = m.status !== 'aborted' && m.status !== 'done'

  const handleControl = (signal: 'pause' | 'resume' | 'abort') => {
    if (!meetingId) return
    void controlMeeting(meetingId, signal)
  }

  return (
    <header className="app-header">
      <div className="header-left">
        <div className="header-title" title={m.topic}>{m.topic}</div>
        <div className="header-sub">
          <span className={`status-tag status-${m.status}`}>{statusLabel(m.status)}</span>
          <span className={`conn-tag ${connected ? 'on' : 'off'}`}>
            {connected ? 'WS 已连接' : connectionError ? 'WS 异常' : 'WS 未连接'}
          </span>
        </div>
      </div>

      <div className="stage-progress">
        {STAGE_ORDER.map((stage, idx) => {
          const isCurrent = stage === m.stage
          const isDone = idx < currentIdx
          return (
            <div
              key={stage}
              className={`stage-step ${isCurrent ? 'current' : ''} ${isDone ? 'done' : ''}`}
            >
              <div className="stage-dot">{idx + 1}</div>
              <div className="stage-name">{STAGE_LABELS[stage]}</div>
            </div>
          )
        })}
      </div>

      <div className="header-actions">
        <button
          type="button"
          className="btn btn-warn"
          onClick={() => handleControl('pause')}
          disabled={!canPause}
        >
          暂停
        </button>
        <button
          type="button"
          className="btn btn-primary"
          onClick={() => handleControl('resume')}
          disabled={!canResume}
        >
          恢复
        </button>
        <button
          type="button"
          className="btn btn-danger"
          onClick={() => handleControl('abort')}
          disabled={!canAbort}
        >
          终止
        </button>
      </div>
    </header>
  )
}

function statusLabel(status: string): string {
  switch (status) {
    case 'running':
      return '运行中'
    case 'paused':
      return '已暂停'
    case 'aborted':
      return '已终止'
    case 'done':
      return '已完成'
    default:
      return status
  }
}
