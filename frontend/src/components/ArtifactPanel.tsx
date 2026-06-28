// 右下：PRD 结构化预览 + OpenAPI 语法高亮 + 一键复制 + 借调入口
import type { ReactNode } from 'react'
import { useMeeting } from '../store/MeetingContext.tsx'
import type { PRD } from '../types/events.ts'
import { useCopy } from '../hooks/useCopy.ts'

interface ArtifactPanelProps {
  onOpenBorrow: () => void
}

export function ArtifactPanel({ onOpenBorrow }: ArtifactPanelProps) {
  const { store } = useMeeting()
  const artifact = store.meeting?.artifact

  return (
    <section className="panel artifact-panel">
      <div className="panel-title">
        产物预览
        <button type="button" className="btn btn-ghost borrow-btn" onClick={onOpenBorrow}>
          借调专家
        </button>
      </div>
      {!artifact ? (
        <div className="empty-hint">会议进行中，产出物将在 produce 阶段生成</div>
      ) : (
        <div className="artifact-body">
          <PRDSection prd={artifact.prd} />
          <OpenAPISection yaml={artifact.openapi} />
        </div>
      )}
    </section>
  )
}

/* ============================ PRD 区域 ============================ */

/** 列表字段图标 */
const LIST_ICONS: { icon: string; cls: string }[] = [
  { icon: '◆', cls: 'icon-assumption' },
  { icon: '■', cls: 'icon-constraint' },
  { icon: '→', cls: 'icon-api' },
  { icon: '?', cls: 'icon-question' },
]

function PRDSection({ prd }: { prd: PRD | undefined }) {
  const { copied, copy } = useCopy()
  const handleCopy = () => copy(prdToMarkdown(prd))
  return (
    <div className="prd-block">
      <div className="prd-head">
        <div className="prd-title">{prd?.title || '未命名 PRD'}</div>
        <button type="button" className="btn btn-ghost copy-btn" onClick={handleCopy}>
          {copied ? '已复制' : '复制 PRD'}
        </button>
      </div>
      <div className="prd-field">
        <span className="field-label">目标</span>
        <div className="field-value">{prd?.goal || '—'}</div>
      </div>
      <div className="prd-field">
        <span className="field-label">范围</span>
        <div className="field-value">{prd?.scope || '—'}</div>
      </div>
      <ListField icon={LIST_ICONS[0]} label="假设" items={prd?.assumptions} />
      <ListField icon={LIST_ICONS[1]} label="约束" items={prd?.constraints} />
      <ListField icon={LIST_ICONS[2]} label="API 端点" items={prd?.api_endpoints} />
      <ListField icon={LIST_ICONS[3]} label="遗留问题" items={prd?.open_questions} />
    </div>
  )
}

/** 带图标的字符串列表字段 */
function ListField({
  icon,
  label,
  items,
}: {
  icon: { icon: string; cls: string }
  label: string
  items?: string[]
}) {
  const arr = items ?? []
  return (
    <div className="prd-field">
      <span className="field-label">
        {label}（{arr.length}）
      </span>
      <ul className="prd-list">
        {arr.length === 0 && <li className="muted">无</li>}
        {arr.map((item, i) => (
          <li key={i}>
            <span className={`list-icon ${icon.cls}`}>{icon.icon}</span>
            <span className="list-text">{item}</span>
          </li>
        ))}
      </ul>
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
    <div className="openapi-block">
      <div className="openapi-head">
        <span className="field-label">OpenAPI 片段</span>
        <button type="button" className="btn btn-ghost copy-btn" onClick={handleCopy}>
          {copied ? '已复制' : '复制 OpenAPI'}
        </button>
      </div>
      <pre className="code-block yaml-code">{highlightYaml(text)}</pre>
    </div>
  )
}

/**
 * YAML 简单语法高亮：键名蓝、字符串绿、注释灰，其余默认色。按行处理。
 * 不引入外部库，仅用正则做 key:value 拆分。
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

/** 处理单行：整行注释 / key:value / 列表项 / 普通行 */
function renderYamlLine(line: string): ReactNode {
  // 整行注释（含前导空白）
  const commentOnly = line.match(/^(\s*)(#.*)$/)
  if (commentOnly) {
    return (
      <>
        {commentOnly[1]}
        <span className="yaml-comment">{commentOnly[2]}</span>
      </>
    )
  }
  // key: value
  const kv = line.match(/^(\s*)([\w.-]+):(.*)$/)
  if (kv) {
    return (
      <>
        {kv[1]}
        <span className="yaml-key">{kv[2]}</span>
        <span className="yaml-colon">:</span>
        {renderValue(kv[3])}
      </>
    )
  }
  // 列表项
  const li = line.match(/^(\s*-\s+)(.*)$/)
  if (li) {
    return (
      <>
        {li[1]}
        {renderValue(' ' + li[2])}
      </>
    )
  }
  // 其余：高亮行内字符串与注释
  return renderValue(line)
}

/** 处理值部分：剥离行内注释，高亮引号字符串 */
function renderValue(valuePart: string): ReactNode {
  const { main, comment } = splitComment(valuePart)
  const strMatch = main.match(/^(\s*)("[^"]*"|'[^']*')(.*)$/)
  if (strMatch) {
    return (
      <>
        {strMatch[1]}
        <span className="yaml-string">{strMatch[2]}</span>
        {strMatch[3]}
        {comment ? <span className="yaml-comment">{comment}</span> : null}
      </>
    )
  }
  return (
    <>
      {main}
      {comment ? <span className="yaml-comment">{comment}</span> : null}
    </>
  )
}

/** 把值中的行内注释拆分出来（引号外的 # 视为注释起点） */
function splitComment(valuePart: string): { main: string; comment: string } {
  let inDouble = false
  let inSingle = false
  for (let i = 0; i < valuePart.length; i++) {
    const ch = valuePart[i]
    if (ch === '"' && !inSingle) inDouble = !inDouble
    else if (ch === "'" && !inDouble) inSingle = !inSingle
    else if (ch === '#' && !inDouble && !inSingle) {
      const prev = valuePart[i - 1]
      // # 前为空白或行首才算注释起点
      if (prev === undefined || prev === ' ' || prev === '\t') {
        return { main: valuePart.slice(0, i), comment: valuePart.slice(i) }
      }
    }
  }
  return { main: valuePart, comment: '' }
}
