// 会议控制按钮：暂停 / 恢复 / 终止（带 Popconfirm 确认）
// 按当前会议 status 决定显示哪些按钮；会议结束后显示返回引导
import { useState } from 'react'
import { Button, Space, Popconfirm } from 'antd'
import {
  PauseCircleOutlined,
  PlayCircleOutlined,
  StopOutlined,
  RollbackOutlined,
  FileDoneOutlined,
} from '@ant-design/icons'
import { useMeeting } from '../store/MeetingContext.tsx'
import type { ControlRequest } from '../types/events.ts'

interface MeetingControlsProps {
  onOpenReport?: () => void
  onBackToBoard?: () => void
}

export function MeetingControls({ onOpenReport, onBackToBoard }: MeetingControlsProps) {
  const { store, meetingId, controlMeeting, selectMeeting } = useMeeting()
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

  const handleBackToBoard = () => {
    if (onBackToBoard) {
      onBackToBoard()
    } else {
      selectMeeting(null)
    }
  }

  // 会议结束/失败/终止状态：显示结束状态提示和操作按钮
  if (status === 'done' || status === 'aborted' || status === 'failed') {
    const statusLabel = status === 'done' ? '会议已完成' : status === 'failed' ? '会议已失败' : '会议已终止'
    return (
      <div className="meeting-controls meeting-controls--finished">
        <Space size="small">
          <span style={{ fontSize: 12, color: 'var(--text-secondary, #8c8c8c)' }}>
            {statusLabel}
          </span>
          {onOpenReport && (
            <Button
              size="small"
              icon={<FileDoneOutlined />}
              onClick={onOpenReport}
            >
              查看报告
            </Button>
          )}
          <Button
            type="primary"
            size="small"
            icon={<RollbackOutlined />}
            onClick={handleBackToBoard}
          >
            返回看板
          </Button>
        </Space>
      </div>
    )
  }

  const busy = loading !== null

  return (
    <div className="meeting-controls">
      <Space size="small">
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
        {/* 运行中/暂停状态也提供返回看板入口 */}
        <Button
          size="small"
          icon={<RollbackOutlined />}
          onClick={handleBackToBoard}
          title="返回会议看板（会议继续在后台运行）"
        >
          返回看板
        </Button>
      </Space>
    </div>
  )
}
