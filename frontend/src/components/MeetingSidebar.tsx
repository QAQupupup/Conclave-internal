// 会议列表侧边栏：展示所有历史会议，支持切换 / 新建 / 删除 / 折叠
import { useState, useEffect, useCallback } from 'react'
import { listMeetings, deleteMeeting } from '../lib/api.ts'
import { useMeeting } from '../store/MeetingContext.tsx'
import { usePersistentState } from '../hooks/usePersistentState.ts'
import { STAGE_LABELS, getMeetingStatusInfo } from '../constants.ts'

interface MeetingListItem {
  meeting_id: string
  topic: string
  stage: string
  status: string
  created_at?: string
  is_running?: boolean
}

export function MeetingSidebar() {
  const { meetingId, selectMeeting } = useMeeting()
  const [meetings, setMeetings] = useState<MeetingListItem[]>([])
  const [concurrentLimit, setConcurrentLimit] = useState(0)
  const [runningCount, setRunningCount] = useState(0)
  const [loading, setLoading] = useState(false)
  // 会议列表折叠状态（持久化）
  const [listCollapsed, setListCollapsed] = usePersistentState<boolean>(
    'conclave-meeting-list-collapsed',
    false,
  )
  // 删除确认状态：记录当前待确认删除的会议 ID 及模式
  const [pendingDelete, setPendingDelete] = useState<{ id: string; mode: 'soft' | 'hard' } | null>(null)
  // 删除中的会议 ID（loading）
  const [deletingId, setDeletingId] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const data = await listMeetings()
      // 后端已按 created_at DESC 返回（最新在前）。运行中的会议置顶。
      const running = data.meetings.filter(m => m.is_running)
      const others = data.meetings.filter(m => !m.is_running)
      setMeetings([...running, ...others])
      setConcurrentLimit(data.concurrent_limit)
      setRunningCount(data.running_count)
    } catch (err) {
      console.error('刷新会议列表失败:', err)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    refresh()
    // 每 5 秒刷新一次列表（捕获运行中会议的状态变化）
    const timer = setInterval(refresh, 5000)
    return () => clearInterval(timer)
  }, [refresh])

  const statusLabel = (status: string, stage: string) => {
    const stageLabel = STAGE_LABELS[stage as keyof typeof STAGE_LABELS] ?? stage
    return getMeetingStatusInfo(status, stageLabel)
  }

  /** 执行删除 */
  const handleDelete = useCallback(
    async (id: string, mode: 'soft' | 'hard') => {
      setDeletingId(id)
      try {
        await deleteMeeting(id, mode)
        // 如果删除的是当前选中的会议，重置到创建页
        if (id === meetingId) {
          selectMeeting(null)
        }
        // 刷新列表
        await refresh()
      } catch (err) {
        console.error('删除会议失败:', err)
      } finally {
        setDeletingId(null)
        setPendingDelete(null)
      }
    },
    [meetingId, selectMeeting, refresh],
  )

  return (
    <div className="meeting-sidebar">
      <div className="sidebar-header">
        <h3>会议列表</h3>
        <button className="btn btn-sm" onClick={refresh} disabled={loading}>
          {loading ? '⟳' : '↻'}
        </button>
      </div>
      <button className="btn btn-primary sidebar-new-btn" onClick={() => selectMeeting(null)}>
        + 新建会议
      </button>

      {/* 会议列表折叠/展开 */}
      <div
        className={`meeting-list-zone ${listCollapsed ? 'is-collapsed' : ''}`}
      >
        <button
          type="button"
          className="meeting-list-toggle"
          onClick={() => setListCollapsed(v => !v)}
          title={listCollapsed ? '展开列表' : '收起列表'}
        >
          <span className={`toggle-arrow ${listCollapsed ? 'is-collapsed' : ''}`}>›</span>
          <span className="toggle-label">
            历史会议 ({meetings.length})
          </span>
          <span className="toggle-running">
            {runningCount > 0 && <span className="running-pulse" title={`${runningCount} 个运行中`} />}
          </span>
        </button>
        <div className="meeting-list">
          {meetings.length === 0 && <div className="meeting-empty">暂无会议</div>}
          {meetings.map((m) => {
            const sl = statusLabel(m.status, m.stage)
            const isActive = m.meeting_id === meetingId
            const isPendingDelete = pendingDelete?.id === m.meeting_id
            const isDeleting = deletingId === m.meeting_id
            const currentDeleteMode = pendingDelete?.mode ?? 'soft'
            return (
              <div
                key={m.meeting_id}
                className={`meeting-item ${isActive ? 'active' : ''} ${isPendingDelete ? 'pending-delete' : ''}`}
                onClick={() => !isPendingDelete && !isDeleting && selectMeeting(m.meeting_id)}
              >
                <div className="meeting-topic">
                  {m.is_running && (
                    <span className="running-pulse" title="运行中" aria-hidden="true" />
                  )}
                  <span className="meeting-topic-text">{m.topic || '(无议题)'}</span>
                  {/* 删除按钮：hover 时显示，运行中的会议禁用 */}
                  <button
                    type="button"
                    className="meeting-delete-btn"
                    title={m.is_running ? '运行中，无法删除' : '删除会议'}
                    disabled={m.is_running || isDeleting}
                    onClick={(e) => {
                      e.stopPropagation()
                      setPendingDelete({ id: m.meeting_id, mode: 'soft' })
                    }}
                  >
                    {isDeleting ? '⟳' : '×'}
                  </button>
                </div>
                <div className="meeting-meta">
                  <span className={`meeting-status ${sl.cls}`}>{sl.text}</span>
                  <span className="meeting-id">{m.meeting_id.slice(-8)}</span>
                </div>
                {/* 删除确认面板 */}
                {isPendingDelete && (
                  <div className="delete-confirm" onClick={(e) => e.stopPropagation()}>
                    <div className="delete-confirm-title">确认删除？</div>
                    <div className="delete-confirm-modes">
                      <label className={`delete-mode-option ${currentDeleteMode === 'soft' ? 'active' : ''}`}>
                        <input
                          type="radio"
                          name={`del-mode-${m.meeting_id}`}
                          value="soft"
                          checked={currentDeleteMode === 'soft'}
                          onChange={() => setPendingDelete({ id: m.meeting_id, mode: 'soft' })}
                        />
                        <span>软删除（保留数据）</span>
                      </label>
                      <label className={`delete-mode-option ${currentDeleteMode === 'hard' ? 'active' : ''}`}>
                        <input
                          type="radio"
                          name={`del-mode-${m.meeting_id}`}
                          value="hard"
                          checked={currentDeleteMode === 'hard'}
                          onChange={() => setPendingDelete({ id: m.meeting_id, mode: 'hard' })}
                        />
                        <span>永久删除（不可恢复）</span>
                      </label>
                    </div>
                    <div className="delete-confirm-actions">
                      <button
                        type="button"
                        className="btn btn-sm btn-danger"
                        onClick={() => handleDelete(m.meeting_id, currentDeleteMode)}
                        disabled={isDeleting}
                      >
                        {isDeleting ? '删除中…' : '确认删除'}
                      </button>
                      <button
                        type="button"
                        className="btn btn-sm btn-ghost"
                        onClick={() => setPendingDelete(null)}
                      >
                        取消
                      </button>
                    </div>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </div>

      <div className="sidebar-footer">
        运行中 {runningCount} / 上限 {concurrentLimit}
      </div>
    </div>
  )
}
