// 组件连通性网格：状态灯 + 组件名 + 延迟/详情
// 使用 AntD Card + Badge + Tag + Button + Row/Col + Typography + Space
import { useState, useCallback } from 'react'
import { Card, Badge, Tag, Button, Row, Col, Typography, Space, Tooltip } from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import type { MetricsSnapshot } from '../lib/api.ts'

const { Text } = Typography

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

const STATUS_DISPLAY: Record<string, { label: string; severity: 'ok' | 'warn' | 'err' | 'idle' }> = {
  ok:          { label: '正常', severity: 'ok' },
  closed:      { label: '正常', severity: 'ok' },
  open:        { label: '熔断', severity: 'err' },
  half_open:   { label: '探测', severity: 'warn' },
  warn:        { label: '警告', severity: 'warn' },
  error:       { label: '错误', severity: 'err' },
  err:         { label: '错误', severity: 'err' },
  unavailable: { label: '未配置', severity: 'idle' },
  unknown:     { label: '未知', severity: 'idle' },
  idle:        { label: '空闲', severity: 'idle' },
  active:      { label: '运行', severity: 'ok' },
  degraded:    { label: '降级', severity: 'warn' },
}

/** Severity → AntD Badge status */
const SEVERITY_BADGE: Record<string, 'success' | 'warning' | 'error' | 'default'> = {
  ok: 'success',
  warn: 'warning',
  err: 'error',
  idle: 'default',
}

/** Severity → AntD Tag color */
const SEVERITY_COLOR: Record<string, string> = {
  ok: 'green',
  warn: 'orange',
  err: 'red',
  idle: 'default',
}

function formatLatency(ms: number | undefined): string {
  if (ms === undefined || ms === null) return ''
  return `${ms.toFixed(1)}ms`
}

export function HealthGrid({ infra, onRefresh, refreshing = false }: HealthGridProps) {
  if (!infra || !infra.components) {
    return (
      <Card size="small">
        <div className="health-grid-header-row">
          <Text strong>组件连通性</Text>
          {onRefresh && <RefreshButton onClick={onRefresh} refreshing={refreshing} />}
        </div>
        <Text type="secondary">暂无数据</Text>
      </Card>
    )
  }

  const components = infra.components as Record<string, ComponentInfo>
  const keys = Object.keys(components)
  const degraded = ((infra as Record<string, unknown>).degraded_components as string[] | undefined) || []

  return (
    <Card size="small">
      <div className="health-grid-header-row">
        <Space>
          <Text strong>组件连通性</Text>
          {degraded.length > 0
            ? <Tag color="red">{degraded.length} 异常</Tag>
            : <Tag color="green">全部正常</Tag>
          }
        </Space>
        {onRefresh && <RefreshButton onClick={onRefresh} refreshing={refreshing} />}
      </div>
      <Row gutter={[8, 8]}>
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
          const tip = c.message && rawStatus !== 'ok' && rawStatus !== 'closed'
            ? `${display.label} · ${c.message}`
            : display.label

          return (
            <Col key={key} xs={12} sm={8} md={6}>
              <Tooltip title={tip}>
                <Card size="small" className="health-grid-card-full">
                  <Space direction="vertical" size={4} className="health-grid-space-full">
                    <Badge status={SEVERITY_BADGE[display.severity] ?? 'default'} text={<Text strong className="health-grid-label-text">{label}</Text>} />
                    <Space size={4}>
                      <Tag color={SEVERITY_COLOR[display.severity] ?? 'default'}>{display.label}</Tag>
                      {extra && <Text type="secondary" className="health-grid-extra-text">{extra}</Text>}
                    </Space>
                  </Space>
                </Card>
              </Tooltip>
            </Col>
          )
        })}
      </Row>
    </Card>
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
    <Button
      type="text"
      size="small"
      icon={<ReloadOutlined spin={spinning} />}
      onClick={handle}
      disabled={spinning}
    >
      刷新
    </Button>
  )
}
