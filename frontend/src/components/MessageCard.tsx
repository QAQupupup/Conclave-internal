// 单条发言卡片：按角色着色，渲染内容与 claim_refs（证据 ref 可点击高亮右侧面板）
// 增强：淡入上滑动画、HH:MM:SS 发言时间、超长消息折叠/展开
// 增强 2：JSON 语法高亮、复制按钮、FocusMode 放大查看
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

/** 尝试把内容渲染成格式化 JSON；失败则原样返回 */
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

/**
 * 极简 JSON 语法高亮：把字符串拆为 tokens，
 * 分别为 key（对象 key）、string（值字符串）、number、boolean、null、punct 着色。
 * 注意：仅做展示用，不保证完美；不做 HTML 转义外的安全处理。
 */
type JsonToken =
  | { kind: 'key'; text: string }
  | { kind: 'string'; text: string }
  | { kind: 'number'; text: string }
  | { kind: 'boolean'; text: string }
  | { kind: 'null'; text: string }
  | { kind: 'punct'; text: string }
  | { kind: 'text'; text: string }

function tokenizeJson(src: string): JsonToken[] {
  const tokens: JsonToken[] = []
  let i = 0
  const n = src.length
  while (i < n) {
    const ch = src[i]
    // 跳过空白
    if (ch === ' ' || ch === '\n' || ch === '\t' || ch === '\r') {
      let j = i
      while (j < n && /\s/.test(src[j])) j++
      tokens.push({ kind: 'text', text: src.slice(i, j) })
      i = j
      continue
    }
    // 字符串（可能是 key：紧跟 ":"）或值
    if (ch === '"') {
      let j = i + 1
      while (j < n) {
        if (src[j] === '\\' && j + 1 < n) {
          j += 2
          continue
        }
        if (src[j] === '"') {
          j++
          break
        }
        j++
      }
      const text = src.slice(i, j)
      // 判断是否为 key：跳过空白后是 ":"
      let k = j
      while (k < n && /\s/.test(src[k])) k++
      if (src[k] === ':') {
        tokens.push({ kind: 'key', text })
      } else {
        tokens.push({ kind: 'string', text })
      }
      i = j
      continue
    }
    // 数字
    if (ch === '-' || (ch >= '0' && ch <= '9')) {
      let j = i + 1
      while (j < n && /[0-9eE+\-.]/.test(src[j])) j++
      tokens.push({ kind: 'number', text: src.slice(i, j) })
      i = j
      continue
    }
    // 布尔 / null
    if (src.startsWith('true', i)) {
      tokens.push({ kind: 'boolean', text: 'true' })
      i += 4
      continue
    }
    if (src.startsWith('false', i)) {
      tokens.push({ kind: 'boolean', text: 'false' })
      i += 5
      continue
    }
    if (src.startsWith('null', i)) {
      tokens.push({ kind: 'null', text: 'null' })
      i += 4
      continue
    }
    // 标点
    if (ch === '{' || ch === '}' || ch === '[' || ch === ']' || ch === ',' || ch === ':') {
      tokens.push({ kind: 'punct', text: ch })
      i++
      continue
    }
    // 其它字符
    tokens.push({ kind: 'text', text: ch })
    i++
  }
  return tokens
}

/** HTML 转义：把 < > & " 转义，避免高亮 HTML 被注入 */
function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

/** 把 token 序列转为带 class 的 HTML 字符串（用于 dangerouslySetInnerHTML） */
function tokensToHtml(tokens: JsonToken[]): string {
  return tokens
    .map(t => {
      const text = escapeHtml(t.text)
      if (t.kind === 'text') return text
      return `<span class="json-${t.kind}">${text}</span>`
    })
    .join('')
}

/** 渲染单条 MessageCard 的内容区（带 JSON 高亮）；返回字符串 HTML */
function renderHighlighted(text: string): string {
  const result = tryFormatJson(text)
  if (!result.ok) return escapeHtml(text)
  return tokensToHtml(tokenizeJson(result.formatted))
}

export function MessageCard({ message, onSelectRef }: MessageCardProps) {
  const role = message.agent_role
  const refs = [...(message.claim_refs ?? []), ...(message.evidence_refs ?? [])]
  const formatted = tryFormatJson(message.content)
  const isJson = formatted.ok
  const displayText = isJson ? formatted.formatted : message.content
  const isLong = displayText.length > COLLAPSE_THRESHOLD
  const [isExpanded, setIsExpanded] = useState(false)
  const [focused, setFocused] = useState(false)
  const [copyTip, setCopyTip] = useState(false)
  // 折叠时截断并加省略号，避免长消息挤压视图
  const truncatedText = isLong && !isExpanded ? displayText.slice(0, COLLAPSE_THRESHOLD) + '…' : displayText
  const truncatedHtml = renderHighlighted(truncatedText)

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

  // FocusMode 中显示完整内容（不受折叠影响）
  const fullHtml = renderHighlighted(displayText)

  return (
    <div className={`message-card ${roleClass(role)} message-in`}>
      <div className="message-head">
        <span className="message-role">{ROLE_LABELS[role] ?? role}</span>
        <span className="message-stage">{STAGE_LABELS[message.stage] ?? message.stage}</span>
        {message.created_at && (
          <span className="message-time">{formatTime(message.created_at)}</span>
        )}
      </div>
      <pre
        className={`message-content${isJson ? ' is-json' : ''}`}
        dangerouslySetInnerHTML={{ __html: truncatedHtml }}
      />
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
        <pre
          className={`message-content-full${isJson ? ' is-json' : ''}`}
          dangerouslySetInnerHTML={{ __html: fullHtml }}
        />
      </FocusMode>
    </div>
  )
}
