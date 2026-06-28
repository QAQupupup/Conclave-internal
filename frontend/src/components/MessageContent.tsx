// 消息内容语义化渲染器
// 把 LLM 生成的 [constraint]、[assumption]、[common_knowledge] 等技术标签
// 解析为彩色中文 badge，提升可读性
import type { ReactNode } from 'react'

/** 标签 → {中文, CSS 类} 映射 */
const TAG_MAP: Record<string, { label: string; cls: string }> = {
  constraint: { label: '约束', cls: 'tag-constraint' },
  assumption: { label: '假设', cls: 'tag-assumption' },
  common_knowledge: { label: '通用知识', cls: 'tag-common' },
  fact: { label: '事实', cls: 'tag-fact' },
  risk: { label: '风险', cls: 'tag-risk' },
  decision: { label: '决策', cls: 'tag-decision' },
  question: { label: '问题', cls: 'tag-question' },
  requirement: { label: '需求', cls: 'tag-requirement' },
}

/** 匹配 [xxx] 格式的标签 */
const TAG_PATTERN = /\[(constraint|assumption|common_knowledge|fact|risk|decision|question|requirement)\]/g

/** 解析消息文本，把标签替换为 badge，其余保持纯文本 */
export function renderMessageContent(text: string): ReactNode[] {
  const parts: ReactNode[] = []
  let lastIndex = 0
  let match: RegExpExecArray | null
  let key = 0

  TAG_PATTERN.lastIndex = 0
  while ((match = TAG_PATTERN.exec(text)) !== null) {
    // 标签前的纯文本
    if (match.index > lastIndex) {
      parts.push(text.slice(lastIndex, match.index))
    }
    // 标签本身
    const tagKey = match[1]
    const info = TAG_MAP[tagKey]
    if (info) {
      parts.push(
        <span key={`tag-${key++}`} className={`msg-tag ${info.cls}`}>
          {info.label}
        </span>,
      )
    } else {
      parts.push(match[0])
    }
    lastIndex = match.index + match[0].length
  }
  // 剩余文本
  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex))
  }
  return parts
}

/** ref chip 友好显示：claim-6826e54b → 论点·54b */
export function formatRefLabel(ref: string): string {
  // claim-6826e54b → 论点·54b
  if (ref.startsWith('claim-')) {
    const short = ref.slice(-4)
    return `论点·${short}`
  }
  // evidence-xxx → 证据·xxx
  if (ref.startsWith('evidence-')) {
    const short = ref.slice(-4)
    return `证据·${short}`
  }
  // 其他：截取后 6 位
  if (ref.length > 10) {
    return ref.slice(0, 4) + '…' + ref.slice(-4)
  }
  return ref
}
