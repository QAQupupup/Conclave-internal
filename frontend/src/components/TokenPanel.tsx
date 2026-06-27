// Token 可视化面板：展示 LLM 调用追踪的 Token 消耗、阶段柱状图、调用明细
// 通过 GET /meetings/:id/trace 拉取数据，每 5s 轮询刷新
import { useState, useEffect } from 'react'
import { useMeeting } from '../store/MeetingContext.tsx'

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

export function TokenPanel() {
  const { meetingId } = useMeeting()
  const [trace, setTrace] = useState<TraceData | null>(null)
  const [loading, setLoading] = useState(false)

  const refresh = async () => {
    if (!meetingId) return
    setLoading(true)
    try {
      const resp = await fetch(`/meetings/${encodeURIComponent(meetingId)}/trace`)
      if (resp.ok) {
        const data = await resp.json()
        setTrace(data)
      }
    } catch {
      // 静默
    } finally {
      setLoading(false)
    }
  }

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
      <div className="token-panel-header">
        <h3>Token 消耗</h3>
        <button className="btn btn-sm" onClick={refresh} disabled={loading}>
          ↻
        </button>
      </div>

      {/* 总览卡片 */}
      <div className="token-cards">
        <div className="token-card">
          <div className="token-card-label">总 Token</div>
          <div className="token-card-value">{s.total_tokens || 0}</div>
        </div>
        <div className="token-card">
          <div className="token-card-label">输入</div>
          <div className="token-card-value in">{s.total_input_tokens || 0}</div>
        </div>
        <div className="token-card">
          <div className="token-card-label">输出</div>
          <div className="token-card-value out">{s.total_output_tokens || 0}</div>
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
            return (
              <div key={stage} className="token-bar-row">
                <span className="token-bar-label">{stage}</span>
                <div className="token-bar-track">
                  <div className="token-bar-fill" style={{ width: `${pct}%` }} />
                </div>
                <span className="token-bar-value">{tokens}</span>
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
            {trace.calls.map((c, i) => (
              <div key={c.call_id || i} className="token-call-item">
                <span className="call-stage">{c.stage}</span>
                <span className="call-tokens">{c.total_tokens || 0} tok</span>
                <span className="call-latency">{c.latency_ms}ms</span>
                <span className={`call-status ${c.validation_status}`}>{c.validation_status}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
