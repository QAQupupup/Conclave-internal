// 概览指标卡片：数值 + 标签 + 状态指示
// [v3 优化] Editorial precision 风格：
//   - 统一白底，不整张卡片染色（太花哨）
//   - 顶部 3px 细色条表示状态（ok/warn/err）
//   - 数值用 tabular-nums 对齐，字号 26px 更克制
//   - 标签用大写小字 + 宽字距（conclave-ui-redesign caption 风格）
interface MetricCardProps {
  label: string
  value: string | number
  suffix?: string
  status?: 'ok' | 'warn' | 'err'
  description?: string
  icon?: React.ReactNode
}

export function MetricCard({ label, value, suffix = '', status = 'ok', description }: MetricCardProps) {
  return (
    <div className={`metric-card metric-card-${status}`}>
      <div className="metric-card-bar" />
      <div className="metric-label">{label}</div>
      <div className="metric-value">
        <span className="metric-value-number">{value}</span>
        {suffix && <span className="metric-value-suffix">{suffix}</span>}
      </div>
      {description && <div className="metric-desc">{description}</div>}
    </div>
  )
}
