// 报告查看器：可折叠的会议完整报告，支持下载 Markdown
// 展示会议信息、执行摘要、议题澄清、团队讨论、冲突与裁决、证据对照、最终产出
// 使用 AntD Card + Typography + Divider + Button + Tag + Rate + Descriptions
import { Card, Button, Divider, Tag, Typography, Rate, Descriptions, Space } from 'antd'
import { DownloadOutlined } from '@ant-design/icons'
import { useState } from 'react'
import { useMeeting } from '../store/MeetingContext.tsx'
import { LogicGraph } from './LogicGraph.tsx'
import { CollapsibleSection } from './CollapsibleSection.tsx'
import { formatDateTime } from '../lib/format.ts'
import { downloadFile } from '../lib/download.ts'
import { STAGE_NAMES } from '../constants.ts'
import { renderMessageContent } from './MessageContent.tsx'

const { Text, Title, Paragraph } = Typography

/** 格式化时间（使用统一的 lib/format，保持单一数据源） */
const fmtTime = formatDateTime

/** 报告转 Markdown */
function reportToMarkdown(state: any): string {
  let md = `# 会议报告：${state.topic || ''}\n\n`
  md += `> 会议ID: ${state.meeting_id}\n`
  md += `> 状态: ${state.status} | 阶段: ${state.stage}\n`
  if (state.clarified_topic) md += `> 澄清议题: ${state.clarified_topic}\n`
  md += '\n---\n\n'

  if (state.key_questions?.length) {
    md += '## 关键问题\n'
    state.key_questions.forEach((q: string, i: number) => {
      md += `${i + 1}. ${q}\n`
    })
    md += '\n'
  }

  if (state.team_config?.length) {
    md += '## 团队配置\n'
    state.team_config.forEach((m: any) => {
      md += `- **${m.role}**: ${m.stance}\n`
    })
    md += '\n'
  }

  if (state.messages?.length) {
    md += '## 讨论记录\n'
    state.messages.forEach((msg: any) => {
      md += `### [${msg.stage || ''}] ${msg.agent_role || msg.role || ''}\n`
      md += `${msg.content || ''}\n\n`
    })
  }

  if (state.conflicts?.length) {
    md += '## 冲突点\n'
    state.conflicts.forEach((c: any, i: number) => {
      md += `${i + 1}. **${c.summary || c.description || ''}** (${c.type || c.conflict_type || ''})\n`
      md += `   - A方: ${c.side_a || ''}\n`
      md += `   - B方: ${c.side_b || ''}\n\n`
    })
  }

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

  if (state.artifact) {
    md += '## 最终产出\n'
    md += '```json\n' + JSON.stringify(state.artifact, null, 2) + '\n```\n'
  }

  return md
}

export function ReportViewer() {
  const { store } = useMeeting()
  const state = store.meeting
  const [rating, setRating] = useState<number>(() => {
    try {
      const ratings = JSON.parse(localStorage.getItem('conclave_ratings') || '{}')
      return ratings[state?.meeting_id ?? ''] || 0
    } catch { return 0 }
  })

  if (!state) return null

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
      <div className="report-viewer-header">
        <Title level={3} className="report-viewer-title">会议报告</Title>
        <Button
          icon={<DownloadOutlined />}
          onClick={() => downloadFile(`report_${state.meeting_id}.md`, reportToMarkdown(state))}
        >
          下载 Markdown
        </Button>
      </div>

      {/* 会议信息 */}
      <CollapsibleSection title="会议信息" defaultOpen>
        <Descriptions column={1} size="small" bordered>
          <Descriptions.Item label="议题">{state.topic}</Descriptions.Item>
          <Descriptions.Item label="会议ID">{state.meeting_id}</Descriptions.Item>
          <Descriptions.Item label="状态">
            <Tag color={state.status === 'done' ? 'green' : 'blue'}>{state.status}</Tag>
          </Descriptions.Item>
          <Descriptions.Item label="阶段">{state.stage}</Descriptions.Item>
          {state.clarified_topic && (
            <Descriptions.Item label="澄清议题">{state.clarified_topic}</Descriptions.Item>
          )}
        </Descriptions>
      </CollapsibleSection>

      {/* 执行摘要 */}
      <CollapsibleSection title="执行摘要" defaultOpen>
        <div>
          {state.confidence_flags &&
            Object.entries(state.confidence_flags).map(([stage, conf]) => (
              <div key={stage} className="report-viewer-confidence-row">
                <Text>{STAGE_NAMES[stage as keyof typeof STAGE_NAMES] || stage}</Text>
                <Tag color={conf === 'high' ? 'green' : conf === 'low' ? 'orange' : 'red'}>{String(conf)}</Tag>
              </div>
            ))}
          {ext.llm_trace && (
            <Card size="small" className="report-viewer-mt-8">
              <Space direction="vertical" size={4}>
                <Text>LLM 调用: {ext.llm_trace.total_calls || 0} 次</Text>
                <Text>成功率: {ext.llm_trace.success_rate || 'N/A'}</Text>
                {ext.llm_trace.total_tokens > 0 && (
                  <Text>
                    Token: {ext.llm_trace.total_tokens} (输入 {ext.llm_trace.total_input_tokens} + 输出{' '}
                    {ext.llm_trace.total_output_tokens})
                  </Text>
                )}
              </Space>
            </Card>
          )}
        </div>
      </CollapsibleSection>

      {/* 关键问题 */}
      {state.key_questions && state.key_questions.length > 0 && (
        <CollapsibleSection title="关键问题">
          <ol className="report-viewer-questions">
            {state.key_questions.map((q: string, i: number) => (
              <li key={i} className="report-viewer-question-item">{q}</li>
            ))}
          </ol>
        </CollapsibleSection>
      )}

      {/* 团队配置 */}
      {state.team_config && state.team_config.length > 0 && (
        <CollapsibleSection title="团队配置">
          <Space direction="vertical" className="report-viewer-w-full">
            {state.team_config.map((m: any, i: number) => (
              <div key={i} className="report-viewer-team-item">
                <Tag color="blue">{m.role}</Tag>
                <Text>{m.stance}</Text>
              </div>
            ))}
          </Space>
        </CollapsibleSection>
      )}

      {/* 各阶段发言 */}
      {Object.entries(stageMessages).map(([stage, msgs]) => (
        <CollapsibleSection key={stage} title={STAGE_NAMES[stage as keyof typeof STAGE_NAMES] || stage}>
          <Space direction="vertical" className="report-viewer-w-full" size={8}>
            {msgs.map((msg: any, i: number) => (
              <Card key={i} size="small">
                <div className="report-viewer-msg-header">
                  <Tag>{msg.agent_role || msg.role}</Tag>
                  <Text type="secondary" className="report-viewer-text-sm">{fmtTime(msg.created_at || msg.ts || '')}</Text>
                </div>
                <div>{renderMessageContent(msg.content)}</div>
              </Card>
            ))}
          </Space>
        </CollapsibleSection>
      ))}

      {/* 逻辑关系图 */}
      {state.conflicts && state.conflicts.length > 0 && (
        <CollapsibleSection title="逻辑关系图（主张→冲突→裁决）">
          <LogicGraph />
        </CollapsibleSection>
      )}

      {/* 最终产出 */}
      {ext.artifact && (
        <CollapsibleSection title="最终产出" defaultOpen>
          <div>
            {ext.artifact.prd && (
              <Card size="small" title={`PRD: ${ext.artifact.prd.title}`} className="report-viewer-mb-12">
                <Paragraph><Text strong>目标: </Text>{ext.artifact.prd.goal}</Paragraph>
                {ext.artifact.prd.api_endpoints?.length > 0 && (
                  <div>
                    <Text strong>API 端点:</Text>
                    <ul>
                      {ext.artifact.prd.api_endpoints.map((ep: string, i: number) => (
                        <li key={i}>{ep}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </Card>
            )}
            {ext.artifact.openapi && (
              <Card size="small" title="OpenAPI" className="report-viewer-mb-12">
                <pre className="code-block report-viewer-code">{ext.artifact.openapi}</pre>
              </Card>
            )}
            {ext.artifact.design_doc && (
              <Card size="small" title={ext.artifact.design_doc.title} className="report-viewer-mb-12">
                <pre className="code-block report-viewer-code">{JSON.stringify(ext.artifact.design_doc, null, 2)}</pre>
              </Card>
            )}
            {ext.artifact.comprehensive && (
              <Card size="small" title={ext.artifact.comprehensive.title} className="report-viewer-mb-12">
                <pre className="code-block report-viewer-code">{JSON.stringify(ext.artifact.comprehensive, null, 2)}</pre>
              </Card>
            )}
            {ext.artifact.research_report && (
              <Card size="small" title={ext.artifact.research_report.title} className="report-viewer-mb-12">
                <pre className="code-block report-viewer-code">{JSON.stringify(ext.artifact.research_report, null, 2)}</pre>
              </Card>
            )}
            {ext.artifact.business_report && (
              <Card size="small" title={ext.artifact.business_report.title} className="report-viewer-mb-12">
                <pre className="code-block report-viewer-code">{JSON.stringify(ext.artifact.business_report, null, 2)}</pre>
              </Card>
            )}
            {ext.artifact.code_analysis && (
              <Card size="small" title={ext.artifact.code_analysis.title} className="report-viewer-mb-12">
                <Paragraph>{ext.artifact.code_analysis.description}</Paragraph>
                <pre className="code-block report-viewer-code">{ext.artifact.code_analysis.code}</pre>
                {ext.artifact.execution && (
                  <Card size="small" title={`执行结果 (exit=${ext.artifact.execution.exit_code})`} className="report-viewer-mt-8">
                    <pre className="code-block report-viewer-code">{ext.artifact.execution.stdout}</pre>
                    {ext.artifact.execution.stderr && (
                      <pre className="code-block report-viewer-code-stderr">{ext.artifact.execution.stderr}</pre>
                    )}
                  </Card>
                )}
              </Card>
            )}
            {ext.artifact.tested_system && (
              <Card size="small" title={ext.artifact.tested_system.title} className="report-viewer-mb-12">
                <Paragraph>{ext.artifact.tested_system.description}</Paragraph>
                <Divider>主代码</Divider>
                <pre className="code-block report-viewer-code">{ext.artifact.tested_system.main_code}</pre>
                <Divider>测试代码</Divider>
                <pre className="code-block report-viewer-code">{ext.artifact.tested_system.test_code}</pre>
                {ext.artifact.execution && (
                  <Card size="small" title={`测试结果 (exit=${ext.artifact.execution.exit_code})`} className="report-viewer-mt-8">
                    <pre className="code-block report-viewer-code">{ext.artifact.execution.stdout}</pre>
                    {ext.artifact.execution.stderr && (
                      <pre className="code-block report-viewer-code-stderr">{ext.artifact.execution.stderr}</pre>
                    )}
                  </Card>
                )}
              </Card>
            )}
            {ext.artifact.deployable_service && (
              <Card size="small" title={ext.artifact.deployable_service.title || '可部署服务'} className="report-viewer-mb-12">
                {ext.artifact.deployable_service.description && (
                  <Paragraph>{ext.artifact.deployable_service.description}</Paragraph>
                )}

                {ext.artifact.deployment && (
                  <Card
                    size="small"
                    style={{
                      marginBottom: 12,
                      borderColor: ext.artifact.deployment.ok ? '#52c41a' : '#ff4d4f',
                    }}
                  >
                    <Space>
                      <span style={{
                        width: 8, height: 8, borderRadius: '50%',
                        background: ext.artifact.deployment.ok ? '#52c41a' : '#ff4d4f',
                        display: 'inline-block',
                      }} />
                      <Text strong>{ext.artifact.deployment.ok ? '服务已启动，可直接访问' : '服务启动失败'}</Text>
                    </Space>
                    {ext.artifact.deployment.ok && ext.artifact.deployment.access_url && (
                      <div className="report-viewer-mt-8">
                        <Text type="secondary">访问地址: </Text>
                        <a href={ext.artifact.deployment.access_url} target="_blank" rel="noopener noreferrer">
                          {ext.artifact.deployment.access_url} ↗
                        </a>
                      </div>
                    )}
                    {ext.artifact.deployment.credentials &&
                      (ext.artifact.deployment.credentials.username || ext.artifact.deployment.credentials.password) && (
                      <div className="report-viewer-mt-8">
                        <Space wrap>
                          <Text type="secondary">账号:</Text>
                          <Tag>{ext.artifact.deployment.credentials.username || '（无，需自行注册）'}</Tag>
                          {ext.artifact.deployment.credentials.password && (
                            <>
                              <Text type="secondary">密码:</Text>
                              <Tag>{ext.artifact.deployment.credentials.password}</Tag>
                            </>
                          )}
                          {ext.artifact.deployment.credentials.note && (
                            <Text type="secondary">({ext.artifact.deployment.credentials.note})</Text>
                          )}
                        </Space>
                      </div>
                    )}
                    {ext.artifact.review && (
                      <div className="report-viewer-mt-8">
                        <Text>代码审查: {ext.artifact.review.rounds}轮，</Text>
                        <Tag color={ext.artifact.review.passed ? 'green' : 'red'}>
                          {ext.artifact.review.passed ? '通过' : '存在未修复问题'}
                        </Tag>
                      </div>
                    )}
                    {!ext.artifact.deployment.ok && ext.artifact.deployment.error && (
                      <div className="report-viewer-mt-8">
                        <Text type="danger">错误: {ext.artifact.deployment.error}</Text>
                        {ext.artifact.deployment.logs && (
                          <details className="report-viewer-details">
                            <summary className="report-viewer-summary">查看启动日志</summary>
                            <pre className="code-block report-viewer-code-logs">{ext.artifact.deployment.logs}</pre>
                          </details>
                        )}
                      </div>
                    )}
                  </Card>
                )}

                <div className="report-viewer-mb-12">
                  <Space>
                    <Text>对本次产出评分:</Text>
                    <Rate
                      value={rating}
                      onChange={(val) => {
                        setRating(val)
                        try {
                          const ratings = JSON.parse(localStorage.getItem('conclave_ratings') || '{}')
                          ratings[state.meeting_id] = val
                          localStorage.setItem('conclave_ratings', JSON.stringify(ratings))
                        } catch { /* ignore */ }
                      }}
                    />
                    <Text type="secondary">（帮助系统改进产出质量）</Text>
                  </Space>
                </div>

                <Divider>应用代码 (app.py)</Divider>
                <pre className="code-block report-viewer-code">{ext.artifact.deployable_service.app_code}</pre>
                {ext.artifact.deployable_service.requirements_txt && (
                  <>
                    <Divider>requirements.txt</Divider>
                    <pre className="code-block report-viewer-code">{ext.artifact.deployable_service.requirements_txt}</pre>
                  </>
                )}
                {ext.artifact.deployable_service.dockerfile && (
                  <>
                    <Divider>Dockerfile</Divider>
                    <pre className="code-block report-viewer-code">{ext.artifact.deployable_service.dockerfile}</pre>
                  </>
                )}
                {ext.artifact.deployable_service.docker_compose && (
                  <>
                    <Divider>docker-compose.yml</Divider>
                    <pre className="code-block report-viewer-code">{ext.artifact.deployable_service.docker_compose}</pre>
                  </>
                )}
                {ext.artifact.execution && (
                  <Card size="small" title="部署结果" className="report-viewer-mt-8">
                    <pre className="code-block report-viewer-code">{ext.artifact.execution.stdout}</pre>
                    {ext.artifact.execution.stderr && (
                      <pre className="code-block report-viewer-code-stderr">{ext.artifact.execution.stderr}</pre>
                    )}
                  </Card>
                )}
              </Card>
            )}
            {ext.artifact.attachments && ext.artifact.attachments.length > 0 && (
              <Card size="small" title={`附件文件（${ext.artifact.attachments.length}）`}>
                <Space wrap>
                  {ext.artifact.attachments.map((att: any, i: number) => (
                    <a
                      key={i}
                      href={`/meetings/${ext.artifact.meeting_id}/attachments/${encodeURIComponent(att.filename)}`}
                      download={att.filename}
                      title={`${att.filename}（${(att.size / 1024).toFixed(1)} KB）`}
                    >
                      <Tag>{att.filename} <Text type="secondary">.{att.ext} · {(att.size / 1024).toFixed(1)} KB</Text></Tag>
                    </a>
                  ))}
                </Space>
              </Card>
            )}
          </div>
        </CollapsibleSection>
      )}
    </div>
  )
}
