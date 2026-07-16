// 概览指标卡片：使用 AntD Card + Statistic
import { Card, Statistic } from 'antd'

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
    <Card className={`metric-card metric-card-${status}`} styles={{ body: { padding: '16px 20px' } }}>
      <div className="metric-card-bar" />
      <Statistic
        title={label}
        value={value}
        suffix={suffix || undefined}
        valueStyle={{ fontSize: 26, fontWeight: 600, fontVariantNumeric: 'tabular-nums' }}
      />
      {description && <div className="metric-desc">{description}</div>}
    </Card>
  )
}
