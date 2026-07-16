// 会议侧边栏：轻量级会议切换器
// 设计原则：侧栏只负责会议快速切换，新建/删除等管理操作在看板页或会议控制栏完成
// 避免在会议视图内嵌套"迷你看板"造成双层结构
import { useState, useEffect, useCallback, useMemo } from 'react'
import { List, Input, Empty, Tooltip, Tag, Popconfirm, Radio, message } from 'antd'
import {
  SearchOutlined,
  MenuUnfoldOutlined,
  ClockCircleOutlined,
} from '@ant-design/icons'
import { listMeetings, deleteMeeting } from '../lib/api.ts'
import { useMeeting } from '../store/MeetingContext.tsx'
import { clearLogs } from '../hooks/useMeetingLogs.ts'
import { navigate } from '../lib/router.ts'

interface MeetingListItem {
  meeting_id: string
  topic: string
  stage: string
  status: string
  created_at?: string
  updated_at?: string
  is_running?: boolean
  flow_plan?: string
}

interface MeetingSidebarProps {
  onCollapse?: () => void
}

function getTimeAgo(dateStr?: string): string {
  if (!dateStr) return ''
  const date = new Date(dateStr)
  const now = new Date()
  const diffMs = now.getTime() - date.getTime()
  const diffMins = Math.floor(diffMs / 60000)
  if (diffMins < 1) return '刚刚'
  if (diffMins < 60) return `${diffMins}分钟前`
  const diffHours = Math.floor(diffMins / 60)
  if (diffHours < 24) return `${diffHours}小时前`
  const diffDays = Math.floor(diffHours / 24)
  if (diffDays < 30) return `${diffDays}天前`
  return date.toLocaleDateString()
}

export function MeetingSidebar({ onCollapse }: MeetingSidebarProps) {
  const { meetingId, selectMeeting } = useMeeting()
  const [meetings, setMeetings] = useState<MeetingListItem[]>([])
  const [loading, setLoading] = useState(false)
  const [search, setSearch] = useState('')
  const [deleteMode, setDeleteMode] = useState<'soft' | 'hard'>('soft')

  const fetchMeetings = useCallback(async () => {
    setLoading(true)
    try {
      const data = await listMeetings()
      setMeetings(data.meetings || [])
    } catch (err) {
      console.error('加载会议列表失败:', err)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchMeetings()
    const interval = setInterval(fetchMeetings, 15000)
    return () => clearInterval(interval)
  }, [fetchMeetings])

  // 排序：运行中置顶，其他按更新时间倒序
  const sortedMeetings = useMemo(() => {
    const running = meetings.filter((m) => m.is_running)
    const others = meetings.filter((m) => !m.is_running)
    return [...running, ...others]
  }, [meetings])

  const filteredMeetings = useMemo(() => {
    if (!search.trim()) return sortedMeetings
    const q = search.toLowerCase()
    return sortedMeetings.filter(
      (m) =>
        m.topic.toLowerCase().includes(q) || m.meeting_id.toLowerCase().includes(q),
    )
  }, [sortedMeetings, search])

  const handleSelect = (id: string) => {
    selectMeeting(id)
    navigate(`/meeting/${id}`)
  }

  const handleDelete = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation()
    try {
      await deleteMeeting(id, deleteMode)
      clearLogs(id)
      message.success(deleteMode === 'hard' ? '会议已永久删除' : '会议已删除')
      if (id === meetingId) {
        selectMeeting(null)
        navigate('/board')
      } else {
        fetchMeetings()
      }
    } catch (err) {
      console.error('删除会议失败:', err)
      message.error('删除失败')
    }
  }

  return (
    <aside className="meeting-sidebar">
      <div className="meeting-sidebar-header">
        <Tooltip title="收起侧栏" placement="right">
          <button
            className="meeting-sidebar-collapse-btn"
            onClick={onCollapse}
            aria-label="收起侧栏"
          >
            <MenuUnfoldOutlined />
          </button>
        </Tooltip>
        <span className="meeting-sidebar-title">会议列表</span>
      </div>

      <div className="meeting-sidebar-search">
        <Input
          prefix={<SearchOutlined style={{ color: 'var(--text-tertiary, #bfbfbf)' }} />}
          placeholder="搜索会议..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          allowClear
          size="small"
        />
      </div>

      <div className="meeting-sidebar-list-container">
        {filteredMeetings.length === 0 ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={
              search ? '没有匹配的会议' : loading ? '加载中...' : '暂无会议'
            }
            style={{ padding: '24px 0' }}
          />
        ) : (
          <List
            dataSource={filteredMeetings}
            split={false}
            renderItem={(m: MeetingListItem) => {
              const isActive = m.meeting_id === meetingId
              const displayStatus = m.is_running
                ? 'running'
                : m.status === 'aborted'
                  ? 'aborted'
                  : m.status
              return (
                <List.Item
                  className={`meeting-sidebar-item${isActive ? ' meeting-sidebar-item--active' : ''} meeting-sidebar-item--${displayStatus}`}
                  onClick={() => handleSelect(m.meeting_id)}
                  style={{ padding: '8px 12px', cursor: 'pointer' }}
                >
                  <div className="meeting-sidebar-item-content">
                    <div className="meeting-sidebar-item-top" style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 2 }}>
                      <span
                        className="meeting-sidebar-item-topic"
                        title={m.topic}
                        style={{ fontSize: 12, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                      >
                        {m.topic || '(未命名会议)'}
                      </span>
                      {m.is_running && (
                        <Tag color="processing" style={{ fontSize: 10, lineHeight: '16px', padding: '0 4px', margin: 0 }}>
                          进行中
                        </Tag>
                      )}
                      {!m.is_running && m.status === 'done' && (
                        <Tag color="success" style={{ fontSize: 10, lineHeight: '16px', padding: '0 4px', margin: 0 }}>
                          已完成
                        </Tag>
                      )}
                      {!m.is_running && m.status === 'aborted' && (
                        <Tag color="default" style={{ fontSize: 10, lineHeight: '16px', padding: '0 4px', margin: 0 }}>
                          已终止
                        </Tag>
                      )}
                      {!m.is_running && m.status === 'failed' && (
                        <Tag color="error" style={{ fontSize: 10, lineHeight: '16px', padding: '0 4px', margin: 0 }}>
                          失败
                        </Tag>
                      )}
                    </div>
                    <div className="meeting-sidebar-item-meta" style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 11, color: 'var(--text-tertiary, #bfbfbf)' }}>
                      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 2 }}>
                        <ClockCircleOutlined style={{ fontSize: 10 }} />
                        {getTimeAgo(m.updated_at || m.created_at)}
                      </span>
                      <span style={{ fontFamily: 'monospace', fontSize: 10, opacity: 0.7 }}>
                        {m.meeting_id.slice(-8)}
                      </span>
                      {!isActive && (
                        <Popconfirm
                          title={
                            <div style={{ width: 200 }}>
                              <div style={{ marginBottom: 6 }}><strong>删除此会议？</strong></div>
                              <Radio.Group size="small" value={deleteMode} onChange={(e) => setDeleteMode(e.target.value)}>
                                <Radio value="soft">软删除</Radio>
                                <Radio value="hard">永久删除</Radio>
                              </Radio.Group>
                            </div>
                          }
                          onConfirm={(e) => handleDelete(m.meeting_id, e as unknown as React.MouseEvent)}
                          okText="删除"
                          cancelText="取消"
                          okButtonProps={{ danger: true, size: 'small' }}
                          cancelButtonProps={{ size: 'small' }}
                          placement="right"
                        >
                          <button
                            className="meeting-sidebar-item-delete"
                            onClick={(e) => e.stopPropagation()}
                            title="删除会议"
                            style={{
                              marginLeft: 'auto',
                              background: 'none',
                              border: 'none',
                              color: 'var(--text-tertiary, #bfbfbf)',
                              cursor: 'pointer',
                              padding: 2,
                              fontSize: 11,
                            }}
                          >
                            删除
                          </button>
                        </Popconfirm>
                      )}
                    </div>
                  </div>
                </List.Item>
              )
            }}
          />
        )}
      </div>
    </aside>
  )
}
