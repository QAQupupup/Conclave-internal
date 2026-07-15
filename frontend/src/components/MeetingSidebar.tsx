// 会议列表侧边栏：展示所有历史会议，支持切换 / 新建 / 删除 / 折叠
// 使用 AntD List + Button + Popconfirm + Badge + Tag + Typography + Tooltip + Input
// 删除按钮 hover 时才显示，避免图标杂乱
import { useState, useEffect, useCallback } from 'react'
import { Button, List, Badge, Tag, Typography, Tooltip, Input, Popconfirm, Radio, Empty } from 'antd'
import {
  PlusOutlined, ReloadOutlined, DeleteOutlined, MenuFoldOutlined, MenuUnfoldOutlined,
  SearchOutlined, ThunderboltOutlined, ScheduleOutlined, CheckCircleOutlined,
} from '@ant-design/icons'
import { listMeetings, deleteMeeting } from '../lib/api.ts'
import { useMeeting } from '../store/MeetingContext.tsx'
import { usePersistentState } from '../hooks/usePersistentState.ts'
import { STAGE_LABELS, getMeetingStatusInfo } from '../constants.ts'
import { clearLogs } from '../hooks/useMeetingLogs.ts'
import { navigateWithQuery } from '../lib/router.ts'

const { Text } = Typography

interface MeetingListItem {
  meeting_id: string
  topic: string
  stage: string
  status: string
  created_at?: string
  is_running?: boolean
  flow_plan?: string
}

interface MeetingSidebarProps {
  /** 收起整个侧边栏的回调 */
  onCollapseSidebar?: () => void
}

export function MeetingSidebar({ onCollapseSidebar }: MeetingSidebarProps) {
  const { meetingId, selectMeeting } = useMeeting()
  const [meetings, setMeetings] = useState<MeetingListItem[]>([])
  const [concurrentLimit, setConcurrentLimit] = useState(0)
  const [runningCount, setRunningCount] = useState(0)
  const [loading, setLoading] = useState(false)
  const [listCollapsed, setListCollapsed] = usePersistentState<boolean>(
    'conclave-meeting-list-collapsed',
    false,
  )
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [deleteMode, setDeleteMode] = useState<'soft' | 'hard'>('soft')
  const [hoveredId, setHoveredId] = useState<string | null>(null)

  // 相对时间显示
  const relativeTime = (dateStr?: string) => {
    if (!dateStr) return ''
    const d = new Date(dateStr)
    const now = new Date()
    const diffMs = now.getTime() - d.getTime()
    const diffMin = Math.floor(diffMs / 60000)
    if (diffMin < 1) return '刚刚'
    if (diffMin < 60) return `${diffMin}分钟前`
    const diffHour = Math.floor(diffMin / 60)
    if (diffHour < 24) return `${diffHour}小时前`
    const diffDay = Math.floor(diffHour / 24)
    if (diffDay < 7) return `${diffDay}天前`
    return d.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' })
  }

  // 搜索过滤后的会议列表
  const filteredMeetings = searchQuery.trim()
    ? meetings.filter(m => m.topic.toLowerCase().includes(searchQuery.toLowerCase()) || m.meeting_id.includes(searchQuery))
    : meetings

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const data = await listMeetings()
      const running = data.meetings.filter((m: MeetingListItem) => m.is_running)
      const others = data.meetings.filter((m: MeetingListItem) => !m.is_running)
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
    const timer = setInterval(refresh, 5000)
    return () => clearInterval(timer)
  }, [refresh])

  const statusLabel = (status: string, stage: string) => {
    const stageLabel = STAGE_LABELS[stage as keyof typeof STAGE_LABELS] ?? stage
    return getMeetingStatusInfo(status, stageLabel)
  }

  const handleDelete = useCallback(
    async (id: string) => {
      setDeletingId(id)
      try {
        await deleteMeeting(id, deleteMode)
        clearLogs(id)
        if (id === meetingId) {
          selectMeeting(null)
        }
        await refresh()
      } catch (err) {
        console.error('删除会议失败:', err)
      } finally {
        setDeletingId(null)
      }
    },
    [meetingId, selectMeeting, refresh, deleteMode],
  )

  // 当前正在操作删除的会议ID（用于控制Popconfirm显示时重置模式）
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null)

  // 打开删除确认时重置为软删除（防止模式粘滞导致误删）
  const handleDeletePopconfirmOpenChange = (open: boolean, id: string) => {
    if (open) {
      setDeleteMode('soft')
      setDeleteConfirmId(id)
    } else {
      setDeleteConfirmId(null)
    }
  }

  const deletePopconfirmTitle = (
    <div style={{ width: 220 }}>
      <div style={{ marginBottom: 8 }}>
        <Text strong>确认删除此会议？</Text>
      </div>
      <Radio.Group
        size="small"
        value={deleteMode}
        onChange={(e) => setDeleteMode(e.target.value)}
      >
        <Radio value="soft">软删除（保留数据）</Radio>
        <Radio value="hard">永久删除</Radio>
      </Radio.Group>
    </div>
  )

  return (
    <div className="meeting-sidebar">
      <div className="meeting-sidebar-toolbar">
        <Button type="primary" icon={<PlusOutlined />} size="small" onClick={() => {
          selectMeeting(null)
          navigateWithQuery('/board', { create: '1' })
        }}>
          新建会议
        </Button>
        <div className="meeting-sidebar-spacer" />
        <Tooltip title="刷新">
          <Button type="text" size="small" icon={<ReloadOutlined spin={loading} />} onClick={refresh} />
        </Tooltip>
        {onCollapseSidebar && (
          <Tooltip title="收起会议列表（专注内容）">
            <Button type="text" size="small" icon={<MenuFoldOutlined />} onClick={onCollapseSidebar} />
          </Tooltip>
        )}
      </div>

      {/* 历史会议标题 + 搜索 */}
      <div className="meeting-sidebar-search-section">
        <div
          className="meeting-sidebar-toggle-row"
          onClick={() => setListCollapsed(v => !v)}
        >
          <Button type="text" size="small" icon={listCollapsed ? <MenuFoldOutlined /> : <MenuUnfoldOutlined />} />
          <Text strong className="meeting-sidebar-history-title">历史会议 ({filteredMeetings.length})</Text>
          {runningCount > 0 && <Badge count={runningCount} className="meeting-sidebar-running-badge" />}
        </div>
        {!listCollapsed && (
          <Input
            size="small"
            placeholder="搜索会议..."
            prefix={<SearchOutlined />}
            allowClear
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="meeting-sidebar-search-input"
          />
        )}
      </div>

      {!listCollapsed && (
        <div className="meeting-sidebar-list-container">
          {filteredMeetings.length === 0 ? (
            <Empty description={searchQuery ? '无匹配会议' : '暂无会议'} image={Empty.PRESENTED_IMAGE_SIMPLE} />
          ) : (
            <List
              dataSource={filteredMeetings}
              renderItem={(m) => {
                const sl = statusLabel(m.status, m.stage)
                const isActive = m.meeting_id === meetingId
                const isDeleting = deletingId === m.meeting_id
                const isHovered = hoveredId === m.meeting_id
                return (
                  <List.Item
                    key={m.meeting_id}
                    onClick={() => !isDeleting && selectMeeting(m.meeting_id)}
                    onMouseEnter={() => setHoveredId(m.meeting_id)}
                    onMouseLeave={() => setHoveredId(null)}
                    style={{
                      cursor: 'pointer',
                      background: isActive ? 'var(--accent-light, #eef2ff)' : 'transparent',
                      borderRadius: 6,
                      padding: '8px 10px',
                      marginBottom: 2,
                      border: isActive ? '1px solid var(--accent, #4f46e5)' : '1px solid transparent',
                      position: 'relative',
                      transition: 'background 0.15s ease, border-color 0.15s ease',
                    }}
                  >
                    <List.Item.Meta
                      title={
                        <div style={{ display: 'flex', alignItems: 'center', gap: 4, paddingRight: 28 }}>
                          {m.is_running && <Badge status="processing" style={{ flexShrink: 0 }} />}
                          <Text ellipsis className="meeting-sidebar-item-title" style={{ flex: 1, minWidth: 0 }}>
                            {m.topic || '(无议题)'}
                          </Text>
                        </div>
                      }
                      description={
                        <div className="meeting-sidebar-item-desc" style={{ display: 'flex', alignItems: 'center', gap: 4, flexWrap: 'wrap', lineHeight: '20px' }}>
                          <Tag
                            color={sl.cls === 'ok' ? 'green' : sl.cls === 'running' ? 'blue' : 'default'}
                            className="meeting-sidebar-status-tag"
                            style={{ margin: 0, lineHeight: '18px' }}
                          >
                            {sl.text}
                          </Tag>
                          {(m.flow_plan === 'instant' || m.flow_plan === 'fast' || m.flow_plan === 'fast_path' || m.flow_plan === 'simple') && (
                            <Tag color="blue" className="meeting-sidebar-flow-tag" icon={<ThunderboltOutlined />} style={{ margin: 0, lineHeight: '18px' }}>
                              Instant
                            </Tag>
                          )}
                          {m.flow_plan === 'plan' && (
                            <Tag color="purple" className="meeting-sidebar-flow-tag" icon={<ScheduleOutlined />} style={{ margin: 0, lineHeight: '18px' }}>
                              Plan
                            </Tag>
                          )}
                          {(m.flow_plan === 'standard' || m.flow_plan === 'deep_think' || m.flow_plan === 'full' || !m.flow_plan) && (
                            <Tag color="geekblue" className="meeting-sidebar-flow-tag" icon={<CheckCircleOutlined />} style={{ margin: 0, lineHeight: '18px' }}>
                              Standard
                            </Tag>
                          )}
                          <Text type="secondary" className="meeting-sidebar-time-text" style={{ fontSize: 11, marginLeft: 'auto' }}>
                            {relativeTime(m.created_at)}
                          </Text>
                        </div>
                      }
                    />
                    {/* 删除按钮：hover 或正在删除时显示 */}
                    {(isHovered || isDeleting) && !m.is_running && (
                      <Popconfirm
                        title={deletePopconfirmTitle}
                        open={deleteConfirmId === m.meeting_id}
                        onOpenChange={(open) => handleDeletePopconfirmOpenChange(open, m.meeting_id)}
                        onConfirm={(e) => {
                          e?.stopPropagation()
                          handleDelete(m.meeting_id)
                        }}
                        onCancel={(e) => e?.stopPropagation()}
                        okText="确认删除"
                        cancelText="取消"
                        okButtonProps={{ danger: true, size: 'small', loading: isDeleting }}
                        cancelButtonProps={{ size: 'small' }}
                        placement="left"
                      >
                        <Button
                          type="text"
                          size="small"
                          danger
                          icon={<DeleteOutlined />}
                          disabled={m.is_running || isDeleting}
                          onClick={(e) => e.stopPropagation()}
                          style={{
                            position: 'absolute',
                            right: 6,
                            top: '50%',
                            transform: 'translateY(-50%)',
                            padding: '0 4px',
                            height: 24,
                          }}
                          title="删除会议"
                        />
                      </Popconfirm>
                    )}
                  </List.Item>
                )
              }}
            />
          )}
        </div>
      )}

      <div className="meeting-sidebar-footer">
        <Text type="secondary" className="meeting-sidebar-time-text" style={{ fontSize: 11 }}>
          运行中 {runningCount} / 上限 {concurrentLimit}
        </Text>
      </div>
    </div>
  )
}
