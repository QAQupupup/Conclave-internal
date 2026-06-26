// 左侧聊天流：渲染发言卡片列表，新消息时自动滚动到底部
import { useEffect, useRef } from 'react'
import { useMeeting } from '../store/MeetingContext.tsx'
import { MessageCard } from './MessageCard.tsx'

interface ChatPanelProps {
  /** 点击证据 ref 时触发，向上传递以定位右侧证据面板 */
  onSelectRef?: (ref: string) => void
}

export function ChatPanel({ onSelectRef }: ChatPanelProps) {
  const { store } = useMeeting()
  const messages = store.meeting?.messages ?? []
  const bottomRef = useRef<HTMLDivElement | null>(null)

  // 新消息时滚动到底部
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages.length])

  return (
    <section className="panel chat-panel">
      <div className="panel-title">聊天流</div>
      <div className="chat-list">
        {messages.length === 0 && (
          <div className="empty-hint">暂无发言，创建会议并运行后，agent 发言将在此实时展示。</div>
        )}
        {messages.map((m) => (
          <MessageCard key={m.id} message={m} onSelectRef={onSelectRef} />
        ))}
        <div ref={bottomRef} />
      </div>
    </section>
  )
}
