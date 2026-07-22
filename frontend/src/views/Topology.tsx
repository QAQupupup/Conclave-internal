import { useEffect, useState, useMemo } from 'react';
import { useApp } from '../state/AppContext';
import { apiGetHealth } from '../lib/api';

interface HealthItem {
  key: string;
  name: string;
  sub: string;
  status: 'ok' | 'error' | 'unavailable';
  latency_ms?: number;
  message?: string;
}

/** 单个服务的健康状态信息（来自健康检查 API 或 mock） */
interface ServiceHealth {
  status?: 'ok' | 'error' | 'unavailable';
  latency_ms?: number;
  message?: string;
}

const CORE_SERVICES: Omit<HealthItem, 'latency_ms' | 'message'>[] = [
  { key: 'frontend', name: 'Frontend', sub: 'Static Assets', status: 'ok' },
  { key: 'backend', name: 'Backend', sub: 'FastAPI :8000', status: 'ok' },
];

const NETWORK_LAYERS = [
  { name: 'L1 - 无网络', desc: '沙箱默认级别，完全隔离外网', tag: '默认' },
  { name: 'L2 - 限网', desc: '仅允许访问 PyPI / npm 等包管理白名单', tag: '代码执行' },
  { name: 'L3 - 全联网', desc: '需网络认证审批后开放', tag: '需审批' },
];

export default function Topology() {
  const { demoMode } = useApp();
  const [health, setHealth] = useState<Record<string, ServiceHealth>>({});
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        if (demoMode) {
          // 演示模式：构造模拟健康状态
          const mock: Record<string, ServiceHealth> = {
            postgresql: { status: 'ok', latency_ms: 8 },
            qdrant: { status: 'ok', latency_ms: 12 },
            docker: { status: 'ok', latency_ms: 25 },
          };
          if (mounted) setHealth(mock);
        } else {
          const data = await apiGetHealth();
          if (mounted && data) setHealth(data as Record<string, ServiceHealth>);
        }
      } catch {
        // 健康检查加载失败，显示基本结构
      } finally {
        if (mounted) setLoading(false);
      }
    })();
    return () => { mounted = false; };
  }, [demoMode]);

  // 合并基础服务 + 数据库/基础设施健康状态
  const nodes: HealthItem[] = useMemo(() => {
    const list: HealthItem[] = CORE_SERVICES.map(s => ({ ...s, latency_ms: undefined, message: undefined }));
    // 添加从健康检查得到的服务
    const nameMap: Record<string, { name: string; sub: string }> = {
      postgresql: { name: 'PostgreSQL', sub: 'DB :5432' },
      qdrant: { name: 'Qdrant', sub: 'Vector :6333' },
      docker: { name: 'Docker', sub: 'Sandbox Runtime' },
    };
    for (const [key, info] of Object.entries(health)) {
      if (nameMap[key]) {
        list.push({
          key,
          name: nameMap[key].name,
          sub: nameMap[key].sub,
          status: info?.status || 'error',
          latency_ms: info?.latency_ms,
          message: info?.message,
        });
      }
    }
    return list;
  }, [health]);

  // 连线：backend -> postgresql/qdrant/docker
  const connections = useMemo(() => {
    const conns: { from: string; to: string; port: string; status: string }[] = [];
    for (const node of nodes) {
      if (node.key === 'backend' || node.key === 'frontend') continue;
      conns.push({
        from: 'Backend',
        to: node.name,
        port: '',
        status: node.status,
      });
    }
    conns.unshift({ from: 'Frontend', to: 'Backend', port: ':8000', status: 'ok' });
    return conns;
  }, [nodes]);

  return (
    <div className="view active" id="view-topology">
      <div className="page-title" style={{ marginBottom: 8 }}>组件联通</div>
      <div style={{ fontSize: 13, color: 'var(--text-3)', marginBottom: 32 }}>
        服务依赖、网络隔离架构、实时健康状态
      </div>

      {/* 服务状态列表 */}
      <div className="monitor-section-title">服务状态</div>
      {loading ? (
        <div style={{ padding: 20, color: 'var(--text-3)', fontSize: 13, textAlign: 'center' }}>
          加载中...
        </div>
      ) : (
        <div id="health-list">
          {nodes.map((n) => (
            <div className="health-item" key={n.key}>
              <div className="health-name">{n.name}</div>
              <div className="health-desc">{n.sub}</div>
              <div className="health-latency">
                {n.latency_ms != null && n.latency_ms > 0 ? `${n.latency_ms}ms` : '-'}
              </div>
              <div className="health-status">
                <span className={`status-dot ${n.status === 'ok' ? 'done' : n.status === 'unavailable' ? 'pending' : 'error'}`} />
                {n.status === 'ok' ? 'ok' : n.status === 'unavailable' ? '未配置' : 'error'}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Network layers */}
      <div className="monitor-section-title" style={{ marginTop: 40 }}>网络隔离层级</div>
      <div id="network-layers">
        {NETWORK_LAYERS.map((l) => (
          <div className="network-layer" key={l.name}>
            <div className="network-layer-name">{l.name}</div>
            <div className="network-layer-desc">{l.desc}</div>
            <span className="network-layer-tag">{l.tag}</span>
          </div>
        ))}
      </div>

      {/* Connection detail */}
      <div className="monitor-section-title" style={{ marginTop: 40 }}>服务连接</div>
      {connections.length === 0 ? (
        <div style={{ padding: 20, color: 'var(--text-3)', fontSize: 13, textAlign: 'center' }}>
          暂无连接数据
        </div>
      ) : (
        <div id="connection-list">
          {connections.map((conn, i) => (
            <div className="connection-item" key={`${conn.from}-${conn.to}-${i}`}>
              <span className={`conn-status status-dot ${conn.status === 'ok' ? 'done' : conn.status === 'unavailable' ? 'pending' : 'error'}`} />
              <span className="conn-from">{conn.from}</span>
              <span className="conn-arrow">→</span>
              <span className="conn-to">{conn.to}</span>
              {conn.port && <span className="conn-port">{conn.port}</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
