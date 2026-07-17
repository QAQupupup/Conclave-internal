import { useMemo } from 'react';
import { TOPOLOGY_NODES, TOPOLOGY_LINKS, NETWORK_LAYERS, CONNECTIONS } from '../data/mock';

type TopologyNode = typeof TOPOLOGY_NODES[number];

export default function Topology() {
  // 节点坐标映射，用于连线计算
  const nodeMap = useMemo(() => {
    const m: Record<string, TopologyNode> = {};
    TOPOLOGY_NODES.forEach((n) => { m[n.id] = n; });
    return m;
  }, []);

  // 预计算连线 path 与中点圆，避免渲染时重复运算
  const links = useMemo(() => {
    return TOPOLOGY_LINKS.map((l, idx) => {
      const f = nodeMap[l.from];
      const t = nodeMap[l.to];
      if (!f || !t) return null;
      const x1 = f.x + f.w / 2;
      const y1 = f.y + f.h;
      const x2 = t.x + t.w / 2;
      const y2 = t.y;
      const midY = (y1 + y2) / 2;
      const d = `M${x1},${y1} C${x1},${midY} ${x2},${midY} ${x2},${y2}`;
      return {
        key: `${l.from}-${l.to}-${idx}`,
        d,
        type: l.type,
        midX: (x1 + x2) / 2,
        midY,
      };
    }).filter(Boolean) as { key: string; d: string; type: string; midX: number; midY: number }[];
  }, [nodeMap]);

  return (
    <div className="view active" id="view-topology">
      <div className="page-title" style={{ marginBottom: 8 }}>组件联通</div>
      <div style={{ fontSize: 13, color: 'var(--text-3)', marginBottom: 32 }}>
        Docker 容器拓扑、网络隔离架构、服务间依赖关系
      </div>

      {/* Topology SVG */}
      <div className="topology-canvas" id="topology-canvas">
        <svg className="topology-svg" viewBox="0 0 720 380">
          {/* Links */}
          {links.map((l) => (
            <g key={l.key}>
              <path className={`topo-link ${l.type}`} d={l.d} />
              <circle cx={l.midX} cy={l.midY} r={2} fill="var(--dot-done)" />
            </g>
          ))}
          {/* Nodes */}
          {TOPOLOGY_NODES.map((n) => (
            <g className="topo-node" key={n.id}>
              <rect x={n.x} y={n.y} width={n.w} height={n.h} rx={4} />
              <text x={n.x + n.w / 2} y={n.y + 16}>{n.label}</text>
              <text className="sub" x={n.x + n.w / 2} y={n.y + 30}>{n.sub}</text>
            </g>
          ))}
        </svg>
      </div>

      {/* Network layers */}
      <div className="monitor-section-title" style={{ marginTop: 40 }}>网络隔离层级</div>
      <div id="network-layers">
        {NETWORK_LAYERS.map((l, i) => (
          <div className="network-layer" key={l.name + i}>
            <div className="network-layer-name">{l.name}</div>
            <div className="network-layer-desc">{l.desc}</div>
            <span className="network-layer-tag">{l.tag}</span>
          </div>
        ))}
      </div>

      {/* Connection detail */}
      <div className="monitor-section-title" style={{ marginTop: 40 }}>服务连接</div>
      <div id="connection-list">
        {CONNECTIONS.map((conn, i) => (
          <div className="connection-item" key={conn.from + conn.to + i}>
            <span className="conn-status status-dot done" />
            <span className="conn-from">{conn.from}</span>
            <span className="conn-arrow">→</span>
            <span className="conn-to">{conn.to}</span>
            <span className="conn-port">{conn.port}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
