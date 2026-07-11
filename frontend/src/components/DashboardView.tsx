// 运维面板主视图：概览卡片 + 连通性 + 性能图表
// 使用 AntD Card + Spin + Alert + Typography
import { useEffect, useState, useCallback, useRef } from 'react'
import { Spin, Alert, Typography, Space } from 'antd'
import {
  getMetrics,
  getMetricsHistory,
  type MetricsSnapshot,
  type MetricPoint,
} from '../lib/api.ts'
import { MetricCard } from './MetricCard.tsx'
import { HealthGrid } from './HealthGrid.tsx'
import { ResourceChart } from './ResourceChart.tsx'

const { Title, Text } = Typography

export function DashboardView() {
  const [snapshot, setSnapshot] = useState<MetricsSnapshot | null>(null)
  const [history, setHistory] = useState<MetricPoint[]>([])
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [healthRefreshing, setHealthRefreshing] = useState(false)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const fetchData = useCallback(async () => {
    try {
      setError(null)
      const [snap, hist] = await Promise.all([
        getMetrics(),
        getMetricsHistory(60),
      ])
      setSnapshot(snap)
      setHistory(hist.points)
      setLastUpdate(new Date())
    } catch (e) {
      setError(e instanceof Error ? e.message : '获取数据失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchData()
    intervalRef.current = setInterval(fetchData, 10000)
    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current)
      }
    }
  }, [fetchData])

  const refreshHealth = useCallback(async () => {
    setHealthRefreshing(true)
    try {
      const { getMetricsHealth } = await import('../lib/api.ts')
      const health = await getMetricsHealth()
      setSnapshot((prev) => (prev ? { ...prev, infrastructure: health } : prev))
      setLastUpdate(new Date())
    } catch (e) {
      setError(e instanceof Error ? e.message : '刷新连通性失败')
    } finally {
      setHealthRefreshing(false)
    }
  }, [])

  const formatUptime = (seconds: number) => {
    const h = Math.floor(seconds / 3600)
    const m = Math.floor((seconds % 3600) / 60)
    const s = Math.floor(seconds % 60)
    if (h > 0) return `${h}h ${m}m`
    if (m > 0) return `${m}m ${s}s`
    return `${s}s`
  }

  const formatCost = (usd: number) => {
    if (usd < 0.01) return '<$0.01'
    return `$${usd.toFixed(2)}`
  }

  const infraStatus = snapshot?.infrastructure?.status || 'unknown'
  const infraOk = infraStatus === 'ok'
  const componentCount = snapshot?.infrastructure?.components
    ? Object.keys(snapshot.infrastructure.components).length
    : 0
  const componentOkCount = snapshot?.infrastructure?.components
    ? Object.values(snapshot.infrastructure.components).filter(
        (c: any) => c.status === 'ok' || c.status === 'closed',
      ).length
    : 0

  if (loading) {
    return (
      <div className="dashboard-view" style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: 300 }}>
        <Spin size="large" tip="加载中..." />
      </div>
    )
  }

  return (
    <div className="dashboard-view" style={{ padding: 24 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <Title level={3} style={{ margin: 0 }}>运维面板</Title>
        <Space>
          {error && <Alert message={error} type="error" showIcon style={{ padding: '4px 12px' }} />}
          {lastUpdate && (
            <Text type="secondary" style={{ fontSize: 12 }}>
              更新于 {lastUpdate.toLocaleTimeString('zh-CN')}
            </Text>
          )}
        </Space>
      </div>

      {/* 概览卡片行 */}
      <div className="metric-grid" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 16, marginBottom: 24 }}>
        <MetricCard
          label="活跃会议"
          value={snapshot?.conclave.active_meetings ?? 0}
          status="ok"
        />
        <MetricCard
          label="Token 累计"
          value={snapshot?.llm.total_tokens?.toLocaleString() ?? '0'}
          description={formatCost(snapshot?.llm.total_cost_usd ?? 0)}
          status="ok"
        />
        <MetricCard
          label="API 吞吐量"
          value={snapshot?.throughput.api_requests_per_minute?.toFixed(1) ?? '0'}
          suffix="QPM"
          description={`${snapshot?.throughput.avg_latency_ms?.toFixed(0) ?? '0'}ms 延迟`}
          status="ok"
        />
        <MetricCard
          label="系统健康"
          value={`${componentOkCount}/${componentCount}`}
          suffix={infraOk ? '正常' : '降级'}
          status={infraOk ? 'ok' : 'err'}
          description={`运行 ${formatUptime(snapshot?.system.uptime_seconds ?? 0)}`}
        />
      </div>

      {/* 内容区：左连通性 + 右图表 */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        <div>
          <HealthGrid
            infra={snapshot?.infrastructure ?? null}
            onRefresh={refreshHealth}
            refreshing={healthRefreshing}
          />
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <ResourceChart type="memory" data={history} title="内存消耗" />
          <ResourceChart type="tokens" data={history} title="Token 消耗" />
          <ResourceChart type="throughput" data={history} title="API 吞吐量" />
        </div>
      </div>
    </div>
  )
}
