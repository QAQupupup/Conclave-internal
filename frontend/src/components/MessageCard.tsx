// 单条发言卡片：按角色着色，渲染内容与 claim_refs（证据 ref 可点击高亮右侧面板）
// 增强：淡入上滑动画、HH:MM:SS 发言时间、超长消息折叠/展开
// 增强 2：复制按钮、FocusMode 放大查看（保持原有简洁样式，不做颜色高亮）
import { useState } from 'react'
import type { MeetingMessage } from '../types/events.ts'
import { ROLE_LABELS, STAGE_LABELS } from '../types/events.ts'
import { FocusMode } from './FocusMode.tsx'
import { formatTime, tryFormatJson, truncate } from '../lib/format.ts'
import { useCopy } from '../hooks/useCopy.ts'
import { renderMessageContent } from './MessageContent.tsx'
import { EvidenceList } from './EvidenceBadge.tsx'

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

export function MessageCard({ message, onSelectRef }: MessageCardProps) {
  const role = message.agent_role
  const refs = [...(message.claim_refs ?? []), ...(message.evidence_refs ?? [])]
  const displayText = tryFormatJson(message.content)
  const isLong = displayText.length > COLLAPSE_THRESHOLD
  const [isExpanded, setIsExpanded] = useState(false)
  const [focused, setFocused] = useState(false)
  const { copied, copy } = useCopy()
  // 折叠时截断并加省略号，避免长消息挤压视图
  const truncatedText = isLong && !isExpanded ? truncate(displayText, COLLAPSE_THRESHOLD) : displayText

  return (
    <div className={`message-card ${roleClass(role)} message-in${isExpanded ? ' is-expanded' : ''}`}>
      <div className="message-head">
        <span className="message-role">{ROLE_LABELS[role] ?? role}</span>
        <span className="message-stage">{STAGE_LABELS[message.stage] ?? message.stage}</span>
        {message.created_at && (
          <span className="message-time">{formatTime(message.created_at)}</span>
        )}
      </div>
      <div className="message-content">{renderMessageContent(truncatedText)}</div>
      <div className="message-actions">
        <div className="message-actions-left">
          {isLong && (
            <button
              type="button"
              className="btn btn-ghost expand-btn"
              onClick={() => setIsExpanded(v => !v)}
            >
              {isExpanded ? '收起' : '展开全部'}
            </button>
          )}
        </div>
        <div className="message-actions-right">
          <button
            type="button"
            className={`btn btn-ghost copy-btn${copied ? ' is-copied' : ''}`}
            onClick={() => copy(displayText)}
            title="复制完整内容到剪贴板"
          >
            {copied ? '已复制' : '复制'}
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
      </div>
      {refs.length > 0 && (
        <div className="message-refs">
          <EvidenceList refs={refs} onSelectRef={onSelectRef} />
        </div>
      )}
      <FocusMode open={focused} onClose={() => setFocused(false)} title={ROLE_LABELS[role] ?? role}>
        <div className="message-content-full">{renderMessageContent(displayText)}</div>
      </FocusMode>
    </div>
  )
}
