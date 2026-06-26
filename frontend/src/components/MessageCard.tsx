// 单条发言卡片：按角色着色，渲染内容与 claim_refs（证据 ref 可点击高亮右侧面板）
// 增强：淡入上滑动画、HH:MM:SS 发言时间、超长消息折叠/展开
import { useState } from 'react'
import type { MeetingMessage } from '../types/events.ts'
import { ROLE_LABELS, STAGE_LABELS } from '../types/events.ts'

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

/** 尝试把内容渲染成格式化 JSON；失败则原样返回 */
function renderContent(content: string): string {
  const trimmed = content.trim()
  if (!trimmed.startsWith('{') && !trimmed.startsWith('[')) return content
  try {
    return JSON.stringify(JSON.parse(trimmed), null, 2)
  } catch {
    return content
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
  const rendered = renderContent(message.content)
  const isLong = rendered.length > COLLAPSE_THRESHOLD
  const [isExpanded, setIsExpanded] = useState(false)
  // 折叠时截断并加省略号，避免长消息挤压视图
  const displayContent =
    isLong && !isExpanded ? rendered.slice(0, COLLAPSE_THRESHOLD) + '…' : rendered

  return (
    <div className={`message-card ${roleClass(role)} message-in`}>
      <div className="message-head">
        <span className="message-role">{ROLE_LABELS[role] ?? role}</span>
        <span className="message-stage">{STAGE_LABELS[message.stage] ?? message.stage}</span>
        {message.created_at && (
          <span className="message-time">{formatTime(message.created_at)}</span>
        )}
      </div>
      <pre className="message-content">{displayContent}</pre>
      {isLong && (
        <button
          type="button"
          className="btn btn-ghost expand-btn"
          onClick={() => setIsExpanded((v) => !v)}
        >
          {isExpanded ? '收起' : '展开全部'}
        </button>
      )}
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
    </div>
  )
}
