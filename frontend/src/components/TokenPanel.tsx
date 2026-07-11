// Token 可视化面板：展示 LLM 调用追踪的 Token 消耗、阶段柱状图、调用明细
// 通过 GET /meetings/:id/trace 拉取数据，每 5s 轮询刷新
// 使用 AntD Card + Progress + Statistic + Tag + Row/Col + Typography
import { useState, useEffect } from 'react'
import { Card, Progress, Statistic, Tag, Row, Col, Typography, Space } from 'antd'
import { useMeeting } from '../store/MeetingContext.tsx'
import { request, getMeetingModel, getLLMBalance } from '../lib/api.ts'
import type { MeetingModelConfig, LLMBalanceResponse } from '../lib/api.ts'

const { Text } = Typography

interface TraceData {
  meeting_id: string
  summary: {
    total_calls: number
    valid_calls: number
    fallback_calls: number
    success_rate: string
    avg_latency_ms: number
    max_latency_ms: number
    total_input_tokens: number
    total_output_tokens: number
    total_tokens: number
    avg_tokens_per_call: number
    stage_stats: Record<string, any>
  }
  calls: Array<{
    call_id: string
    stage: string
    model: string
    temperature: number
    latency_ms: number
    input_tokens: number
    output_tokens: number
    total_tokens: number
    validation_status: string
  }>
}

interface BudgetData {
  budget: number
  used: number
  remaining: number
  percentage: number
  status: 'normal' | 'warning' | 'exceeded'
  total_calls: number
}

/** 阶段英文ID → 中文标签映射（含所有 schema_hint 阶段名） */
const STAGE_LABELS: Record<string, string> = {
  clarify: '澄清议题',
  intra_team: '队内发言',
  cross_team: '跨队辩论',
  evidence_check: '证据对照',
  arbitrate: '仲裁裁决',
  produce_prd_openapi: '产出PRD',
  produce_code_analysis: '产出代码分析',
  produce_data_science: '产出数据科学分析',
  produce_tested_system: '产出可测系统',
  produce_deployable_service: '产出可部署服务',
  produce_design_doc: '产出设计文档',
  produce_comprehensive: '产出综合文档',
  produce_research_report: '产出研究报告',
  produce_business_report: '产出商业报告',
  meta_next_stage: '阶段路由',
}

function stageLabel(stage: string): string {
  if (STAGE_LABELS[stage]) return STAGE_LABELS[stage]
  if (stage.startsWith('produce_')) {
    const suffix = stage.slice('produce_'.length)
    return `产出·${suffix}`
  }
  return stage
}

/** 验证状态中文标签 */
function statusLabel(status: string): { label: string; color: string } {
  switch (status) {
    case 'valid': return { label: '成功', color: 'green' }
    case 'invalid': return { label: '失败', color: 'red' }
    case 'fallback_stub': return { label: '降级', color: 'orange' }
    default: return { label: status, color: 'default' }
  }
}

export function TokenPanel() {
  const { meetingId } = useMeeting()
  const [trace, setTrace] = useState<TraceData | null>(null)
  const [budget, setBudget] = useState<BudgetData | null>(null)
  const [modelConfig, setModelConfig] = useState<MeetingModelConfig | null>(null)
  const [balance, setBalance] = useState<LLMBalanceResponse | null>(null)

  const refresh = async () => {
    if (!meetingId) return
    try {
      const [data, bd] = await Promise.all([
        request<TraceData>(`/meetings/${encodeURIComponent(meetingId)}/trace`),
        request<BudgetData>(`/meetings/${encodeURIComponent(meetingId)}/budget`),
      ])
      setTrace(data)
      setBudget(bd)
    } catch {
      // 静默：轮询失败不影响 UI
    }
  }

  // 加载当前模型配置和余额（仅首次，不轮询避免浪费请求）
  useEffect(() => {
    if (!meetingId) return
    let cancelled = false
    void (async () => {
      try {
        const cfg = await getMeetingModel(meetingId)
        if (!cancelled) setModelConfig(cfg)
        try {
          const bal = await getLLMBalance({ provider: cfg.provider_id })
          if (!cancelled) setBalance(bal)
        } catch {
          // 余额查询失败静默
        }
      } catch {
        // 模型配置获取失败静默
      }
    })()
    return () => { cancelled = true }
  }, [meetingId])

  useEffect(() => {
    refresh()
    const timer = setInterval(refresh, 5000)
    return () => clearInterval(timer)
  }, [meetingId])

  if (!trace) {
    return (
      <div style={{ textAlign: 'center', padding: 24 }}>
        <Text type="secondary">暂无追踪数据</Text>
      </div>
    )
  }

  const s = trace.summary
  const stages = Object.entries(s.stage_stats || {})
  const maxTokens = Math.max(
    ...stages.map(([, v]: any) => (v.input_tokens || 0) + (v.output_tokens || 0)),
    1,
  )

  const budgetStatus = budget?.status === 'exceeded' ? 'exception' : budget?.status === 'warning' ? 'active' : 'normal'

  return (
    <div className="token-panel">
      {/* 当前模型信息条 */}
      {modelConfig && (
        <Card size="small" style={{ marginBottom: 12 }}>
          <Space wrap>
            <Text type="secondary">模型</Text>
            <Text strong ellipsis style={{ maxWidth: 200 }} title={modelConfig.model}>{modelConfig.model}</Text>
            {modelConfig.has_custom_key && <Tag color="purple">自定义Key</Tag>}
            {balance?.supported && balance.balance !== null && (
              <Text type={balance.balance < 1 ? 'danger' : 'secondary'}>
                余额 {balance.currency === 'CNY' ? '¥' : '$'}{balance.balance.toFixed(2)}
              </Text>
            )}
          </Space>
        </Card>
      )}

      {/* 预算进度条 */}
      {budget && budget.budget > 0 && (
        <Card size="small" style={{ marginBottom: 12 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
            <Text type="secondary">预算 {budget.used.toLocaleString()} / {budget.budget.toLocaleString()}</Text>
            <Text strong>{budget.percentage}%</Text>
          </div>
          <Progress
            percent={Math.min(budget.percentage, 100)}
            showInfo={false}
            status={budgetStatus as any}
            strokeColor={budget.status === 'exceeded' ? '#ff4d4f' : budget.status === 'warning' ? '#faad14' : undefined}
          />
          <Text type="secondary" style={{ fontSize: 12 }}>
            剩余 {budget.remaining.toLocaleString()} · {budget.total_calls} 次调用
          </Text>
        </Card>
      )}

      {/* 总览卡片 */}
      <Row gutter={[8, 8]} style={{ marginBottom: 12 }}>
        <Col span={6}>
          <Card size="small">
            <Statistic title="总 Token" value={s.total_tokens || 0} valueStyle={{ fontSize: 20 }} />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic title="输入" value={s.total_input_tokens || 0} valueStyle={{ fontSize: 20, color: '#52c41a' }} />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic title="输出" value={s.total_output_tokens || 0} valueStyle={{ fontSize: 20, color: '#1890ff' }} />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic title="调用数" value={s.total_calls || 0} valueStyle={{ fontSize: 20 }} />
          </Card>
        </Col>
      </Row>

      {/* 按阶段柱状图 */}
      {stages.length > 0 && (
        <Card size="small" title="按阶段消耗" style={{ marginBottom: 12 }}>
          {stages.map(([stage, v]: any) => {
            const tokens = (v.input_tokens || 0) + (v.output_tokens || 0)
            const pct = (tokens / maxTokens) * 100
            const label = stageLabel(stage)
            return (
              <div key={stage} style={{ marginBottom: 8 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 2 }}>
                  <Text style={{ fontSize: 12 }}>{label}</Text>
                  <Text type="secondary" style={{ fontSize: 12 }}>{tokens.toLocaleString()}</Text>
                </div>
                <Progress percent={pct} showInfo={false} strokeColor="#4f46e5" size="small" />
              </div>
            )
          })}
        </Card>
      )}

      {/* 调用列表 */}
      {trace.calls && trace.calls.length > 0 && (
        <Card size="small" title="调用明细">
          <div style={{ maxHeight: 300, overflowY: 'auto' }}>
            {trace.calls.map((c, i) => {
              const sl = statusLabel(c.validation_status)
              const label = stageLabel(c.stage)
              return (
                <div
                  key={c.call_id || i}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 8,
                    padding: '6px 0',
                    borderBottom: '1px solid var(--border-color, #e5e7eb)',
                    fontSize: 12,
                  }}
                  title={`${label} · ${c.total_tokens} tok · ${c.latency_ms}ms`}
                >
                  <Text style={{ flex: 1, fontSize: 12 }}>{label}</Text>
                  <Text type="secondary" style={{ fontSize: 12 }}>{(c.total_tokens || 0).toLocaleString()} tok</Text>
                  <Text type="secondary" style={{ fontSize: 12 }}>{c.latency_ms}ms</Text>
                  <Tag color={sl.color} style={{ margin: 0 }}>{sl.label}</Tag>
                </div>
              )
            })}
          </div>
        </Card>
      )}
    </div>
  )
}
