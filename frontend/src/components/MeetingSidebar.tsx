// 会议列表侧边栏：展示所有历史会议，支持切换 / 新建 / 删除 / 折叠
// 使用 AntD List + Button + Popconfirm + Badge + Tag + Typography + Radio + Space
import { useState, useEffect, useCallback } from 'react'
import { Button, List, Badge, Tag, Typography, Radio, Space, Empty } from 'antd'
import { PlusOutlined, ReloadOutlined, DeleteOutlined, MenuFoldOutlined, MenuUnfoldOutlined } from '@ant-design/icons'
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
}

export function MeetingSidebar() {
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
    <div className="meeting-sidebar" style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '12px 16px', borderBottom: '1px solid var(--border-color, #e5e7eb)' }}>
        <Text strong>会议列表</Text>
        <Button type="text" size="small" icon={<ReloadOutlined spin={loading} />} onClick={refresh} />
      </div>

      <div style={{ padding: '12px 16px' }}>
        <Button type="primary" icon={<PlusOutlined />} block onClick={() => selectMeeting(null)}>
          新建会议
        </Button>
      </div>

      <div style={{ padding: '0 16px' }}>
        <div
          style={{ display: 'flex', alignItems: 'center', cursor: 'pointer', padding: '8px 0' }}
          onClick={() => setListCollapsed(v => !v)}
        >
          <Button type="text" size="small" icon={listCollapsed ? <MenuFoldOutlined /> : <MenuUnfoldOutlined />} />
          <Text strong style={{ flex: 1 }}>历史会议 ({meetings.length})</Text>
          {runningCount > 0 && <Badge count={runningCount} style={{ backgroundColor: '#52c41a' }} />}
        </div>
      </div>

      {!listCollapsed && (
        <div style={{ flex: 1, overflowY: 'auto', padding: '0 8px' }}>
          {meetings.length === 0 ? (
            <Empty description="暂无会议" image={Empty.PRESENTED_IMAGE_SIMPLE} />
          ) : (
            <List
              dataSource={meetings}
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
                      padding: '8px 12px',
                      marginBottom: 4,
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
                        <Space>
                          {m.is_running && <Badge status="processing" />}
                          <Text ellipsis style={{ maxWidth: 160 }}>{m.topic || '(无议题)'}</Text>
                        </Space>
                      }
                      description={
                        <Space>
                          <Tag color={sl.cls === 'ok' ? 'green' : sl.cls === 'running' ? 'blue' : 'default'} style={{ margin: 0 }}>
                            {sl.text}
                          </Tag>
                          <Text type="secondary" style={{ fontSize: 12 }}>{m.meeting_id.slice(-8)}</Text>
                        </Space>
                      }
                    />
                    {isPendingDelete && (
                      <div onClick={(e) => e.stopPropagation()} style={{ padding: 8, background: 'var(--bg-secondary, #fafafa)', borderRadius: 4, marginTop: 8, width: '100%' }}>
                        <Text strong style={{ fontSize: 12 }}>确认删除？</Text>
                        <Radio.Group
                          size="small"
                          value={currentDeleteMode}
                          onChange={(e) => setPendingDelete({ id: m.meeting_id, mode: e.target.value })}
                          style={{ display: 'flex', flexDirection: 'column', gap: 4, margin: '8px 0' }}
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

      <div style={{ padding: '12px 16px', borderTop: '1px solid var(--border-color, #e5e7eb)', textAlign: 'center' }}>
        <Text type="secondary" style={{ fontSize: 12 }}>
          运行中 {runningCount} / 上限 {concurrentLimit}
        </Text>
      </div>
    </div>
  )
}
