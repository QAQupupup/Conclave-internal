// 会议控制按钮：暂停 / 恢复 / 终止（带 Popconfirm 确认）
// 按当前会议 status 决定显示哪些按钮
import { useState } from 'react'
import { Button, Space, Popconfirm } from 'antd'
import { PauseCircleOutlined, PlayCircleOutlined, StopOutlined } from '@ant-design/icons'
import { useMeeting } from '../store/MeetingContext.tsx'
import type { ControlRequest } from '../types/events.ts'

export function MeetingControls() {
  const { store, meetingId, controlMeeting } = useMeeting()
  const [loading, setLoading] = useState<string | null>(null)

  const status = store.meeting?.status

  const control = async (signal: ControlRequest['signal']) => {
    if (!meetingId) return
    setLoading(signal)
    try {
      await controlMeeting(meetingId, signal)
    } catch (err) {
      console.error(`会议控制操作 ${signal} 失败:`, err)
    } finally {
      setLoading(null)
    }
  }

  if (status === 'done' || status === 'aborted') return null

  const busy = loading !== null

  return (
    <div className="meeting-controls">
      <Space>
        {status === 'running' && (
          <Button
            icon={<PauseCircleOutlined />}
            onClick={() => void control('pause')}
            loading={loading === 'pause'}
            disabled={busy}
            size="small"
          >
            暂停
          </Button>
        )}
        {status === 'paused' && (
          <Button
            type="primary"
            icon={<PlayCircleOutlined />}
            onClick={() => void control('resume')}
            loading={loading === 'resume'}
            disabled={busy}
            size="small"
          >
            恢复
          </Button>
        )}
        {(status === 'running' || status === 'paused') && (
          <Popconfirm
            title="确认终止会议？"
            description="终止是不可逆操作，会议将永久停止。已生成的产出物和聊天记录会保留。"
            onConfirm={async () => {
              await control('abort')
            }}
            okText="确认终止"
            cancelText="取消"
            okButtonProps={{ danger: true }}
          >
            <Button
              danger
              icon={<StopOutlined />}
              loading={loading === 'abort'}
              disabled={busy}
              size="small"
            >
              终止
            </Button>
          </Popconfirm>
        )}
      </Space>
    </div>
  )
}
