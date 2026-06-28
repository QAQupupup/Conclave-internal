// 报告查看器：可折叠的会议完整报告，支持下载 Markdown
// 展示会议信息、执行摘要、议题澄清、团队讨论、冲突与裁决、证据对照、最终产出
import { useState } from 'react'
import type { ReactNode } from 'react'
import { useMeeting } from '../store/MeetingContext.tsx'
import { LogicGraph } from './LogicGraph.tsx'
import { formatDateTime } from '../lib/format.ts'
import { downloadFile } from '../lib/download.ts'

/** 可折叠面板 */
function CollapsibleSection({ title, children, defaultOpen = false }: {
  title: string
  children: ReactNode
  defaultOpen?: boolean
}) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="report-section">
      <div className="report-section-header" onClick={() => setOpen(!open)}>
        <span className={`report-toggle ${open ? 'open' : ''}`}>▶</span>
        <span className="report-section-title">{title}</span>
      </div>
      {open && <div className="report-section-body">{children}</div>}
    </div>
  )
}

/** 格式化时间（使用统一的 lib/format，保持单一数据源） */
const fmtTime = formatDateTime

/** 报告转 Markdown */
function reportToMarkdown(state: any): string {
  let md = `# 会议报告：${state.topic || ''}\n\n`
  md += `> 会议ID: ${state.meeting_id}\n`
  md += `> 状态: ${state.status} | 阶段: ${state.stage}\n`
  if (state.clarified_topic) md += `> 澄清议题: ${state.clarified_topic}\n`
  md += '\n---\n\n'

  // 关键问题
  if (state.key_questions?.length) {
    md += '## 关键问题\n'
    state.key_questions.forEach((q: string, i: number) => {
      md += `${i + 1}. ${q}\n`
    })
    md += '\n'
  }

  // 团队配置
  if (state.team_config?.length) {
    md += '## 团队配置\n'
    state.team_config.forEach((m: any) => {
      md += `- **${m.role}**: ${m.stance}\n`
    })
    md += '\n'
  }

  // 发言记录
  if (state.messages?.length) {
    md += '## 讨论记录\n'
    state.messages.forEach((msg: any) => {
      md += `### [${msg.stage || ''}] ${msg.agent_role || msg.role || ''}\n`
      md += `${msg.content || ''}\n\n`
    })
  }

  // 冲突
  if (state.conflicts?.length) {
    md += '## 冲突点\n'
    state.conflicts.forEach((c: any, i: number) => {
      md += `${i + 1}. **${c.summary || c.description || ''}** (${c.type || c.conflict_type || ''})\n`
      md += `   - A方: ${c.side_a || ''}\n`
      md += `   - B方: ${c.side_b || ''}\n\n`
    })
  }

  // 裁决
  if (state.decision_record?.decisions?.length) {
    md += '## 裁决结果\n'
    state.decision_record.decisions.forEach((d: any, i: number) => {
      md += `${i + 1}. **${d.verdict}**: ${d.rationale || ''}\n`
    })
    if (state.decision_record.adopted_claims?.length) {
      md += '\n### 采纳主张\n'
      state.decision_record.adopted_claims.forEach((c: string) => {
        md += `- ${c}\n`
      })
    }
    md += '\n'
  }

  // 产出物
  if (state.artifact) {
    md += '## 最终产出\n'
    md += '```json\n' + JSON.stringify(state.artifact, null, 2) + '\n```\n'
  }

  return md
}

/** 阶段中文标签 */
const STAGE_NAMES: Record<string, string> = {
  clarify: '议题澄清',
  intra_team: '团队内部讨论',
  cross_team: '跨队辩论',
  evidence_check: '证据对照',
  arbitrate: '仲裁裁决',
  produce: '产出阶段',
}

export function ReportViewer() {
  const { store } = useMeeting()
  const state = store.meeting
  if (!state) return null

  // llm_trace 与多类型 artifact 扩展字段不在严格类型中，统一按 any 访问
  const ext = state as any

  const messages = state.messages || []
  const stageMessages = messages.reduce((acc: Record<string, any[]>, msg: any) => {
    const stage = msg.stage || 'unknown'
    if (!acc[stage]) acc[stage] = []
    acc[stage].push(msg)
    return acc
  }, {})

  return (
    <div className="report-viewer">
      <div className="report-toolbar">
        <h2>会议报告</h2>
        <button
          className="btn btn-sm"
          onClick={() => downloadFile(`report_${state.meeting_id}.md`, reportToMarkdown(state))}
        >
          下载 Markdown
        </button>
      </div>

      {/* 会议信息 */}
      <CollapsibleSection title="会议信息" defaultOpen>
        <div className="report-info">
          <div><strong>议题:</strong> {state.topic}</div>
          <div><strong>会议ID:</strong> {state.meeting_id}</div>
          <div><strong>状态:</strong> {state.status}</div>
          <div><strong>阶段:</strong> {state.stage}</div>
          {state.clarified_topic && <div><strong>澄清议题:</strong> {state.clarified_topic}</div>}
        </div>
      </CollapsibleSection>

      {/* 执行摘要 */}
      <CollapsibleSection title="执行摘要" defaultOpen>
        <div className="report-summary">
          {state.confidence_flags &&
            Object.entries(state.confidence_flags).map(([stage, conf]) => (
              <div key={stage} className="summary-row">
                <span className="summary-stage">{STAGE_NAMES[stage] || stage}</span>
                <span className={`summary-conf ${conf}`}>{conf}</span>
              </div>
            ))}
          {ext.llm_trace && (
            <div className="trace-summary">
              <div>LLM 调用: {ext.llm_trace.total_calls || 0} 次</div>
              <div>成功率: {ext.llm_trace.success_rate || 'N/A'}</div>
              {ext.llm_trace.total_tokens > 0 && (
                <div>
                  Token: {ext.llm_trace.total_tokens} (输入 {ext.llm_trace.total_input_tokens} + 输出{' '}
                  {ext.llm_trace.total_output_tokens})
                </div>
              )}
            </div>
          )}
        </div>
      </CollapsibleSection>

      {/* 关键问题 */}
      {state.key_questions && state.key_questions.length > 0 && (
        <CollapsibleSection title="关键问题">
          <ol className="report-questions">
            {state.key_questions.map((q: string, i: number) => (
              <li key={i}>{q}</li>
            ))}
          </ol>
        </CollapsibleSection>
      )}

      {/* 团队配置 */}
      {state.team_config && state.team_config.length > 0 && (
        <CollapsibleSection title="团队配置">
          <div className="report-team">
            {state.team_config.map((m: any, i: number) => (
              <div key={i} className="team-member">
                <span className="member-role">{m.role}</span>
                <span className="member-stance">{m.stance}</span>
              </div>
            ))}
          </div>
        </CollapsibleSection>
      )}

      {/* 各阶段发言 */}
      {Object.entries(stageMessages).map(([stage, msgs]) => (
        <CollapsibleSection key={stage} title={STAGE_NAMES[stage] || stage}>
          <div className="report-messages">
            {msgs.map((msg: any, i: number) => (
              <div key={i} className="report-message">
                <div className="message-header">
                  <span className="message-role">{msg.agent_role || msg.role}</span>
                  <span className="message-time">{fmtTime(msg.created_at || msg.ts || '')}</span>
                </div>
                <div className="message-content">{msg.content}</div>
              </div>
            ))}
          </div>
        </CollapsibleSection>
      ))}

      {/* 逻辑关系图：主张 → 冲突 → 裁决 */}
      {state.conflicts && state.conflicts.length > 0 && (
        <CollapsibleSection title="逻辑关系图（主张→冲突→裁决）">
          <LogicGraph />
        </CollapsibleSection>
      )}

      {/* 最终产出：根据 deliverable_type 展示不同内容 */}
      {ext.artifact && (
        <CollapsibleSection title="最终产出" defaultOpen>
          <div className="report-artifact">
            {ext.artifact.prd && (
              <div className="artifact-block">
                <h4>PRD: {ext.artifact.prd.title}</h4>
                <p>
                  <strong>目标:</strong> {ext.artifact.prd.goal}
                </p>
                {ext.artifact.prd.api_endpoints?.length > 0 && (
                  <div>
                    <strong>API 端点:</strong>
                    <ul>
                      {ext.artifact.prd.api_endpoints.map((ep: string, i: number) => (
                        <li key={i}>{ep}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}
            {ext.artifact.openapi && (
              <div className="artifact-block">
                <h4>OpenAPI</h4>
                <pre className="code-block">{ext.artifact.openapi}</pre>
              </div>
            )}
            {ext.artifact.design_doc && (
              <div className="artifact-block">
                <h4>{ext.artifact.design_doc.title}</h4>
                <pre>{JSON.stringify(ext.artifact.design_doc, null, 2)}</pre>
              </div>
            )}
            {ext.artifact.comprehensive && (
              <div className="artifact-block">
                <h4>{ext.artifact.comprehensive.title}</h4>
                <pre>{JSON.stringify(ext.artifact.comprehensive, null, 2)}</pre>
              </div>
            )}
            {ext.artifact.research_report && (
              <div className="artifact-block">
                <h4>{ext.artifact.research_report.title}</h4>
                <pre>{JSON.stringify(ext.artifact.research_report, null, 2)}</pre>
              </div>
            )}
            {ext.artifact.business_report && (
              <div className="artifact-block">
                <h4>{ext.artifact.business_report.title}</h4>
                <pre>{JSON.stringify(ext.artifact.business_report, null, 2)}</pre>
              </div>
            )}
            {ext.artifact.code_analysis && (
              <div className="artifact-block">
                <h4>{ext.artifact.code_analysis.title}</h4>
                <p>{ext.artifact.code_analysis.description}</p>
                <pre className="code-block">{ext.artifact.code_analysis.code}</pre>
                {ext.artifact.execution && (
                  <div className="execution-result">
                    <h5>执行结果 (exit={ext.artifact.execution.exit_code})</h5>
                    <pre className="code-block">{ext.artifact.execution.stdout}</pre>
                    {ext.artifact.execution.stderr && (
                      <pre className="code-block error">{ext.artifact.execution.stderr}</pre>
                    )}
                  </div>
                )}
              </div>
            )}
            {ext.artifact.tested_system && (
              <div className="artifact-block">
                <h4>{ext.artifact.tested_system.title}</h4>
                <p>{ext.artifact.tested_system.description}</p>
                <h5>主代码</h5>
                <pre className="code-block">{ext.artifact.tested_system.main_code}</pre>
                <h5>测试代码</h5>
                <pre className="code-block">{ext.artifact.tested_system.test_code}</pre>
                {ext.artifact.execution && (
                  <div className="execution-result">
                    <h5>测试结果 (exit={ext.artifact.execution.exit_code})</h5>
                    <pre className="code-block">{ext.artifact.execution.stdout}</pre>
                    {ext.artifact.execution.stderr && (
                      <pre className="code-block error">{ext.artifact.execution.stderr}</pre>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>
        </CollapsibleSection>
      )}
    </div>
  )
}
