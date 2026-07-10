// 组件连通性网格：状态灯 + 组件名 + 延迟/详情
// [v3 优化] 基于审美文件 Editorial precision 风格：
//   1) 状态文字简化："关闭 (健康)" → "正常"（语义靠颜色+点表达，避免文字过长）
//   2) 布局防重叠：grid 列宽自适应，长文字截断，不固定死宽度
//   3) 刷新按钮：改用 SVG 图标（Lucide 风格），不再用 Unicode 字符
//   4) 间距对齐审美文件：space-2/3、radius-sm、极简边框
//   5) 颜色：主色 #335c8e，状态色低饱和（对齐 conclave-ui-redesign）
//   6) hover 态柔和：仅背景微变，不加边框
import { useState, useCallback } from 'react'
import type { MetricsSnapshot } from '../lib/api.ts'

interface HealthGridProps {
  infra: MetricsSnapshot['infrastructure'] | null
  onRefresh?: () => void | Promise<void>
  refreshing?: boolean
}

type ComponentInfo = {
  status: string
  latency_ms?: number
  message?: string
  active_contexts?: number
  mode?: string
  failures?: number
  threshold?: number
}

const COMPONENT_LABELS: Record<string, string> = {
  sqlite: 'SQLite',
  qdrant: 'Qdrant',
  docker: 'Docker',
  llm_circuit: 'LLM 熔断器',
  browser_pool: '浏览器池',
  sandbox: '沙箱',
}

// [v3 简化] 状态文字精简，避免"关闭 (健康)"这种容易误解的长文字
// 熔断器三态（closed=正常, open=熔断, half_open=探测）统一用简洁中文
const STATUS_DISPLAY: Record<string, { label: string; severity: 'ok' | 'warn' | 'err' | 'idle' }> = {
  ok:          { label: '正常', severity: 'ok' },
  closed:      { label: '正常', severity: 'ok' },    // 熔断器关闭 = 健康
  open:        { label: '熔断', severity: 'err' },   // 熔断器打开 = 已熔断
  half_open:   { label: '探测', severity: 'warn' },  // 半开探测中
  warn:        { label: '警告', severity: 'warn' },
  error:       { label: '错误', severity: 'err' },
  err:         { label: '错误', severity: 'err' },
  unavailable: { label: '未配置', severity: 'idle' }, // 后端未配置访问，非错误
  unknown:     { label: '未知', severity: 'idle' },
  idle:        { label: '空闲', severity: 'idle' },
  active:      { label: '运行', severity: 'ok' },
  degraded:    { label: '降级', severity: 'warn' },
}

function formatLatency(ms: number | undefined): string {
  if (ms === undefined || ms === null) return ''
  return `${ms.toFixed(1)}ms`
}

/** Refresh icon (Lucide refresh-cw style, inline SVG) */
function RefreshIcon({ spinning }: { spinning: boolean }) {
  return (
    <svg
      width="12"
      height="12"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      style={{
        animation: spinning ? 'health-spin 0.9s linear infinite' : 'none',
      }}
      aria-hidden="true"
    >
      <path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
      <path d="M3 3v5h5" />
      <path d="M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16" />
      <path d="M16 16h5v5" />
    </svg>
  )
}

export function HealthGrid({ infra, onRefresh, refreshing = false }: HealthGridProps) {
  if (!infra || !infra.components) {
    return (
      <div className="health-grid">
        <div className="health-grid-header">
          <h3 className="section-title">组件连通性</h3>
          {onRefresh && <RefreshButton onClick={onRefresh} refreshing={refreshing} />}
        </div>
        <div className="health-empty">暂无数据</div>
      </div>
    )
  }

  const components = infra.components as Record<string, ComponentInfo>
  const keys = Object.keys(components)
  const degraded = ((infra as Record<string, unknown>).degraded_components as string[] | undefined) || []

  return (
    <div className="health-grid">
      <div className="health-grid-header">
        <div className="health-title-group">
          <h3 className="section-title">组件连通性</h3>
          {degraded.length > 0
            ? <span className="health-summary health-summary-err">{degraded.length} 异常</span>
            : <span className="health-summary health-summary-ok">全部正常</span>
          }
        </div>
        {onRefresh && <RefreshButton onClick={onRefresh} refreshing={refreshing} />}
      </div>
      <div className="health-grid-inner">
        {keys.map((key) => {
          const c = components[key]
          const rawStatus = (c.status || 'unknown').toLowerCase()
          const display = STATUS_DISPLAY[rawStatus] || { label: rawStatus, severity: 'idle' as const }
          const label = COMPONENT_LABELS[key] || key
          const extra: string = c.latency_ms !== undefined
            ? formatLatency(c.latency_ms)
            : c.active_contexts !== undefined
              ? `${c.active_contexts} 活跃`
              : c.mode !== undefined
                ? c.mode
                : c.failures !== undefined && c.threshold !== undefined
                  ? `${c.failures}/${c.threshold}`
                  : ''
          // 非正常状态显示详细原因
          const tip = c.message && rawStatus !== 'ok' && rawStatus !== 'closed'
            ? `${display.label} · ${c.message}`
            : display.label

          return (
            <div key={key} className={`health-item health-sev-${display.severity}`} title={tip}>
              <span className={`health-dot health-dot-${display.severity}`} />
              <span className="health-name">{label}</span>
              <span className={`health-status health-status-${display.severity}`}>{display.label}</span>
              {extra && <span className="health-extra">{extra}</span>}
            </div>
          )
        })}
      </div>
    </div>
  )
}

function RefreshButton({ onClick, refreshing }: { onClick: () => void | Promise<void>; refreshing: boolean }) {
  const [localSpin, setLocalSpin] = useState(false)
  const handle = useCallback(async () => {
    if (refreshing) return
    setLocalSpin(true)
    try { await onClick() } finally {
      setTimeout(() => setLocalSpin(false), 250)
    }
  }, [onClick, refreshing])
  const spinning = refreshing || localSpin
  return (
    <button
      type="button"
      className={`health-refresh-btn ${spinning ? 'is-spinning' : ''}`}
      onClick={handle}
      disabled={spinning}
      title="立即重检所有组件状态"
      aria-label="刷新组件状态"
    >
      <RefreshIcon spinning={spinning} />
      <span>刷新</span>
    </button>
  )
}
