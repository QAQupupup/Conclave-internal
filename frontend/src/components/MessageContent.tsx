// 消息内容语义化渲染器
// 把 LLM 生成的 [constraint]、[assumption]、[common_knowledge]、[doc:xxx]、[risk:high] 等标签
// 解析为 AntD Tag 彩色 badge，提升可读性
import { Tag } from 'antd'
import type { ReactNode } from 'react'

/** 标签类型定义：label=中文显示，color=AntD Tag color */
interface TagInfo {
  label: string
  color: string
}

/** 精确匹配标签（无参数后缀）：[fact]、[assumption] 等，同时支持 LLM 直接输出的中文标签 */
const EXACT_TAGS: Record<string, TagInfo> = {
  // 英文标签（标准）
  constraint:       { label: '约束',   color: 'orange' },
  assumption:       { label: '假设',   color: 'gold' },
  common_knowledge: { label: '常识',   color: 'blue' },
  fact:             { label: '事实',   color: 'green' },
  decision:         { label: '决策',   color: 'purple' },
  question:         { label: '问题',   color: 'cyan' },
  requirement:      { label: '需求',   color: 'magenta' },
  // 中文标签别名（LLM 偶尔会直接输出中文括号标签）
  '约束':           { label: '约束',   color: 'orange' },
  '假设':           { label: '假设',   color: 'gold' },
  '常识':           { label: '常识',   color: 'blue' },
  '事实':           { label: '事实',   color: 'green' },
  '决策':           { label: '决策',   color: 'purple' },
  '问题':           { label: '问题',   color: 'cyan' },
  '需求':           { label: '需求',   color: 'magenta' },
}

/** 前缀匹配标签（带参数后缀）：[doc:用户调研]、[web:xxx]、[risk:high] 等 */
const PREFIX_TAGS: Array<{ prefix: string; build: (arg: string) => TagInfo }> = [
  {
    prefix: 'risk:',
    build: (level) => {
      const label = level === 'high' ? '高风险' : level === 'medium' ? '中风险' : level === 'low' ? '低风险' : `风险:${level}`
      const color = level === 'high' ? 'red' : level === 'medium' ? 'orange' : 'default'
      return { label, color }
    },
  },
  {
    prefix: 'doc:',
    build: (name) => ({ label: `文档:${name}`, color: 'geekblue' }),
  },
  {
    prefix: 'web:',
    build: (_url) => ({ label: '网络', color: 'geekblue' }),
  },
  {
    prefix: 'common_knowledge:',
    build: (side) => ({
      label: side ? `常识·${side === 'side_a' ? 'A方' : side === 'side_b' ? 'B方' : side}` : '常识',
      color: 'blue',
    }),
  },
]

/**
 * 从文本的 position 位置开始尝试匹配一个 [xxx] 标签。
 * meta 标签不在此处处理（由行级解析处理）。
 */
function tryMatchTag(text: string, position: number): { info: TagInfo; length: number } | null {
  if (text[position] !== '[') return null
  // 找匹配的 ]
  let end = position + 1
  while (end < text.length && text[end] !== ']' && text[end] !== '\n' && text[end] !== '（' && text[end] !== '(') {
    end++
  }
  if (end >= text.length || text[end] !== ']') return null
  const inner = text.slice(position + 1, end)
  if (!inner) return null

  // meta 标签由行级处理，这里跳过
  if (inner === 'meta') return null

  // 1. 精确匹配
  if (EXACT_TAGS[inner]) {
    return { info: EXACT_TAGS[inner], length: end - position + 1 }
  }
  // 2. 前缀匹配
  for (const { prefix, build } of PREFIX_TAGS) {
    if (inner.startsWith(prefix)) {
      const arg = inner.slice(prefix.length)
      return { info: build(arg), length: end - position + 1 }
    }
  }
  return null
}

/** 解析一行文本（不含换行符），把标签替换为 AntD Tag */
function renderInline(text: string, keyPrefix: string): ReactNode[] {
  const parts: ReactNode[] = []
  let lastIndex = 0
  let key = 0
  let i = 0

  while (i < text.length) {
    const match = tryMatchTag(text, i)
    if (match) {
      if (i > lastIndex) {
        parts.push(text.slice(lastIndex, i))
      }
      parts.push(
        <Tag key={`${keyPrefix}-tag-${key++}`} color={match.info.color} style={{ marginInlineEnd: 4 }}>
          {match.info.label}
        </Tag>,
      )
      i += match.length
      lastIndex = i
    } else {
      i++
    }
  }
  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex))
  }
  return parts
}

/** 解析消息文本（按行处理），支持 [meta] 元信息行 */
export function renderMessageContent(text: string): ReactNode[] {
  const lines = text.split('\n')
  const nodes: ReactNode[] = []
  let key = 0

  for (const rawLine of lines) {
    // 判断是否为元信息行：开头可能有空格缩进，然后是 [meta]
    const metaMatch = rawLine.match(/^\s*\[meta\]\s*(.*)$/)
    if (metaMatch) {
      const metaContent = metaMatch[1]
      nodes.push(
        <div key={`meta-${key++}`} className="msg-meta-line">
          {renderInline(metaContent, `meta-${key}`)}
        </div>,
      )
    } else {
      // 普通行
      nodes.push(
        <div key={`line-${key++}`} className="msg-line">
          {renderInline(rawLine, `line-${key}`)}
        </div>,
      )
    }
  }
  return nodes
}

/** ref chip 友好显示：claim-6826e54b → 论点·54b */
export function formatRefLabel(ref: string): string {
  if (ref.startsWith('claim-')) {
    const short = ref.slice(-4)
    return `论点·${short}`
  }
  if (ref.startsWith('evidence-')) {
    const short = ref.slice(-4)
    return `证据·${short}`
  }
  if (ref.length > 10) {
    return ref.slice(0, 4) + '…' + ref.slice(-4)
  }
  return ref
}
