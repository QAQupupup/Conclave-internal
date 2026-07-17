import { useEffect, useState } from 'react';
import { useApp } from '../state/AppContext';
import { HEALTH_CHECKS, METRICS, CIRCUIT_BREAKER, EVENTS } from '../data/mock';
import { apiGetMetrics } from '../lib/api';

type Metric = typeof METRICS[number];

function cbDotClass(indicator: string): string {
  if (indicator === 'closed') return 'closed';
  if (indicator === 'half_open') return 'half_open';
  if (indicator === 'open') return 'open';
  return '';
}

function cbText(indicator: string): string | null {
  if (indicator === 'closed') return '正常';
  if (indicator === 'half_open') return '半开';
  if (indicator === 'open') return '熔断';
  return null;
}

export default function Monitor() {
  const { appendLog } = useApp();

  // 指标：默认 mock，API 成功覆盖对应项；失败回退 mock
  const [metrics, setMetrics] = useState<Metric[]>(METRICS);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data: any = await apiGetMetrics(true);
        if (cancelled || !data || typeof data !== 'object') return;
        setMetrics((prev) =>
          prev.map((m) => {
            // 用真实数据覆盖语义对应的指标显示
            if (m.label === '运行中会议' && data.active_meetings != null) {
              return { ...m, value: String(data.active_meetings) };
            }
            if (m.label === '会议总数' && data.meetings_total != null) {
              return { ...m, value: String(data.meetings_total) };
            }
            if (m.label === '今日Token消耗' && data.llm_calls_total != null) {
              return { ...m, trend: `累计 ${data.llm_calls_total} 次调用` };
            }
            return m;
          }),
        );
      } catch (e: any) {
        // 静默回退 mock，不抛错
        if (!cancelled) appendLog?.('监控指标拉取失败，使用本地数据', 'debug');
      }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="view active" id="view-monitor">
      <div className="page-title" style={{ marginBottom: 8 }}>监控面板</div>
      <div style={{ fontSize: 13, color: 'var(--text-3)', marginBottom: 32 }}>
        系统健康状态、资源占用、LLM 熔断器、实时指标
      </div>

      {/* Health overview */}
      <div className="monitor-section-title">组件健康</div>
      <div id="health-list">
        {HEALTH_CHECKS.map((h, i) => {
          const isCb = h.name === 'LLM 熔断器';
          const dotCls = isCb ? 'done' : h.status === 'ok' ? 'done' : 'error';
          const statusText = isCb ? 'closed (正常)' : h.status === 'ok' ? 'ok' : 'error';
          return (
            <div className="health-item" key={h.name + i}>
              <div className="health-name">{h.name}</div>
              <div className="health-desc">
                {h.desc}
                <br />
                <span style={{ color: 'var(--text-3)', fontSize: 11 }}>{h.detail}</span>
              </div>
              <div className="health-latency">{h.latency}</div>
              <div className="health-status">
                <span className={`status-dot ${dotCls}`} />
                {statusText}
              </div>
            </div>
          );
        })}
      </div>

      {/* Metrics */}
      <div className="monitor-section-title" style={{ marginTop: 40 }}>运行指标</div>
      <div className="metric-grid" id="metric-grid">
        {metrics.map((m, i) => (
          <div className="metric-card" key={m.label + i}>
            <div className="metric-label">{m.label}</div>
            <div className="metric-value">
              {m.value}
              <span className="metric-unit">{m.unit}</span>
            </div>
            <div className="metric-trend">{m.trend}</div>
            <div className="metric-bar">
              <div className="metric-bar-fill" style={{ width: `${m.bar * 100}%` }} />
            </div>
          </div>
        ))}
      </div>

      {/* LLM circuit breaker */}
      <div className="monitor-section-title" style={{ marginTop: 40 }}>LLM 熔断器</div>
      <div id="circuit-breaker">
        {CIRCUIT_BREAKER.map((cb, i) => {
          const dotText = cbText(cb.indicator);
          return (
            <div className="cb-state" key={cb.label + i}>
              <span className="cb-label">{cb.label}</span>
              <span className="cb-value">{cb.value}</span>
              {dotText && (
                <span className="cb-state-indicator">
                  <span className={`cb-dot ${cbDotClass(cb.indicator)}`} />
                  {dotText}
                </span>
              )}
            </div>
          );
        })}
      </div>

      {/* Recent events */}
      <div className="monitor-section-title" style={{ marginTop: 40 }}>近期事件</div>
      <div id="event-list">
        {EVENTS.map((e, i) => (
          <div className="event-item" key={e.time + i}>
            <span className="event-time">{e.time}</span>
            <span className={`event-level ${e.level}`}>{e.level}</span>
            <span className="event-msg">{e.msg}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
