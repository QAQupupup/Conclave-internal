import { useEffect, useState, useCallback } from 'react';
import { useApp } from '../state/AppContext';
import { apiGetMetrics, apiGetHealth, apiGetSecurityEvents } from '../lib/api';
import { HEALTH_CHECKS as MOCK_HEALTH, METRICS as MOCK_METRICS, EVENTS as MOCK_EVENTS } from '../data/mock';

interface HealthCheck {
  name: string;
  status: 'ok' | 'error' | 'unavailable';
  latency_ms?: number;
  message?: string;
}

interface MetricCard {
  label: string;
  value: string;
  unit: string;
  trend: string;
}

interface SecurityEvent {
  id: number;
  timestamp: string;
  category: string;
  action: string;
  username: string;
  status: string;
  details: Record<string, unknown>;
}

const HEALTH_LABELS: Record<string, { name: string; desc: string }> = {
  postgresql: { name: 'PostgreSQL', desc: '主数据库' },
  qdrant: { name: 'Qdrant', desc: '向量数据库' },
  docker: { name: 'Docker', desc: '沙箱运行时' },
  docker_hosts: { name: 'Docker Hosts', desc: '远程主机集群' },
  redis: { name: 'Redis', desc: '缓存与队列' },
  llm_circuit_breaker: { name: 'LLM 熔断器', desc: 'API连接保护' },
};

function statusDotClass(status: string): string {
  if (status === 'ok') return 'done';
  if (status === 'unavailable') return 'pending';
  return 'error';
}

function statusText(status: string): string {
  if (status === 'ok') return 'ok';
  if (status === 'unavailable') return '未配置';
  return 'error';
}

function formatTime(ts: string): string {
  try {
    return new Date(ts).toLocaleTimeString('zh-CN', { hour12: false });
  } catch {
    return ts.slice(11, 19);
  }
}

export default function Monitor() {
  const { toast, demoMode } = useApp();

  const [healthChecks, setHealthChecks] = useState<HealthCheck[]>([]);
  const [metrics, setMetrics] = useState<MetricCard[]>([]);
  const [events, setEvents] = useState<SecurityEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    // 演示模式：直接使用 mock 数据
    if (demoMode) {
      setHealthChecks((MOCK_HEALTH as unknown as Record<string, unknown>[]).map((h: Record<string, unknown>) => ({
        name: String(h.name), status: h.status === 'healthy' ? 'ok' : (h.status === 'unavailable' ? 'unavailable' : 'error'),
        latency_ms: h.latency as number | undefined, message: h.message as string | undefined,
      })));
      setMetrics(MOCK_METRICS.map((m) => ({ label: m.label, value: String(m.value), unit: m.unit || '', trend: m.trend || '' })));
      setEvents((MOCK_EVENTS as unknown as Record<string, unknown>[]).map((e: Record<string, unknown>, i: number) => ({
        id: i, timestamp: String(e.time || new Date().toISOString()),
        category: String(e.category || 'system'), action: String(e.action || e.event || ''),
        username: String(e.user || 'demo'), status: String(e.status || 'info'), details: {},
      })));
      setLoading(false);
      setError(null);
      return;
    }
    setError(null);
    try {
      const [healthData, metricsData, eventsData] = await Promise.allSettled([
        apiGetHealth(),
        apiGetMetrics(false),
        apiGetSecurityEvents(20),
      ]);

      // 处理健康检查
      if (healthData.status === 'fulfilled' && healthData.value) {
        const checks: HealthCheck[] = Object.entries(healthData.value).map(([key, val]) => {
          const v = val as Record<string, unknown> | undefined;
          return {
            name: HEALTH_LABELS[key]?.name || key,
            status: ((v?.status as string) || 'error') as HealthCheck['status'],
            latency_ms: v?.latency_ms as number | undefined,
            message: v?.message as string | undefined,
          };
        });
        // 添加 LLM 熔断器状态（从 metrics 获取）
        setHealthChecks(checks);
      }

      // 处理指标
      if (metricsData.status === 'fulfilled' && metricsData.value) {
        const m = metricsData.value;
        const cards: MetricCard[] = [
          { label: '会议总数', value: String(m.meetings_total ?? '-'), unit: '', trend: `运行中 ${m.active_meetings ?? 0}` },
          { label: 'LLM 调用次数', value: String(m.llm_calls_total ?? '-'), unit: '', trend: `失败 ${m.llm_calls_failed ?? 0} 次` },
          { label: '平均响应耗时', value: m.avg_response_ms != null ? `${Math.round(m.avg_response_ms as number)}` : '-', unit: 'ms', trend: '' },
          { label: 'WS 连接数', value: String(m.ws_connections ?? '-'), unit: '', trend: '' },
          { label: '沙箱运行中', value: String(m.running_sandboxes ?? '-'), unit: '', trend: '' },
          { label: '审计事件', value: String(m.audit_events_today ?? '-'), unit: '', trend: '今日' },
        ];
        setMetrics(cards);
      }

      // 处理安全/系统事件
      if (eventsData.status === 'fulfilled' && eventsData.value) {
        const allEvents = ([
          ...((eventsData.value.security_events as SecurityEvent[]) || []),
          ...((eventsData.value.system_errors as SecurityEvent[]) || []),
        ] as SecurityEvent[])
          .sort((a, b) => (b.id || 0) - (a.id || 0))
          .slice(0, 20);
        setEvents(allEvents);
      }

      const anyFailed = [healthData, metricsData, eventsData].some(r => r.status === 'rejected');
      if (anyFailed && healthChecks.length === 0) {
        // 至少有一个请求失败但健康检查也没拿到
        const failedReasons = [healthData, metricsData, eventsData]
          .filter((r): r is PromiseRejectedResult => r.status === 'rejected')
          .map(r => r.reason?.message || '未知错误')
          .join('; ');
        setError(failedReasons || '部分数据加载失败');
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '加载监控数据失败');
    } finally {
      setLoading(false);
    }
  }, [demoMode]);

  useEffect(() => {
    loadData();
    // 每 10 秒自动刷新
    const timer = setInterval(loadData, 10000);
    return () => clearInterval(timer);
  }, [loadData, demoMode]);

  if (loading && healthChecks.length === 0 && metrics.length === 0) {
    return (
      <div className="view active" id="view-monitor">
        <div className="page-title" style={{ marginBottom: 8 }}>监控面板</div>
        <div style={{ padding: 60, textAlign: 'center', color: 'var(--text-3)' }}>
          正在加载监控数据...
        </div>
      </div>
    );
  }

  return (
    <div className="view active" id="view-monitor">
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
        <div className="page-title" style={{ marginBottom: 0 }}>监控面板</div>
        <button className="btn btn-ghost" onClick={loadData} style={{ fontSize: 12 }}>刷新</button>
      </div>
      <div style={{ fontSize: 13, color: 'var(--text-3)', marginBottom: error ? 12 : 32 }}>
        系统健康状态、资源占用、实时指标
      </div>

      {error && (
        <div style={{
          padding: '10px 14px', background: 'var(--bg-elevated)', borderRadius: 6,
          border: '1px solid var(--error, #e74c3c)', color: 'var(--error, #e74c3c)',
          fontSize: 12, marginBottom: 20, display: 'flex', alignItems: 'center', gap: 8,
        }}>
          <span>⚠️</span>
          <span>部分监控数据加载失败: {error}</span>
        </div>
      )}

      {/* Health overview */}
      <div className="monitor-section-title">组件健康</div>
      {healthChecks.length === 0 ? (
        <div style={{ padding: 20, color: 'var(--text-3)', fontSize: 13, textAlign: 'center' }}>
          暂无健康检查数据
        </div>
      ) : (
        <div id="health-list">
          {healthChecks.map((h) => (
            <div className="health-item" key={h.name}>
              <div className="health-name">{h.name}</div>
              <div className="health-desc">
                {HEALTH_LABELS[h.name]?.desc || ''}
                {h.message && (
                  <>
                    <br />
                    <span style={{ color: 'var(--text-3)', fontSize: 11 }}>{h.message}</span>
                  </>
                )}
              </div>
              <div className="health-latency">
                {h.latency_ms != null && h.latency_ms > 0 ? `${h.latency_ms}ms` : '-'}
              </div>
              <div className="health-status">
                <span className={`status-dot ${statusDotClass(h.status)}`} />
                {statusText(h.status)}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Metrics */}
      <div className="monitor-section-title" style={{ marginTop: 40 }}>运行指标</div>
      {metrics.length === 0 ? (
        <div style={{ padding: 20, color: 'var(--text-3)', fontSize: 13, textAlign: 'center' }}>
          暂无指标数据
        </div>
      ) : (
        <div className="metric-grid" id="metric-grid">
          {metrics.map((m) => (
            <div className="metric-card" key={m.label}>
              <div className="metric-label">{m.label}</div>
              <div className="metric-value">
                {m.value}
                <span className="metric-unit">{m.unit}</span>
              </div>
              <div className="metric-trend">{m.trend}</div>
            </div>
          ))}
        </div>
      )}

      {/* Recent events (from audit log) */}
      <div className="monitor-section-title" style={{ marginTop: 40 }}>近期事件</div>
      {events.length === 0 ? (
        <div style={{ padding: 20, color: 'var(--text-3)', fontSize: 13, textAlign: 'center' }}>
          暂无事件记录
        </div>
      ) : (
        <div id="event-list">
          {events.map((e) => {
            const isError = e.status === 'error' || e.status === 'failure' || e.status === 'blocked' || e.status === 'denied';
            const isWarn = e.status === 'warning';
            const level = isError ? 'error' : isWarn ? 'warn' : 'info';
            return (
              <div className="event-item" key={e.id}>
                <span className="event-time">{formatTime(e.timestamp)}</span>
                <span className={`event-level ${level}`}>{level}</span>
                <span className="event-msg">
                  [{e.category}] {e.action}
                  {e.username && e.username !== '-' && ` - ${e.username}`}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
