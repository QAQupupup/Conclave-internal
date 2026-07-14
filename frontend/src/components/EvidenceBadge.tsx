// 统一证据渲染组件：把机器可读的证据引用转换为人类友好格式
// 支持三级可靠性：已核验(verified) / 可追溯(traceable) / 推理假设(assumption)
// 使用 AntD Tag + Badge + Typography
import { useState } from 'react'
import { Tag, Button, Space, Typography } from 'antd'
import { CheckCircleOutlined, LinkOutlined, QuestionCircleOutlined } from '@ant-design/icons'

const { Text } = Typography

// ---------- 证据等级 ----------

export type EvidenceLevel = 'verified' | 'traceable' | 'assumption'

const LEVEL_CONFIG: Record<EvidenceLevel, { label: string; color: string; icon: React.ReactNode }> = {
  verified:   { label: '已核验', color: 'green', icon: <CheckCircleOutlined /> },
  traceable:  { label: '可追溯', color: 'blue', icon: <LinkOutlined /> },
  assumption: { label: '推理假设', color: 'orange', icon: <QuestionCircleOutlined /> },
}

// ---------- 证据条目 ----------

export interface EvidenceItem {
  /** 证据唯一标识（如 claim-xxx, evidence-xxx, doc:section） */
  id: string
  /** 证据来源名称（文档名/章节名） */
  sourceName?: string
  /** 来源链接（可点击跳转） */
  sourceUrl?: string
  /** 证据引用原文片段 */
  quote?: string
  /** 可靠性等级 */
  level: EvidenceLevel
  /** 证据类型标签 */
  typeLabel?: string
}

// ---------- 解析函数：从原始 ref 字符串推断 EvidenceItem ----------

/** 从原始 ref 字符串（如 "claim-6826e54b", "evidence-xxx", "doc:section"）解析为 EvidenceItem */
export function parseEvidenceRef(ref: string): EvidenceItem {
  // claim-xxx → 论点
  if (ref.startsWith('claim-')) {
    return {
      id: ref,
      sourceName: `论点 ${ref.slice(-4)}`,
      level: 'assumption',
      typeLabel: '论点',
    }
  }
  // evidence-xxx → 证据
  if (ref.startsWith('evidence-')) {
    return {
      id: ref,
      sourceName: `证据片段 ${ref.slice(-4)}`,
      level: 'traceable',
      typeLabel: '证据',
    }
  }
  // doc:xxx → 文档引用
  if (ref.includes(':')) {
    const [doc, section] = ref.split(':', 2)
    return {
      id: ref,
      sourceName: section ? `《${doc}》${section}` : `《${doc}》`,
      level: 'verified',
      typeLabel: '文档',
    }
  }
  // 其他
  return {
    id: ref,
    sourceName: ref.length > 12 ? ref.slice(0, 6) + '…' + ref.slice(-4) : ref,
    level: 'traceable',
    typeLabel: '引用',
  }
}

// ---------- 组件 Props ----------

export interface EvidenceBadgeProps {
  item: EvidenceItem
  /** 点击回调（可传递 id 用于定位） */
  onClick?: (id: string) => void
  /** 是否显示完整详情（默认 compact） */
  expanded?: boolean
  /** 自定义类名 */
  className?: string
}

// ---------- 单个证据徽章 ----------

export function EvidenceBadge({ item, onClick, expanded: forceExpanded, className = '' }: EvidenceBadgeProps) {
  const [localExpanded, setLocalExpanded] = useState(false)
  const expanded = forceExpanded ?? localExpanded
  const cfg = LEVEL_CONFIG[item.level]

  const handleClick = () => {
    if (item.quote) {
      setLocalExpanded(v => !v)
    }
    onClick?.(item.id)
  }

  return (
    <span className={`evidence-badge ${className}${expanded ? ' is-expanded' : ''}`}>
      <Tag
        icon={cfg.icon}
        color={cfg.color}
        className="evidence-badge-tag"
        onClick={handleClick}
        title={item.sourceName ?? item.id}
      >
        <span>{item.sourceName ?? item.id}</span>
        <span className="evidence-badge-level">({cfg.label})</span>
      </Tag>
      {expanded && item.quote && (
        <div className="evidence-badge-quote-box">
          <Text type="secondary" className="evidence-badge-quote-text">「{item.quote}」</Text>
        </div>
      )}
    </span>
  )
}

// ---------- 证据列表（横向排列） ----------

export interface EvidenceListProps {
  /** 原始 ref 字符串列表（claim-xxx, evidence-xxx, doc:section） */
  refs: string[]
  /** 点击回调 */
  onSelectRef?: (ref: string) => void
  /** 默认可见数量，超出折叠为 "+N" */
  visibleCount?: number
}

export function EvidenceList({ refs, onSelectRef, visibleCount = 3 }: EvidenceListProps) {
  const [expanded, setExpanded] = useState(false)
  const hasMany = refs.length > visibleCount
  const visible = hasMany && !expanded ? refs.slice(0, visibleCount) : refs
  const hidden = refs.length - visibleCount

  if (refs.length === 0) return null

  return (
    <div className="evidence-list evidence-badge-list-inline">
      {visible.map((ref, i) => (
        <EvidenceBadge
          key={`${ref}-${i}`}
          item={parseEvidenceRef(ref)}
          onClick={onSelectRef}
        />
      ))}
      {hasMany && (
        <Button
          type="link"
          size="small"
          onClick={() => setExpanded(v => !v)}
        >
          {expanded ? '收起' : `+${hidden}`}
        </Button>
      )}
    </div>
  )
}

// ---------- 证据详情面板（用于弹出窗口展示完整证据链） ----------

export interface EvidenceDetailProps {
  items: EvidenceItem[]
  title?: string
}

export function EvidenceDetail({ items, title = '证据链' }: EvidenceDetailProps) {
  if (items.length === 0) {
    return <Text type="secondary">暂无证据引用</Text>
  }
  return (
    <div className="evidence-detail">
      <Text strong className="evidence-detail-title">{title}</Text>
      <Space direction="vertical" size={8} className="evidence-detail-space">
        {items.map((item, i) => (
          <div key={item.id} className="evidence-detail-item">
            <Text type="secondary">{i + 1}.</Text>
            <EvidenceBadge item={item} expanded />
          </div>
        ))}
      </Space>
    </div>
  )
}
