// 单条发言卡片：按角色着色，渲染内容与 claim_refs（证据 ref 可点击高亮右侧面板）
// 增强：淡入上滑动画、HH:MM:SS 发言时间、超长消息折叠/展开
// 增强 2：复制按钮、FocusMode 放大查看（使用 AntD Card + Tag + Button + Typography）
import { useState } from 'react'
import { Card, Tag, Button, Space, Typography } from 'antd'
import { ExpandOutlined, CompressOutlined, CopyOutlined, CheckOutlined, ZoomInOutlined } from '@ant-design/icons'
import type { MeetingMessage } from '../types/events.ts'
import { ROLE_LABELS, STAGE_LABELS } from '../types/events.ts'
import { FocusMode } from './FocusMode.tsx'
import { formatTime, tryFormatJson, truncate } from '../lib/format.ts'
import { useCopy } from '../hooks/useCopy.ts'
import { renderMessageContent } from './MessageContent.tsx'
import { EvidenceList } from './EvidenceBadge.tsx'

const { Text } = Typography

interface MessageCardProps {
  message: MeetingMessage
  /** 点击证据 ref 时触发，用于在右侧证据面板定位 */
  onSelectRef?: (ref: string) => void
}

/** 超过该字符数视为长消息，默认折叠 */
const COLLAPSE_THRESHOLD = 300

/** 角色 → AntD Tag color */
function roleTagColor(role: MeetingMessage['agent_role']): string {
  switch (role) {
    case 'moderator':
      return 'purple'
    case 'product_architect':
      return 'blue'
    case 'engineer':
      return 'green'
    default:
      return 'default'
  }
}

/** 角色 → CSS class（保留用于卡片边框着色） */
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
    <Card
      className={`message-card ${roleClass(role)} message-in${isExpanded ? ' is-expanded' : ''}`}
      size="small"
      styles={{ body: { padding: '12px 16px' } }}
    >
      <div className="message-head">
        <Space size={8}>
          <Tag color={roleTagColor(role)} className="message-card-role-tag">
            {ROLE_LABELS[role] ?? role}
          </Tag>
          <Text type="secondary" className="message-card-stage-text">
            {STAGE_LABELS[message.stage] ?? message.stage}
          </Text>
          {message.created_at && (
            <Text type="secondary" className="message-card-stage-text">
              {formatTime(message.created_at)}
            </Text>
          )}
        </Space>
      </div>
      <div className="message-content message-card-body-spacing">
        {renderMessageContent(truncatedText)}
      </div>
      <div className="message-actions message-card-actions-bar">
        <Space size={4}>
          {isLong && (
            <Button
              type="text"
              size="small"
              icon={isExpanded ? <CompressOutlined /> : <ExpandOutlined />}
              onClick={() => setIsExpanded(v => !v)}
            >
              {isExpanded ? '收起' : '展开全部'}
            </Button>
          )}
        </Space>
        <Space size={4}>
          <Button
            type="text"
            size="small"
            icon={copied ? <CheckOutlined /> : <CopyOutlined />}
            onClick={() => copy(displayText)}
          >
            {copied ? '已复制' : '复制'}
          </Button>
          {isLong && (
            <Button
              type="text"
              size="small"
              icon={<ZoomInOutlined />}
              onClick={() => setFocused(true)}
            >
              放大查看
            </Button>
          )}
        </Space>
      </div>
      {refs.length > 0 && (
        <div className="message-refs message-card-refs-spacing">
          <EvidenceList refs={refs} onSelectRef={onSelectRef} />
        </div>
      )}
      <FocusMode open={focused} onClose={() => setFocused(false)} title={ROLE_LABELS[role] ?? role}>
        <div className="message-content-full">{renderMessageContent(displayText)}</div>
      </FocusMode>
    </Card>
  )
}
