// 会议控制按钮：暂停 / 恢复 / 终止 / 删除 / 返回看板
// 按当前会议 status 决定显示哪些按钮
import { useState } from 'react'
import { Button, Space, Popconfirm, Radio, message } from 'antd'
import {
  PauseCircleOutlined,
  PlayCircleOutlined,
  StopOutlined,
  RollbackOutlined,
  FileDoneOutlined,
  DeleteOutlined,
} from '@ant-design/icons'
import { useMeeting } from '../store/MeetingContext.tsx'
import { deleteMeeting } from '../lib/api.ts'
import { clearLogs } from '../hooks/useMeetingLogs.ts'
import { navigate } from '../lib/router.ts'
import type { ControlRequest } from '../types/events.ts'

interface MeetingControlsProps {
  onOpenReport?: () => void
  onBackToBoard?: () => void
}

export function MeetingControls({ onOpenReport, onBackToBoard }: MeetingControlsProps) {
  const { store, meetingId, controlMeeting, selectMeeting } = useMeeting()
  const [loading, setLoading] = useState<string | null>(null)
  const [deleteMode, setDeleteMode] = useState<'soft' | 'hard'>('soft')

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
      navigate('/board')
    }
  }

  const handleDelete = async () => {
    if (!meetingId) return
    setLoading('delete')
    try {
      await deleteMeeting(meetingId, deleteMode)
      clearLogs(meetingId)
      message.success(deleteMode === 'hard' ? '会议已永久删除' : '会议已删除')
      selectMeeting(null)
      navigate('/board')
    } catch (err) {
      console.error('删除会议失败:', err)
      message.error('删除会议失败: ' + (err instanceof Error ? err.message : String(err)))
    } finally {
      setLoading(null)
    }
  }

  const deletePopconfirmTitle = (
    <div style={{ width: 220 }}>
      <div style={{ marginBottom: 8 }}>
        <strong>确认删除此会议？</strong>
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
          <Popconfirm
            title={deletePopconfirmTitle}
            onConfirm={handleDelete}
            okText="确认删除"
            cancelText="取消"
            okButtonProps={{ danger: true, size: 'small', loading: loading === 'delete' }}
            cancelButtonProps={{ size: 'small' }}
            placement="bottomRight"
          >
            <Button
              size="small"
              danger
              icon={<DeleteOutlined />}
              loading={loading === 'delete'}
            >
              删除会议
            </Button>
          </Popconfirm>
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

  // 运行中/暂停/待启动状态
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
        {/* 删除会议（任意状态下都可用） */}
        <Popconfirm
          title={deletePopconfirmTitle}
          onConfirm={handleDelete}
          okText="确认删除"
          cancelText="取消"
          okButtonProps={{ danger: true, size: 'small', loading: loading === 'delete' }}
          cancelButtonProps={{ size: 'small' }}
          placement="bottomRight"
          description={status === 'running' ? '会议正在运行，删除将强制终止会议并删除相关数据。' : undefined}
        >
          <Button
            size="small"
            danger
            icon={<DeleteOutlined />}
            loading={loading === 'delete'}
            disabled={busy && loading !== 'delete'}
          >
            删除
          </Button>
        </Popconfirm>
        {/* 返回看板（会议继续在后台运行） */}
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
