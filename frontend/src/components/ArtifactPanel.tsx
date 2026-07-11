// 右下：PRD 结构化预览 + OpenAPI 语法高亮 + 一键复制 + 借调入口 + 附件列表(跳转工作区)
// 使用 AntD Card + Button + List + Tag + Empty + Typography + Collapse
import { Card, Button, List, Tag, Empty, Typography, Space, Divider } from 'antd'
import { CopyOutlined, CheckOutlined, DownloadOutlined, FolderOpenOutlined, UserSwitchOutlined } from '@ant-design/icons'
import type { ReactNode } from 'react'
import { useMeeting } from '../store/MeetingContext.tsx'
import type { PRD } from '../types/events.ts'
import { useCopy } from '../hooks/useCopy.ts'

const { Text, Title } = Typography

interface Attachment {
  filename: string
  path: string
  size?: number
  ext?: string
  meeting_id?: string
}

interface ArtifactPanelProps {
  onOpenBorrow: () => void
  /** 点击附件"在工作区打开"时的回调，参数为文件相对路径 */
  onOpenInWorkspace?: (filePath: string) => void
}

export function ArtifactPanel({ onOpenBorrow, onOpenInWorkspace }: ArtifactPanelProps) {
  const { store } = useMeeting()
  const artifact = store.meeting?.artifact
  const meetingId = store.meeting?.meeting_id

  return (
    <section className="panel artifact-panel">
      <div className="panel-title" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span>产物预览</span>
        <Button type="link" size="small" icon={<UserSwitchOutlined />} onClick={onOpenBorrow}>
          借调专家
        </Button>
      </div>
      {!artifact ? (
        <Empty description="会议进行中，产出物将在 produce 阶段生成" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : (
        <div className="artifact-body">
          <PRDSection prd={artifact.prd} />
          <OpenAPISection yaml={artifact.openapi} />
          <AttachmentsSection
            attachments={artifact.attachments}
            meetingId={meetingId}
            onOpenInWorkspace={onOpenInWorkspace}
          />
        </div>
      )}
    </section>
  )
}

/* ============================ 附件区域 ============================ */

function AttachmentsSection({
  attachments,
  meetingId,
  onOpenInWorkspace,
}: {
  attachments?: Attachment[]
  meetingId?: string
  onOpenInWorkspace?: (filePath: string) => void
}) {
  const list = attachments ?? []
  if (list.length === 0) return null

  return (
    <Card size="small" title={`产出文件（${list.length}）`} style={{ marginTop: 12 }}>
      <List
        size="small"
        dataSource={list}
        renderItem={(att, i) => {
          const relPath = meetingId ? att.filename : att.path.split(/[/\\]/).slice(-1)[0]
          return (
            <List.Item
              key={i}
              actions={[
                meetingId && (
                  <a
                    key="download"
                    href={`/meetings/${meetingId}/attachments/${encodeURIComponent(att.filename)}`}
                    download={att.filename}
                    title="下载"
                  >
                    <Button type="text" size="small" icon={<DownloadOutlined />}>下载</Button>
                  </a>
                ),
                onOpenInWorkspace && (
                  <Button
                    key="workspace"
                    type="text"
                    size="small"
                    icon={<FolderOpenOutlined />}
                    onClick={() => onOpenInWorkspace(relPath)}
                  >
                    在工作区打开
                  </Button>
                ),
              ].filter(Boolean) as ReactNode[]}
            >
              <List.Item.Meta
                title={
                  <Space>
                    <Tag>{att.ext || 'FILE'}</Tag>
                    <Text>{att.filename}</Text>
                  </Space>
                }
                description={att.size != null ? (att.size > 1024 ? `${(att.size / 1024).toFixed(1)}KB` : `${att.size}B`) : undefined}
              />
            </List.Item>
          )
        }}
      />
    </Card>
  )
}

/* ============================ PRD 区域 ============================ */

function PRDSection({ prd }: { prd: PRD | undefined }) {
  const { copied, copy } = useCopy()
  const handleCopy = () => copy(prdToMarkdown(prd))
  return (
    <Card size="small" style={{ marginTop: 12 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <Title level={5} style={{ margin: 0 }}>{prd?.title || '未命名 PRD'}</Title>
        <Button
          type="text"
          size="small"
          icon={copied ? <CheckOutlined /> : <CopyOutlined />}
          onClick={handleCopy}
        >
          {copied ? '已复制' : '复制 PRD'}
        </Button>
      </div>
      <div style={{ marginBottom: 8 }}>
        <Text type="secondary">目标</Text>
        <div><Text>{prd?.goal || '—'}</Text></div>
      </div>
      <div style={{ marginBottom: 8 }}>
        <Text type="secondary">范围</Text>
        <div><Text>{prd?.scope || '—'}</Text></div>
      </div>
      <Divider style={{ margin: '8px 0' }} />
      <ListField label="假设" items={prd?.assumptions} color="gold" />
      <ListField label="约束" items={prd?.constraints} color="orange" />
      <ListField label="API 端点" items={prd?.api_endpoints} color="blue" />
      <ListField label="遗留问题" items={prd?.open_questions} color="red" />
    </Card>
  )
}

/** 带颜色标签的字符串列表字段 */
function ListField({ label, items, color }: { label: string; items?: string[]; color: string }) {
  const arr = items ?? []
  return (
    <div style={{ marginBottom: 8 }}>
      <Text type="secondary">{label}（{arr.length}）</Text>
      {arr.length === 0 ? (
        <div><Text type="secondary">无</Text></div>
      ) : (
        <ul style={{ margin: '4px 0 0', paddingLeft: 16 }}>
          {arr.map((item, i) => (
            <li key={i} style={{ marginBottom: 2 }}>
              <Tag color={color} style={{ marginInlineEnd: 4 }}>{label.charAt(0)}</Tag>
              <Text>{item}</Text>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

/** 把 PRD 序列化为 Markdown 文本（供复制） */
function prdToMarkdown(prd: PRD | undefined): string {
  if (!prd) return ''
  const lines: string[] = []
  lines.push(`# ${prd.title || '未命名 PRD'}`)
  lines.push('')
  lines.push('## 目标')
  lines.push(prd.goal || '—')
  lines.push('')
  lines.push('## 范围')
  lines.push(prd.scope || '—')
  lines.push('')
  const section = (title: string, items?: string[]) => {
    lines.push(`## ${title}`)
    if (!items || items.length === 0) {
      lines.push('- 无')
    } else {
      items.forEach((it) => lines.push(`- ${it}`))
    }
    lines.push('')
  }
  section('假设', prd.assumptions)
  section('约束', prd.constraints)
  section('API 端点', prd.api_endpoints)
  section('遗留问题', prd.open_questions)
  return lines.join('\n')
}

/* ============================ OpenAPI 区域 ============================ */

function OpenAPISection({ yaml }: { yaml: string | undefined }) {
  const { copied, copy } = useCopy()
  const text = yaml || '# 暂无 OpenAPI'
  const handleCopy = () => copy(text)
  return (
    <Card size="small" title="OpenAPI 片段" style={{ marginTop: 12 }} extra={
      <Button
        type="text"
        size="small"
        icon={copied ? <CheckOutlined /> : <CopyOutlined />}
        onClick={handleCopy}
      >
        {copied ? '已复制' : '复制 OpenAPI'}
      </Button>
    }>
      <pre className="code-block yaml-code" style={{ margin: 0, fontSize: 12, maxHeight: 300, overflow: 'auto' }}>{highlightYaml(text)}</pre>
    </Card>
  )
}

/**
 * YAML 简单语法高亮：键名蓝、字符串绿、注释灰，其余默认色。按行处理。
 */
function highlightYaml(text: string): ReactNode {
  const lines = text.split('\n')
  return (
    <>
      {lines.map((line, i) => (
        <span key={i} className="yaml-line">
          {renderYamlLine(line)}
        </span>
      ))}
    </>
  )
}

function renderYamlLine(line: string): ReactNode {
  const commentOnly = line.match(/^(\s*)(#.*)$/)
  if (commentOnly) {
    return (
      <>
        {commentOnly[1]}
        <span style={{ color: '#8b949e' }}>{commentOnly[2]}</span>
      </>
    )
  }
  const kv = line.match(/^(\s*)([\w.-]+):(.*)$/)
  if (kv) {
    return (
      <>
        {kv[1]}
        <span style={{ color: '#79c0ff' }}>{kv[2]}</span>
        <span>:</span>
        {renderValue(kv[3])}
      </>
    )
  }
  const li = line.match(/^(\s*-\s+)(.*)$/)
  if (li) {
    return (
      <>
        {li[1]}
        {renderValue(' ' + li[2])}
      </>
    )
  }
  return renderValue(line)
}

function renderValue(valuePart: string): ReactNode {
  const { main, comment } = splitComment(valuePart)
  const strMatch = main.match(/^(\s*)("[^"]*"|'[^']*')(.*)$/)
  if (strMatch) {
    return (
      <>
        {strMatch[1]}
        <span style={{ color: '#a5d6ff' }}>{strMatch[2]}</span>
        {strMatch[3]}
        {comment ? <span style={{ color: '#8b949e' }}>{comment}</span> : null}
      </>
    )
  }
  return (
    <>
      {main}
      {comment ? <span style={{ color: '#8b949e' }}>{comment}</span> : null}
    </>
  )
}

function splitComment(valuePart: string): { main: string; comment: string } {
  let inDouble = false
  let inSingle = false
  for (let i = 0; i < valuePart.length; i++) {
    const ch = valuePart[i]
    if (ch === '"' && !inSingle) inDouble = !inDouble
    else if (ch === "'" && !inDouble) inSingle = !inSingle
    else if (ch === '#' && !inDouble && !inSingle) {
      const prev = valuePart[i - 1]
      if (prev === undefined || prev === ' ' || prev === '\t') {
        return { main: valuePart.slice(0, i), comment: valuePart.slice(i) }
      }
    }
  }
  return { main: valuePart, comment: '' }
}
