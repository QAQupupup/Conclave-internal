// 单条发言卡片：按角色着色，渲染内容与 claim_refs（证据 ref 可点击高亮右侧面板）
// 增强：淡入上滑动画、HH:MM:SS 发言时间、超长消息折叠/展开
// 增强 2：复制按钮、FocusMode 放大查看（保持原有简洁样式，不做颜色高亮）
import { useState } from 'react'
import type { MeetingMessage } from '../types/events.ts'
import { ROLE_LABELS, STAGE_LABELS } from '../types/events.ts'
import { FocusMode } from './FocusMode.tsx'

interface MessageCardProps {
  message: MeetingMessage
  /** 点击证据 ref 时触发，用于在右侧证据面板定位 */
  onSelectRef?: (ref: string) => void
}

/** 超过该字符数视为长消息，默认折叠 */
const COLLAPSE_THRESHOLD = 300

/** 角色 → CSS 颜色类 */
function roleClass(role: MeetingMessage['agent_role']): string {
  switch (role) {
    case 'moderator':
      return 'role-moderator'
    case 'product_architect':
      return 'role-architect'
    case 'engineer':
      return 'role-engineer'
    default:
      return 'role-default'
  }
}

/** 尝试把内容解析并重新格式化（仅做缩进美化，不做颜色高亮） */
function tryFormatJson(content: string): { ok: true; formatted: string } | { ok: false } {
  const trimmed = content.trim()
  if (!trimmed.startsWith('{') && !trimmed.startsWith('[')) return { ok: false }
  try {
    return { ok: true, formatted: JSON.stringify(JSON.parse(trimmed), null, 2) }
  } catch {
    return { ok: false }
  }
}

/** 把 ISO 时间字符串格式化为 HH:MM:SS */
function formatTime(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

export function MessageCard({ message, onSelectRef }: MessageCardProps) {
  const role = message.agent_role
  const refs = [...(message.claim_refs ?? []), ...(message.evidence_refs ?? [])]
  const formatted = tryFormatJson(message.content)
  const displayText = formatted.ok ? formatted.formatted : message.content
  const isLong = displayText.length > COLLAPSE_THRESHOLD
  const [isExpanded, setIsExpanded] = useState(false)
  const [focused, setFocused] = useState(false)
  const [copyTip, setCopyTip] = useState(false)
  // 折叠时截断并加省略号，避免长消息挤压视图
  const truncatedText = isLong && !isExpanded ? displayText.slice(0, COLLAPSE_THRESHOLD) + '…' : displayText

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(displayText)
      setCopyTip(true)
      setTimeout(() => setCopyTip(false), 1200)
    } catch {
      // 兜底：旧 API
      const ta = document.createElement('textarea')
      ta.value = displayText
      document.body.appendChild(ta)
      ta.select()
      try {
        document.execCommand('copy')
        setCopyTip(true)
        setTimeout(() => setCopyTip(false), 1200)
      } catch {
        /* noop */
      } finally {
        document.body.removeChild(ta)
      }
    }
  }

  return (
    <div className={`message-card ${roleClass(role)} message-in`}>
      <div className="message-head">
        <span className="message-role">{ROLE_LABELS[role] ?? role}</span>
        <span className="message-stage">{STAGE_LABELS[message.stage] ?? message.stage}</span>
        {message.created_at && (
          <span className="message-time">{formatTime(message.created_at)}</span>
        )}
      </div>
      <pre className="message-content">{truncatedText}</pre>
      <div className="message-actions">
        {isLong && (
          <button
            type="button"
            className="btn btn-ghost expand-btn"
            onClick={() => setIsExpanded(v => !v)}
          >
            {isExpanded ? '收起' : '展开全部'}
          </button>
        )}
        <button
          type="button"
          className={`btn btn-ghost copy-btn${copyTip ? ' is-copied' : ''}`}
          onClick={handleCopy}
          title="复制完整内容到剪贴板"
        >
          {copyTip ? '已复制' : '复制'}
        </button>
        {isLong && (
          <button
            type="button"
            className="btn btn-ghost focus-btn"
            onClick={() => setFocused(true)}
            title="放大查看完整内容"
          >
            放大查看
          </button>
        )}
      </div>
      {refs.length > 0 && (
        <div className="message-refs">
          {refs.map((ref, i) => (
            <button
              key={`${ref}-${i}`}
              className="ref-chip"
              type="button"
              onClick={() => onSelectRef?.(ref)}
              title="点击在右侧证据面板定位"
            >
              {ref}
            </button>
          ))}
        </div>
      )}
      <FocusMode open={focused} onClose={() => setFocused(false)} title={ROLE_LABELS[role] ?? role}>
        <pre className="message-content-full">{displayText}</pre>
      </FocusMode>
    </div>
  )
}
