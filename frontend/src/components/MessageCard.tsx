// 单条发言卡片：按角色着色，渲染内容与 claim_refs（证据 ref 可点击高亮右侧面板）
import type { MeetingMessage } from '../types/events.ts'
import { ROLE_LABELS, STAGE_LABELS } from '../types/events.ts'

interface MessageCardProps {
  message: MeetingMessage
  /** 点击证据 ref 时触发，用于在右侧证据面板定位 */
  onSelectRef?: (ref: string) => void
}

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

export function MessageCard({ message, onSelectRef }: MessageCardProps) {
  const role = message.agent_role
  const refs = [...(message.claim_refs ?? []), ...(message.evidence_refs ?? [])]

  return (
    <div className={`message-card ${roleClass(role)}`}>
      <div className="message-head">
        <span className="message-role">{ROLE_LABELS[role] ?? role}</span>
        <span className="message-stage">{STAGE_LABELS[message.stage] ?? message.stage}</span>
        {message.created_at && (
          <span className="message-time">
            {new Date(message.created_at).toLocaleTimeString()}
          </span>
        )}
      </div>
      <pre className="message-content">{renderContent(message.content)}</pre>
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
