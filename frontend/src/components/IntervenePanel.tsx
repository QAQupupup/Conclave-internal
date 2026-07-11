// 用户介入对话面板：用户 ↔ 主持人 1v1 私密对话
// 使用 AntD List + Input.TextArea + Button + Empty + Typography + Card
import { useState, useRef, useEffect, useCallback } from 'react'
import { Input, Button, Empty, Typography, Card, Space } from 'antd'
import { SendOutlined, MessageOutlined, CloseOutlined } from '@ant-design/icons'
import { useMeeting } from '../store/MeetingContext.tsx'
import type { InterventionMessage } from '../types/events.ts'

const { Text } = Typography

interface IntervenePanelProps {
  onClose: () => void
}

export function IntervenePanel({ onClose }: IntervenePanelProps) {
  const { store, meetingId, sendIntervention } = useMeeting()
  const [input, setInput] = useState('')
  const [replyTo, setReplyTo] = useState<InterventionMessage | null>(null)
  const [sending, setSending] = useState(false)
  const listRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<import('antd/es/input/TextArea').TextAreaRef>(null)
  const [optimisticMessages, setOptimisticMessages] = useState<InterventionMessage[]>([])

  const serverMessages: InterventionMessage[] = store.meeting?.intervention_messages ?? []
  const messages: InterventionMessage[] = (() => {
    const serverIds = new Set(serverMessages.map(m => m.id))
    const pending = optimisticMessages.filter(m => !serverIds.has(m.id))
    return [...serverMessages, ...pending]
  })()

  useEffect(() => {
    if (listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight
    }
  }, [messages])

  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  const handleSend = useCallback(async () => {
    const text = input.trim()
    if (!text || !meetingId || sending) return

    const optimisticId = `iv-local-${Date.now()}`
    const optimisticMsg: InterventionMessage = {
      id: optimisticId,
      sender: 'user',
      content: text,
      reply_to_id: replyTo?.id,
      timestamp: new Date().toISOString(),
      processed: false,
    }
    setOptimisticMessages(prev => [...prev, optimisticMsg])
    setInput('')
    setReplyTo(null)
    setSending(true)

    try {
      await sendIntervention(meetingId, text, replyTo?.id)
      setOptimisticMessages(prev => prev.filter(m => m.id !== optimisticId))
    } catch (err) {
      console.error('介入消息发送失败:', err)
      setOptimisticMessages(prev => prev.filter(m => m.id !== optimisticId))
    } finally {
      setSending(false)
    }
  }, [input, meetingId, sending, sendIntervention, replyTo])

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }, [handleSend])

  const handleReply = (msg: InterventionMessage) => {
    setReplyTo(msg)
    inputRef.current?.focus()
  }

  const cancelReply = () => setReplyTo(null)

  const formatTime = (ts: string) => {
    try {
      const d = new Date(ts)
      return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
    } catch {
      return ''
    }
  }

  return (
    <div className="intervene-panel" style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* 头部 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '12px 16px', borderBottom: '1px solid var(--border-color, #e5e7eb)' }}>
        <Space>
          <MessageOutlined />
          <Text strong>介入对话</Text>
          <Text type="secondary" style={{ fontSize: 12 }}>私密 · 仅主持人可见</Text>
        </Space>
        <Button type="text" size="small" icon={<CloseOutlined />} onClick={onClose} />
      </div>

      {/* 消息列表 */}
      <div ref={listRef} style={{ flex: 1, overflowY: 'auto', padding: 16 }}>
        {messages.length === 0 ? (
          <Empty
            description={
              <div>
                <Text type="secondary">向主持人发送私密消息</Text>
                <br />
                <Text type="secondary" style={{ fontSize: 12 }}>你的消息不会出现在 Agent 聊天流中</Text>
              </div>
            }
            image={<MessageOutlined style={{ fontSize: 32, color: '#d1d5db' }} />}
            style={{ marginTop: 60 }}
          />
        ) : (
          <Space direction="vertical" style={{ width: '100%' }} size={8}>
            {messages.map((msg) => {
              const isUser = msg.sender === 'user'
              const repliedMsg = msg.reply_to_id
                ? messages.find(m => m.id === msg.reply_to_id)
                : null
              return (
                <Card
                  key={msg.id}
                  size="small"
                  style={{
                    background: isUser ? 'var(--accent-bg, #eef2ff)' : 'var(--bg-secondary, #f9fafb)',
                    marginLeft: isUser ? 40 : 0,
                    marginRight: isUser ? 0 : 40,
                  }}
                >
                  {repliedMsg && (
                    <div style={{ fontSize: 12, color: 'var(--text-secondary, #6b7280)', marginBottom: 4, padding: '4px 8px', background: 'var(--bg-tertiary, #f3f4f6)', borderRadius: 4 }}>
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        回复 {repliedMsg.sender === 'user' ? '你' : '主持人'}：{repliedMsg.content.slice(0, 80)}
                        {repliedMsg.content.length > 80 ? '...' : ''}
                      </Text>
                    </div>
                  )}
                  <div style={{ marginBottom: 4 }}>
                    <Text>{msg.content}</Text>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <Text type="secondary" style={{ fontSize: 12 }}>{formatTime(msg.timestamp)}</Text>
                    {!isUser && (
                      <Button type="link" size="small" onClick={() => handleReply(msg)} style={{ padding: 0, fontSize: 12 }}>
                        回复
                      </Button>
                    )}
                  </div>
                </Card>
              )
            })}
          </Space>
        )}
      </div>

      {/* 回复预览 */}
      {replyTo && (
        <div style={{ padding: '8px 16px', borderTop: '1px solid var(--border-color, #e5e7eb)', background: 'var(--bg-secondary, #f9fafb)', display: 'flex', alignItems: 'center', gap: 8 }}>
          <Text type="secondary" style={{ fontSize: 12 }}>
            回复 {replyTo.sender === 'user' ? '自己' : '主持人'}：
          </Text>
          <Text type="secondary" ellipsis style={{ flex: 1, fontSize: 12 }}>
            {replyTo.content.slice(0, 60)}{replyTo.content.length > 60 ? '...' : ''}
          </Text>
          <Button type="text" size="small" icon={<CloseOutlined />} onClick={cancelReply} />
        </div>
      )}

      {/* 输入框 */}
      <div style={{ padding: '12px 16px', borderTop: '1px solid var(--border-color, #e5e7eb)', display: 'flex', gap: 8 }}>
        <Input.TextArea
          ref={inputRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="向主持人发送消息... (Enter 发送)"
          autoSize={{ minRows: 2, maxRows: 4 }}
          disabled={sending}
          style={{ flex: 1 }}
        />
        <Button
          type="primary"
          icon={<SendOutlined />}
          onClick={handleSend}
          loading={sending}
          disabled={!input.trim()}
        />
      </div>
    </div>
  )
}
