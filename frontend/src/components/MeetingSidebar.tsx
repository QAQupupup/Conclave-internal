// 会议列表侧边栏：展示所有历史会议，支持切换 / 新建 / 删除 / 折叠
// 使用 AntD List + Button + Popconfirm + Badge + Tag + Typography + Radio + Space
import { useState, useEffect, useCallback } from 'react'
import { Button, List, Badge, Tag, Typography, Radio, Space, Empty, Tooltip, Input } from 'antd'
import {
  PlusOutlined, ReloadOutlined, DeleteOutlined, MenuFoldOutlined, MenuUnfoldOutlined,
  SearchOutlined, ThunderboltOutlined, ScheduleOutlined,
} from '@ant-design/icons'
import { listMeetings, deleteMeeting } from '../lib/api.ts'
import { useMeeting } from '../store/MeetingContext.tsx'
import { usePersistentState } from '../hooks/usePersistentState.ts'
import { STAGE_LABELS, getMeetingStatusInfo } from '../constants.ts'

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
  const [pendingDelete, setPendingDelete] = useState<{ id: string; mode: 'soft' | 'hard' } | null>(null)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [searchQuery, setSearchQuery] = useState('')

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
    const timer = setInterval(refresh, 5000)
    return () => clearInterval(timer)
  }, [refresh])

  const statusLabel = (status: string, stage: string) => {
    const stageLabel = STAGE_LABELS[stage as keyof typeof STAGE_LABELS] ?? stage
    return getMeetingStatusInfo(status, stageLabel)
  }

  const handleDelete = useCallback(
    async (id: string, mode: 'soft' | 'hard') => {
      setDeletingId(id)
      try {
        await deleteMeeting(id, mode)
        if (id === meetingId) {
          selectMeeting(null)
        }
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
      <div className="meeting-sidebar-toolbar">
        <Button type="primary" icon={<PlusOutlined />} size="small" onClick={() => selectMeeting(null)}>
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
        {!listCollapsed && meetings.length > 3 && (
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
                const isPendingDelete = pendingDelete?.id === m.meeting_id
                const isDeleting = deletingId === m.meeting_id
                const currentDeleteMode = pendingDelete?.mode ?? 'soft'
                return (
                  <List.Item
                    key={m.meeting_id}
                    onClick={() => !isPendingDelete && !isDeleting && selectMeeting(m.meeting_id)}
                    style={{
                      cursor: isPendingDelete || isDeleting ? 'default' : 'pointer',
                      background: isActive ? 'var(--accent-bg, #eef2ff)' : isPendingDelete ? '#fff2f0' : 'transparent',
                      borderRadius: 6,
                      padding: '6px 10px',
                      marginBottom: 2,
                      border: isActive ? '1px solid var(--accent-color, #4f46e5)' : '1px solid transparent',
                    }}
                    actions={[
                      <Button
                        key="delete"
                        type="text"
                        size="small"
                        danger
                        icon={<DeleteOutlined />}
                        disabled={m.is_running || isDeleting}
                        onClick={(e) => {
                          e.stopPropagation()
                          setPendingDelete({ id: m.meeting_id, mode: 'soft' })
                        }}
                        title={m.is_running ? '运行中，无法删除' : '删除会议'}
                      />,
                    ]}
                  >
                    <List.Item.Meta
                      title={
                        <Space size={4}>
                          {m.is_running && <Badge status="processing" />}
                          <Text ellipsis className="meeting-sidebar-item-title">{m.topic || '(无议题)'}</Text>
                        </Space>
                      }
                      description={
                        <div className="meeting-sidebar-item-desc">
                          <Tag color={sl.cls === 'ok' ? 'green' : sl.cls === 'running' ? 'blue' : 'default'} className="meeting-sidebar-status-tag">
                            {sl.text}
                          </Tag>
                          {m.flow_plan === 'fast' && (
                            <Tag color="blue" className="meeting-sidebar-flow-tag">
                              <ThunderboltOutlined /> Fast
                            </Tag>
                          )}
                          {m.flow_plan === 'plan' && (
                            <Tag color="purple" className="meeting-sidebar-flow-tag">
                              <ScheduleOutlined /> Plan
                            </Tag>
                          )}
                          <Text type="secondary" className="meeting-sidebar-time-text">{relativeTime(m.created_at)}</Text>
                        </div>
                      }
                    />
                    {isPendingDelete && (
                      <div onClick={(e) => e.stopPropagation()} className="meeting-sidebar-delete-confirm">
                        <Text strong className="meeting-sidebar-delete-confirm-text">确认删除？</Text>
                        <Radio.Group
                          size="small"
                          value={currentDeleteMode}
                          onChange={(e) => setPendingDelete({ id: m.meeting_id, mode: e.target.value })}
                          className="meeting-sidebar-radio-group"
                        >
                          <Radio value="soft">软删除（保留数据）</Radio>
                          <Radio value="hard">永久删除（不可恢复）</Radio>
                        </Radio.Group>
                        <Space>
                          <Button
                            type="primary"
                            danger
                            size="small"
                            loading={isDeleting}
                            onClick={() => handleDelete(m.meeting_id, currentDeleteMode)}
                          >
                            确认删除
                          </Button>
                          <Button size="small" onClick={() => setPendingDelete(null)}>取消</Button>
                        </Space>
                      </div>
                    )}
                  </List.Item>
                )
              }}
            />
          )}
        </div>
      )}

      <div className="meeting-sidebar-footer">
        <Text type="secondary" className="meeting-sidebar-time-text">
          运行中 {runningCount} / 上限 {concurrentLimit}
        </Text>
      </div>
    </div>
  )
}
