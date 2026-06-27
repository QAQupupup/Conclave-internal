// 会议列表侧边栏：展示所有历史会议，支持切换 / 新建
import { useState, useEffect } from 'react'
import { listMeetings } from '../lib/api.ts'
import { useMeeting } from '../store/MeetingContext.tsx'

interface MeetingListItem {
  meeting_id: string
  topic: string
  stage: string
  status: string
  created_at?: string
  is_running?: boolean
}

export function MeetingSidebar() {
  const { meetingId, selectMeeting, reset } = useMeeting()
  const [meetings, setMeetings] = useState<MeetingListItem[]>([])
  const [concurrentLimit, setConcurrentLimit] = useState(0)
  const [runningCount, setRunningCount] = useState(0)
  const [loading, setLoading] = useState(false)

  const refresh = async () => {
    setLoading(true)
    try {
      const data = await listMeetings()
      setMeetings(data.meetings.reverse()) // 最新的在前
      setConcurrentLimit(data.concurrent_limit)
      setRunningCount(data.running_count)
    } catch {
      // 静默失败
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    refresh()
    // 每 5 秒刷新一次列表（捕获运行中会议的状态变化）
    const timer = setInterval(refresh, 5000)
    return () => clearInterval(timer)
  }, [])

  const statusLabel = (status: string, stage: string) => {
    if (status === 'done') return { text: '已完成', cls: 'done' }
    if (status === 'running') return { text: `${stage} 运行中`, cls: 'running' }
    if (status === 'paused') return { text: '已暂停', cls: 'paused' }
    if (status === 'aborted') return { text: '已终止', cls: 'aborted' }
    return { text: stage, cls: '' }
  }

  return (
    <div className="meeting-sidebar">
      <div className="sidebar-header">
        <h3>会议列表</h3>
        <button className="btn btn-sm" onClick={refresh} disabled={loading}>
          {loading ? '⟳' : '↻'}
        </button>
      </div>
      <button className="btn btn-primary sidebar-new-btn" onClick={reset}>
        + 新建会议
      </button>
      <div className="meeting-list">
        {meetings.length === 0 && <div className="meeting-empty">暂无会议</div>}
        {meetings.map((m) => {
          const sl = statusLabel(m.status, m.stage)
          const isActive = m.meeting_id === meetingId
          return (
            <div
              key={m.meeting_id}
              className={`meeting-item ${isActive ? 'active' : ''}`}
              onClick={() => selectMeeting(m.meeting_id)}
            >
              <div className="meeting-topic">
                {m.is_running && (
                  <span className="running-pulse" title="运行中" aria-hidden="true" />
                )}
                {m.topic || '(无议题)'}
              </div>
              <div className="meeting-meta">
                <span className={`meeting-status ${sl.cls}`}>{sl.text}</span>
                <span className="meeting-id">{m.meeting_id.slice(-8)}</span>
              </div>
            </div>
          )
        })}
      </div>
      <div className="sidebar-footer">
        运行中 {runningCount} / 上限 {concurrentLimit}
      </div>
    </div>
  )
}
