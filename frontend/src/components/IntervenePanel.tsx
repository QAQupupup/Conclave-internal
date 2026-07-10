// 用户介入对话面板：用户 ↔ 主持人 1v1 私密对话
// 独立于 Agent 聊天流，通过右侧浮标"介入"展开
import { useState, useRef, useEffect, useCallback } from 'react'
import { useMeeting } from '../store/MeetingContext.tsx'
import type { InterventionMessage } from '../types/events.ts'

interface IntervenePanelProps {
  onClose: () => void
}

export function IntervenePanel({ onClose }: IntervenePanelProps) {
  const { store, meetingId, sendIntervention } = useMeeting()
  const [input, setInput] = useState('')
  const [replyTo, setReplyTo] = useState<InterventionMessage | null>(null)
  const [sending, setSending] = useState(false)
  const listRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  // 乐观更新：发送后立即显示在列表中，避免等待 store 刷新
  const [optimisticMessages, setOptimisticMessages] = useState<InterventionMessage[]>([])

  // 从 store 中读取介入消息（正确路径：store.meeting.intervention_messages）
  const serverMessages: InterventionMessage[] = store.meeting?.intervention_messages ?? []
  // 合并服务端消息 + 乐观更新的本地消息（去重）
  const messages: InterventionMessage[] = (() => {
    const serverIds = new Set(serverMessages.map(m => m.id))
    const pending = optimisticMessages.filter(m => !serverIds.has(m.id))
    return [...serverMessages, ...pending]
  })()

  // 自动滚动到底部
  useEffect(() => {
    if (listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight
    }
  }, [messages])

  // 聚焦输入框
  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  const handleSend = useCallback(async () => {
    const text = input.trim()
    if (!text || !meetingId || sending) return

    // 乐观更新：立即显示用户消息
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
      // 服务端刷新后，移除对应的乐观消息
      setOptimisticMessages(prev => prev.filter(m => m.id !== optimisticId))
    } catch (err) {
      console.error('介入消息发送失败:', err)
      // 发送失败也移除乐观消息（服务端刷新会恢复真实状态）
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
    <div className="intervene-panel">
      {/* 头部 */}
      <div className="intervene-header">
        <div className="intervene-header-title">
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M8 2C4.7 2 2 4.7 2 8c0 1.1.3 2.1.8 3L2 14l3.2-.7C6.1 13.8 7 14 8 14c3.3 0 6-2.7 6-6s-2.7-6-6-6z" />
          </svg>
          <span>介入对话</span>
          <span className="intervene-subtitle">私密 · 仅主持人可见</span>
        </div>
        <button type="button" className="intervene-close-btn" onClick={onClose} title="关闭">
          ×
        </button>
      </div>

      {/* 消息列表 */}
      <div className="intervene-messages" ref={listRef}>
        {messages.length === 0 && (
          <div className="intervene-empty">
            <svg width="32" height="32" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1" opacity="0.3">
              <path d="M8 2C4.7 2 2 4.7 2 8c0 1.1.3 2.1.8 3L2 14l3.2-.7C6.1 13.8 7 14 8 14c3.3 0 6-2.7 6-6s-2.7-6-6-6z" />
            </svg>
            <p>向主持人发送私密消息</p>
            <p className="intervene-empty-hint">你的消息不会出现在 Agent 聊天流中</p>
          </div>
        )}
        {messages.map((msg) => {
          const isUser = msg.sender === 'user'
          const repliedMsg = msg.reply_to_id
            ? messages.find(m => m.id === msg.reply_to_id)
            : null
          return (
            <div
              key={msg.id}
              className={`intervene-msg ${isUser ? 'intervene-msg-user' : 'intervene-msg-moderator'}`}
            >
              {/* 回复引用 */}
              {repliedMsg && (
                <div className="intervene-reply-ref">
                  <span className="intervene-reply-sender">
                    {repliedMsg.sender === 'user' ? '你' : '主持人'}
                  </span>
                  ：{repliedMsg.content.slice(0, 80)}
                  {repliedMsg.content.length > 80 ? '...' : ''}
                </div>
              )}
              <div className="intervene-msg-content">{msg.content}</div>
              <div className="intervene-msg-footer">
                <span className="intervene-msg-time">{formatTime(msg.timestamp)}</span>
                {!isUser && (
                  <button
                    type="button"
                    className="intervene-reply-btn"
                    onClick={() => handleReply(msg)}
                    title="回复"
                  >
                    ↩
                  </button>
                )}
              </div>
            </div>
          )
        })}
      </div>

      {/* 回复预览 */}
      {replyTo && (
        <div className="intervene-reply-bar">
          <span className="intervene-reply-label">
            回复 {replyTo.sender === 'user' ? '自己' : '主持人'}：
          </span>
          <span className="intervene-reply-preview">
            {replyTo.content.slice(0, 60)}{replyTo.content.length > 60 ? '...' : ''}
          </span>
          <button type="button" className="intervene-reply-cancel" onClick={cancelReply}>
            ×
          </button>
        </div>
      )}

      {/* 输入框 */}
      <div className="intervene-input-area">
        <textarea
          ref={inputRef}
          className="intervene-input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="向主持人发送消息... (Enter 发送)"
          rows={2}
          disabled={sending}
        />
        <button
          type="button"
          className="intervene-send-btn"
          onClick={handleSend}
          disabled={sending || !input.trim()}
        >
          {sending ? '...' : '发送'}
        </button>
      </div>
    </div>
  )
}