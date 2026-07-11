// 聊天输入框：支持 @ 唤起历史会议搜索 → 注入引用
// 类似 Cursor/Terminal 中的 @mention 交互模式
// 使用 AntD Input.TextArea + Button + Tag
import { useState, useRef, useEffect, useCallback } from 'react'
import { Input, Button, Tag, Typography, Space } from 'antd'
import { SendOutlined, PaperClipOutlined } from '@ant-design/icons'
import { useMeeting } from '../store/MeetingContext.tsx'
import { listMeetings, type MeetingListItem } from '../lib/api.ts'

const { Text } = Typography

interface Props {
  meetingId: string
}

export function ChatInput({ meetingId }: Props) {
  const { injectReference } = useMeeting()
  const [text, setText] = useState('')
  const [showMention, setShowMention] = useState(false)
  const [mentionQuery, setMentionQuery] = useState('')
  const [mentionResults, setMentionResults] = useState<MeetingListItem[]>([])
  const [selectedRefs, setSelectedRefs] = useState<{ id: string; topic: string }[]>([])
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState<string | null>(null)
  const textareaRef = useRef<import('antd/es/input/TextArea').TextAreaRef>(null)
  const mentionRef = useRef<HTMLDivElement>(null)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  // 检测 @ 输入：在文本末尾找到最后一个 @ 后的字符
  const detectMention = useCallback((value: string, cursorPos: number) => {
    const beforeCursor = value.slice(0, cursorPos)
    const atMatch = beforeCursor.match(/@([^\s@]*)$/)
    if (atMatch) {
      setMentionQuery(atMatch[1])
      setShowMention(true)
    } else {
      setShowMention(false)
    }
  }, [])

  // 搜索会议（300ms 防抖）
  useEffect(() => {
    if (!showMention || !mentionQuery) {
      // 空查询显示最近完成的会议
      if (showMention && !mentionQuery) {
        doMentionSearch('')
      }
      return
    }
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => doMentionSearch(mentionQuery), 300)
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current) }
  }, [mentionQuery, showMention])

  const doMentionSearch = async (q: string) => {
    try {
      const res = await listMeetings({ q: q || undefined, limit: 8 })
      setMentionResults(res.meetings.filter(m => !m.is_running))
    } catch {
      setMentionResults([])
    }
  }

  // 点击外部关闭 mention 下拉
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (mentionRef.current && !mentionRef.current.contains(e.target as Node)) {
        setShowMention(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const selectMention = (item: MeetingListItem) => {
    // 替换文本中的 @mentionQuery 为会议引用标记
    const beforeAt = text.slice(0, text.lastIndexOf('@'))
    const afterQuery = text.slice(text.lastIndexOf('@') + 1 + mentionQuery.length)
    const refTag = `[引用:${item.topic.slice(0, 30)}]`
    setText(beforeAt + refTag + afterQuery)
    setSelectedRefs(prev => {
      if (prev.some(r => r.id === item.meeting_id)) return prev
      return [...prev, { id: item.meeting_id, topic: item.topic }]
    })
    setShowMention(false)
    textareaRef.current?.focus()
  }

  const handleChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const value = e.target.value
    setText(value)
    detectMention(value, e.target.selectionStart)
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey && !showMention) {
      e.preventDefault()
      handleSubmit()
    }
    if (e.key === 'Escape' && showMention) {
      setShowMention(false)
    }
  }

  const handleSubmit = async () => {
    const trimmed = text.trim()
    if (!trimmed) return
    setBusy(true)
    setStatus(null)
    try {
      // 如果有选中的引用会议，先注入引用
      if (selectedRefs.length > 0) {
        await injectReference(meetingId, selectedRefs.map(r => r.id))
      }
      // 如果有文本内容，通过 controlMeeting 注入到会议
      if (trimmed) {
        const { controlMeeting } = await import('../lib/api.ts')
        await controlMeeting(meetingId, 'inject', { message: trimmed, type: 'user_input' })
      }
      setText('')
      setSelectedRefs([])
      setStatus(selectedRefs.length > 0 ? `已注入 ${selectedRefs.length} 个历史会议引用` : '消息已发送')
      setTimeout(() => setStatus(null), 3000)
    } catch (err) {
      setStatus(`发送失败: ${err instanceof Error ? err.message : String(err)}`)
    } finally {
      setBusy(false)
    }
  }

  const removeRef = (id: string) => {
    setSelectedRefs(prev => prev.filter(r => r.id !== id))
    // 从文本中移除对应的引用标记
    const ref = selectedRefs.find(r => r.id === id)
    if (ref) {
      setText(prev => prev.replace(`[引用:${ref.topic.slice(0, 30)}]`, ''))
    }
  }

  return (
    <div className="chat-input-wrap">
      {/* 已选引用标签 */}
      {selectedRefs.length > 0 && (
        <div className="chat-input-refs" style={{ marginBottom: 8 }}>
          <Space wrap size={[4, 4]}>
            {selectedRefs.map(ref => (
              <Tag
                key={ref.id}
                icon={<PaperClipOutlined />}
                closable
                onClose={() => removeRef(ref.id)}
                color="blue"
              >
                {ref.topic.slice(0, 25)}
              </Tag>
            ))}
          </Space>
        </div>
      )}

      <div className="chat-input-row" style={{ display: 'flex', gap: 8 }}>
        <Input.TextArea
          ref={textareaRef}
          value={text}
          onChange={handleChange}
          onKeyDown={handleKeyDown}
          placeholder="输入消息… 输入 @ 引用历史会议"
          autoSize={{ minRows: 1, maxRows: 4 }}
          disabled={busy}
          style={{ flex: 1 }}
        />
        <Button
          type="primary"
          icon={<SendOutlined />}
          onClick={handleSubmit}
          loading={busy}
          disabled={!text.trim()}
          title="发送 (Enter)"
        />
      </div>

      {status && (
        <Text type="secondary" style={{ display: 'block', marginTop: 4, fontSize: 12 }}>
          {status}
        </Text>
      )}

      {/* @mention 下拉 */}
      {showMention && (
        <div
          ref={mentionRef}
          className="chat-mention-dropdown"
          style={{
            background: 'var(--card-bg, #fff)',
            border: '1px solid var(--border-color, #e5e7eb)',
            borderRadius: 8,
            marginTop: 4,
            maxHeight: 260,
            overflowY: 'auto',
            boxShadow: '0 4px 12px rgba(0,0,0,0.08)',
          }}
        >
          <div style={{ padding: '8px 12px', borderBottom: '1px solid var(--border-color, #e5e7eb)' }}>
            <Text type="secondary" style={{ fontSize: 12 }}>引用历史会议</Text>
          </div>
          {mentionResults.length === 0 && (
            <div style={{ padding: '12px', textAlign: 'center' }}>
              <Text type="secondary">未找到匹配的会议</Text>
            </div>
          )}
          {mentionResults.map(m => {
            const isSelected = selectedRefs.some(r => r.id === m.meeting_id)
            return (
              <div
                key={m.meeting_id}
                style={{
                  padding: '8px 12px',
                  cursor: 'pointer',
                  background: isSelected ? 'var(--accent-bg, #eef2ff)' : 'transparent',
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                }}
                onClick={() => selectMention(m)}
                onMouseEnter={(e) => { if (!isSelected) e.currentTarget.style.background = 'var(--hover-bg, #f9fafb)' }}
                onMouseLeave={(e) => { if (!isSelected) e.currentTarget.style.background = 'transparent' }}
              >
                <Text ellipsis style={{ maxWidth: '70%' }}>{m.topic}</Text>
                <Text type="secondary" style={{ fontSize: 12 }}>{m.meeting_id.slice(-8)}</Text>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
