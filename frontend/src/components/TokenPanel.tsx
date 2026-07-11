// Token 可视化面板：展示 LLM 调用追踪的 Token 消耗、阶段柱状图、调用明细
// 通过 GET /meetings/:id/trace 拉取数据，每 5s 轮询刷新
import { useState, useEffect } from 'react'
import { useMeeting } from '../store/MeetingContext.tsx'
import { request, getMeetingModel, getLLMBalance } from '../lib/api.ts'
import type { MeetingModelConfig, LLMBalanceResponse } from '../lib/api.ts'

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
  // 兜底：produce_xxx → 产出·xxx
  if (stage.startsWith('produce_')) {
    const suffix = stage.slice('produce_'.length)
    return `产出·${suffix}`
  }
  return stage
}

/** 验证状态中文标签 */
function statusLabel(status: string): { label: string; cls: string } {
  switch (status) {
    case 'valid': return { label: '成功', cls: 'valid' }
    case 'invalid': return { label: '失败', cls: 'invalid' }
    case 'fallback_stub': return { label: '降级', cls: 'fallback_stub' }
    default: return { label: status, cls: '' }
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
    } catch (e) {
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
        if (cancelled) setModelConfig(cfg)
        // 查询余额（用当前 provider）
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
    return <div className="token-panel-empty">暂无追踪数据</div>
  }

  const s = trace.summary
  const stages = Object.entries(s.stage_stats || {})
  const maxTokens = Math.max(
    ...stages.map(([, v]: any) => (v.input_tokens || 0) + (v.output_tokens || 0)),
    1,
  )

  return (
    <div className="token-panel">
      {/* 当前模型信息条 */}
      {modelConfig && (
        <div className="token-model-bar">
          <span className="token-model-label">模型</span>
          <span className="token-model-name" title={modelConfig.model}>{modelConfig.model}</span>
          {modelConfig.has_custom_key && <span className="custom-key-badge">自定义Key</span>}
          {balance?.supported && balance.balance !== null && (
            <span className={`token-model-balance${balance.balance < 1 ? ' low' : ''}`}>
              余额 {balance.currency === 'CNY' ? '¥' : '$'}{balance.balance.toFixed(2)}
            </span>
          )}
        </div>
      )}

      {/* 预算进度条 */}
      {budget && budget.budget > 0 && (
        <div className={`token-budget-bar ${budget.status}`}>
          <div className="budget-label">
            <span>预算 {budget.used.toLocaleString()} / {budget.budget.toLocaleString()}</span>
            <span className="budget-pct">{budget.percentage}%</span>
          </div>
          <div className="budget-track">
            <div className="budget-fill" style={{ width: `${Math.min(budget.percentage, 100)}%` }} />
          </div>
          <div className="budget-meta">
            剩余 {budget.remaining.toLocaleString()} · {budget.total_calls} 次调用
          </div>
        </div>
      )}

      {/* 总览卡片 */}
      <div className="token-cards">
        <div className="token-card">
          <div className="token-card-label">总 Token</div>
          <div className="token-card-value">{(s.total_tokens || 0).toLocaleString()}</div>
        </div>
        <div className="token-card">
          <div className="token-card-label">输入</div>
          <div className="token-card-value in">{(s.total_input_tokens || 0).toLocaleString()}</div>
        </div>
        <div className="token-card">
          <div className="token-card-label">输出</div>
          <div className="token-card-value out">{(s.total_output_tokens || 0).toLocaleString()}</div>
        </div>
        <div className="token-card">
          <div className="token-card-label">调用数</div>
          <div className="token-card-value">{s.total_calls || 0}</div>
        </div>
      </div>

      {/* 按阶段柱状图 */}
      {stages.length > 0 && (
        <div className="token-chart">
          <h4>按阶段消耗</h4>
          {stages.map(([stage, v]: any) => {
            const tokens = (v.input_tokens || 0) + (v.output_tokens || 0)
            const pct = (tokens / maxTokens) * 100
            const label = stageLabel(stage)
            return (
              <div key={stage} className="token-bar-row" title={`${label}：${tokens.toLocaleString()} tokens`}>
                <span className="token-bar-label">{label}</span>
                <div className="token-bar-track">
                  <div className="token-bar-fill" style={{ width: `${pct}%` }} />
                </div>
                <span className="token-bar-value">{tokens.toLocaleString()}</span>
              </div>
            )
          })}
        </div>
      )}

      {/* 调用列表 */}
      {trace.calls && trace.calls.length > 0 && (
        <div className="token-calls">
          <h4>调用明细</h4>
          <div className="token-call-list">
            {trace.calls.map((c, i) => {
              const sl = statusLabel(c.validation_status)
              const label = stageLabel(c.stage)
              return (
                <div key={c.call_id || i} className="token-call-item" title={`${label} · ${c.total_tokens} tok · ${c.latency_ms}ms`}>
                  <span className="call-stage">{label}</span>
                  <span className="call-tokens">{(c.total_tokens || 0).toLocaleString()} tok</span>
                  <span className="call-latency">{c.latency_ms}ms</span>
                  <span className={`call-status ${sl.cls}`}>{sl.label}</span>
                </div>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}
