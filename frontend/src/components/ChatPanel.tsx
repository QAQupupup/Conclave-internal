// 左侧聊天流：渲染发言卡片列表，新消息时智能自动滚动 + 阶段分隔线
import { useCallback, useEffect, useRef, useState } from 'react'
import { Button, Typography, Divider, Progress } from 'antd'
import { ArrowDownOutlined, MessageOutlined, LoadingOutlined } from '@ant-design/icons'
import { useMeeting } from '../store/MeetingContext.tsx'
import { MessageCard } from './MessageCard.tsx'
import { STAGE_LABELS } from '../types/events.ts'
import type { MeetingMessage, Stage } from '../types/events.ts'

const { Text } = Typography

interface ChatPanelProps {
  /** 点击证据 ref 时触发，向上传递以定位右侧证据面板 */
  onSelectRef?: (ref: string) => void
}

/** 距底部小于该阈值视为"在底部"，新消息可自动跟随 */
const BOTTOM_THRESHOLD = 50
/** 快速消息间隔阈值(ms)：间隔小于此值时用 instant 滚动，避免 smooth 动画堆叠抖动 */
const RAPID_INTERVAL = 300

export function ChatPanel({ onSelectRef }: ChatPanelProps) {
  const { store } = useMeeting()
  const messages = store.meeting?.messages ?? []
  const stage = store.meeting?.stage
  const status = store.meeting?.status
  const produceProgress = store.meeting?.produce_progress
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const [isAtBottom, setIsAtBottom] = useState(true)
  const [showNewMsg, setShowNewMsg] = useState(false)
  // 记录用户已"看过"的消息数，用于判断新消息是否到来
  const lastSeenCountRef = useRef(0)
  // 记录上次滚动时间戳：快速连续消息时用 instant 而非 smooth
  const lastScrollAtRef = useRef(0)

  /** 滚动到底部并重置提示状态 */
  const scrollToBottom = useCallback((behavior: ScrollBehavior = 'smooth') => {
    const el = scrollRef.current
    if (!el) return
    el.scrollTo({ top: el.scrollHeight, behavior })
    setIsAtBottom(true)
    setShowNewMsg(false)
    lastSeenCountRef.current = messages.length
    lastScrollAtRef.current = Date.now()
  }, [messages.length])

  /** 监听滚动位置，更新 isAtBottom，到底时同步已看消息数 */
  const handleScroll = useCallback(() => {
    const el = scrollRef.current
    if (!el) return
    const distance = el.scrollHeight - el.scrollTop - el.clientHeight
    const atBottom = distance < BOTTOM_THRESHOLD
    setIsAtBottom(atBottom)
    if (atBottom) {
      setShowNewMsg(false)
      lastSeenCountRef.current = messages.length
    }
  }, [messages.length])

  // 新消息到达：在底部则跟随，否则显示"新消息"提示
  // 快速连续消息(间隔<300ms)用 instant 滚动，避免 smooth 动画堆叠抖动
  useEffect(() => {
    if (messages.length === 0) return
    if (isAtBottom) {
      const sinceLast = Date.now() - lastScrollAtRef.current
      const behavior: ScrollBehavior = sinceLast < RAPID_INTERVAL ? 'auto' : 'smooth'
      scrollToBottom(behavior)
    } else if (messages.length > lastSeenCountRef.current) {
      setShowNewMsg(true)
    }
  }, [messages.length, isAtBottom, scrollToBottom])

  return (
    <section className="panel chat-panel">
      <div className="panel-title">聊天流</div>
      <div className="chat-list" ref={scrollRef} onScroll={handleScroll}>
        {messages.length === 0 && (
          <div className="empty-hint" style={{ textAlign: 'center', padding: '40px 20px' }}>
            <MessageOutlined style={{ fontSize: 32, color: '#d1d5db', marginBottom: 12 }} />
            <Text type="secondary">暂无发言，创建会议并运行后，agent 发言将在此实时展示。</Text>
          </div>
        )}
        {messages.map((m, i) => (
          <MessageItem
            key={m.id}
            message={m}
            prevStage={i > 0 ? messages[i - 1].stage : null}
            onSelectRef={onSelectRef}
          />
        ))}
        {/* Produce 阶段进度条 */}
        {stage === 'produce' && status === 'running' && produceProgress && produceProgress.percent < 100 && (
          <div style={{ padding: '12px 16px', borderTop: '1px solid #f0f0f0', background: '#fafafa' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
              <LoadingOutlined style={{ color: '#1890ff' }} />
              <Text strong style={{ fontSize: 13 }}>{produceProgress.message}</Text>
            </div>
            <Progress
              percent={produceProgress.percent}
              size="small"
              status="active"
              strokeColor={{
                '0%': '#1890ff',
                '100%': '#52c41a',
              }}
            />
          </div>
        )}
      </div>
      {showNewMsg && (
        <Button
          type="primary"
          shape="round"
          size="small"
          icon={<ArrowDownOutlined />}
          className="new-msg-btn"
          onClick={() => scrollToBottom('smooth')}
          style={{ position: 'absolute', bottom: 60, left: '50%', transform: 'translateX(-50%)', zIndex: 10, boxShadow: '0 2px 8px rgba(0,0,0,0.15)' }}
        >
          新消息
        </Button>
      )}
    </section>
  )
}

/** 单条消息 + 可选的阶段分隔线 */
function MessageItem({
  message,
  prevStage,
  onSelectRef,
}: {
  message: MeetingMessage
  prevStage: Stage | null
  onSelectRef?: (ref: string) => void
}) {
  // 与上一条消息阶段不同时，在两者之间插入阶段分隔线
  const showSeparator = prevStage !== null && prevStage !== message.stage
  return (
    <div className="message-wrap">
      {showSeparator && (
        <Divider style={{ margin: '12px 0' }}>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {STAGE_LABELS[message.stage] ?? message.stage}
          </Text>
        </Divider>
      )}
      <MessageCard message={message} onSelectRef={onSelectRef} />
    </div>
  )
}
