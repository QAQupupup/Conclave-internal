// 左侧聊天流：渲染发言卡片列表，新消息时智能自动滚动 + 阶段分隔线
// 当会议走 Fast Path（无 agent 发言但有直接答案）时，展示答案卡片
import { useCallback, useEffect, useRef, useState } from 'react'
import { Button, Typography, Divider, Progress, Card, Tag } from 'antd'
import { ArrowDownOutlined, MessageOutlined, LoadingOutlined, ThunderboltOutlined, ClockCircleOutlined } from '@ant-design/icons'
import { useMeeting } from '../store/MeetingContext.tsx'
import { MessageCard } from './MessageCard.tsx'
import { STAGE_LABELS } from '../types/events.ts'
import type { MeetingMessage, Stage } from '../types/events.ts'

const { Text, Paragraph } = Typography

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
  const meeting = store.meeting
  const messages = meeting?.messages ?? []
  const stage = meeting?.stage
  const status = meeting?.status
  const artifact = meeting?.artifact
  const produceProgress = meeting?.produce_progress
  // Fast Path：无 agent 发言，但有直接答案
  const isFastPath = artifact?.flow === 'fast_path' && !!artifact?.answer && messages.length === 0
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
        {messages.length === 0 && !isFastPath && (
          <div className="empty-hint chat-panel-empty-hint">
            <MessageOutlined className="chat-panel-empty-icon" />
            <Text type="secondary">暂无发言，创建会议并运行后，agent 发言将在此实时展示。</Text>
          </div>
        )}
        {isFastPath && artifact && (
          <div className="chat-panel-fast-path">
            <Card
              className="fast-path-card"
              title={
                <div className="fast-path-card-header">
                  <ThunderboltOutlined className="fast-path-icon" />
                  <span>{artifact.title || '快速回答'}</span>
                </div>
              }
              extra={
                <div className="fast-path-card-extra">
                  <Tag color="blue" icon={<ThunderboltOutlined />}>Fast Path</Tag>
                  {artifact.latency_ms != null && (
                    <Tag icon={<ClockCircleOutlined />}>
                      {(artifact.latency_ms / 1000).toFixed(1)}s
                    </Tag>
                  )}
                </div>
              }
            >
              <Paragraph className="fast-path-answer">
                {artifact.answer}
              </Paragraph>
            </Card>
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
          <div className="chat-panel-progress-wrap">
            <div className="chat-panel-progress-head">
              <LoadingOutlined className="chat-panel-progress-icon" />
              <Text strong className="chat-panel-progress-text">{produceProgress.message}</Text>
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
          className="new-msg-btn chat-panel-new-msg-btn"
          onClick={() => scrollToBottom('smooth')}
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
        <Divider className="chat-panel-divider">
          <Text type="secondary" className="chat-panel-divider-text">
            {STAGE_LABELS[message.stage] ?? message.stage}
          </Text>
        </Divider>
      )}
      <MessageCard message={message} onSelectRef={onSelectRef} />
    </div>
  )
}
