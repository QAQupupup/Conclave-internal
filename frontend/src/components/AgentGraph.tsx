// AgentGraph：Agent / 冲突 / 证据 拓扑图
// 视觉升级：圆角矩形节点 + 角色色填充 + 双行文字 + 贝塞尔连线 + 节点悬停高亮邻居
// 交互：d3-force 物理布局（快速稳定）/ 拖拽平移 / 滚轮缩放 / Focus 模式
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { MouseEvent as ReactMouseEvent } from 'react'
import { forceCenter, forceCollide, forceLink, forceManyBody, forceSimulation } from 'd3-force'
import type { SimulationLinkDatum, SimulationNodeDatum } from 'd3-force'
import { useMeeting } from '../store/MeetingContext.tsx'
import { ROLE_LABELS } from '../types/events.ts'
import type { MeetingState, Role } from '../types/events.ts'
import type { ForceGraphData, GraphLink, GraphNode } from '../types/graph.ts'
import { FocusMode } from './FocusMode.tsx'

// ---------- 视觉常量 ----------
const NODE_W = { agent: 132, conflict: 124, evidence: 110 } as const
const NODE_H = 52

const TYPE_BADGE: Record<GraphNode['type'], string> = {
  agent: '#3b82f6',
  conflict: '#f59e0b',
  evidence: '#06b6d4',
}
const TYPE_LABEL: Record<GraphNode['type'], string> = {
  agent: 'AGT',
  conflict: 'CFT',
  evidence: 'EV',
}

const ROLE_COLORS: Record<string, { bg: string; border: string; fg: string }> = {
  moderator:           { bg: '#eef2ff', border: '#6366f1', fg: '#3730a3' },
  product_architect:   { bg: '#faf5ff', border: '#8b5cf6', fg: '#6b21a8' },
  engineer:            { bg: '#ecfdf5', border: '#10b981', fg: '#065f46' },
  security_expert:     { bg: '#fef2f2', border: '#ef4444', fg: '#991b1b' },
  data_engineer:       { bg: '#ecfeff', border: '#06b6d4', fg: '#155e75' },
  ux_designer:         { bg: '#fffbeb', border: '#f59e0b', fg: '#92400e' },
  marketing_expert:    { bg: '#fdf2f8', border: '#ec4899', fg: '#9d174d' },
}
const DEFAULT_COLORS = { bg: '#f3f4f6', border: '#6b7280', fg: '#1f2937' }
const BORROWED_COLORS = { bg: '#f9fafb', border: '#9ca3af', fg: '#6b7280' }
const CONFLICT_COLORS = { bg: '#fffbeb', border: '#f59e0b', fg: '#92400e' }
const EVIDENCE_COLORS = { bg: '#ecfeff', border: '#06b6d4', fg: '#155e75' }

const TYPE_COLORS: Record<GraphNode['type'], { bg: string; border: string; fg: string }> = {
  agent: DEFAULT_COLORS,
  conflict: CONFLICT_COLORS,
  evidence: EVIDENCE_COLORS,
}

function nodeColor(n: GraphNode, borrowed: boolean): { bg: string; border: string; fg: string } {
  if (n.type === 'agent') {
    if (borrowed) return BORROWED_COLORS
    if (n.role && ROLE_COLORS[n.role]) return ROLE_COLORS[n.role]
    return DEFAULT_COLORS
  }
  return TYPE_COLORS[n.type]
}

const LINK_STYLE: Record<GraphLink['type'], { stroke: string; dash: string; opacity: number }> = {
  argues:     { stroke: '#94a3b8', dash: '',       opacity: 0.6 },
  conflicts:  { stroke: '#f59e0b', dash: '5 3',    opacity: 0.85 },
  supports:   { stroke: '#10b981', dash: '',       opacity: 0.75 },
  cites:      { stroke: '#cbd5e1', dash: '2 3',    opacity: 0.6 },
}

interface SimNode extends SimulationNodeDatum, GraphNode {
  borrowed?: boolean
}
interface SimLink extends SimulationLinkDatum<SimNode> {
  type: GraphLink['type']
  weight: number
}

function nodeSize(n: SimNode): { w: number; h: number } {
  return { w: NODE_W[n.type], h: NODE_H }
}

function linkDistance(type: GraphLink['type']): number {
  if (type === 'argues') return 95
  if (type === 'conflicts') return 130
  if (type === 'supports') return 70
  return 60
}

function tooltipText(n: SimNode): string {
  if (n.type === 'agent') {
    const role = n.role ? (ROLE_LABELS[n.role as Role] ?? n.role) : 'Agent'
    return n.stance ? `${role}\n立场：${n.stance}\n类型：${n.borrowed ? '借调' : '常驻'}` : `${role}\n类型：${n.borrowed ? '借调' : '常驻'}`
  }
  if (n.type === 'conflict') {
    return n.conflictType ? `冲突节点\n类型：${n.conflictType}` : `冲突节点`
  }
  return n.evidenceSource
    ? `证据\n来源：${n.evidenceSource}\n类型：${sourceLabel(n.evidenceSource)}`
    : `证据`
}

function sourceLabel(src: string): string {
  if (src.startsWith('doc:')) return '文档证据'
  if (src.startsWith('web:')) return '网络检索'
  if (src.startsWith('common_knowledge')) return '通用知识'
  return '证据'
}

function buildGraphData(meeting: MeetingState): { data: ForceGraphData; borrowedSet: Set<string> } {
  const nodes: GraphNode[] = []
  const links: GraphLink[] = []
  const seen = new Set<string>()
  const borrowedSet = new Set<string>()
  const addNode = (n: GraphNode): void => {
    if (!seen.has(n.id)) {
      seen.add(n.id)
      nodes.push(n)
    }
  }

  addNode({ id: 'moderator', label: '主持人', type: 'agent', role: 'moderator' })

  const team = meeting.team_config ?? []
  team.forEach((m) => {
    addNode({
      id: m.role,
      label: ROLE_LABELS[m.role as Role] ?? m.role,
      type: 'agent',
      role: m.role,
      stance: m.stance,
    })
  })

  team.forEach((m) => {
    links.push({ source: 'moderator', target: m.role, type: 'argues', weight: 0.4 })
  })

  const borrowed = meeting.borrowed_agents ?? []
  borrowed.forEach((b) => {
    const bid = `borrow:${b.role}`
    borrowedSet.add(bid)
    addNode({
      id: bid,
      label: b.role,
      type: 'agent',
      role: b.role,
      stance: '借调视角',
    })
    links.push({ source: 'moderator', target: bid, type: 'argues', weight: 0.3 })
  })

  const conflicts = meeting.conflicts ?? []
  conflicts.forEach((c, i) => {
    const cid = c.id ?? `conflict-${i}`
    addNode({
      id: cid,
      label: `冲突 ${i + 1}`,
      type: 'conflict',
      conflictType: c.conflict_type ?? (c as any).type,
    })
    links.push({ source: 'moderator', target: cid, type: 'argues', weight: 0.8 })
    team.forEach((m) => {
      links.push({ source: m.role, target: cid, type: 'argues', weight: 0.6 })
    })
  })

  const evidenceSet = meeting.evidence_set ?? []
  evidenceSet.forEach((es) => {
    const cid = es.conflict_id
    const assessments = es.assessments ?? []
    assessments.forEach((a, j) => {
      const eid = `evidence-${cid}-${j}`
      const src = a.source ?? ''
      const label = sourceLabel(src)
      addNode({ id: eid, label, type: 'evidence', evidenceSource: src })
      const linkType: GraphLink['type'] =
        a.supports === 'a' || a.supports === 'b' ? 'supports' : 'cites'
      links.push({ source: eid, target: cid, type: linkType, weight: 0.6 })
    })
  })

  return { data: { nodes, links }, borrowedSet }
}

// ---------- 组件 ----------

export function AgentGraph() {
  const { store } = useMeeting()
  const meeting = store.meeting
  if (!meeting) return null
  const { data: graphData, borrowedSet } = buildGraphData(meeting)
  return (
    <AgentGraphInner
      graphData={graphData}
      borrowedSet={borrowedSet}
      meeting={meeting}
    />
  )
}

function AgentGraphInner({
  graphData,
  borrowedSet,
  meeting: _meeting,
}: {
  graphData: ForceGraphData
  borrowedSet: Set<string>
  meeting: MeetingState
}) {
  const [focused, setFocused] = useState(false)
  const [tooltip, setTooltip] = useState<{ x: number; y: number; text: string } | null>(null)
  const svgRef = useRef<SVGSVGElement>(null)
  const groupRef = useRef<SVGGElement>(null)
  const [scale, setScale] = useState(1)
  const [translate, setTranslate] = useState({ x: 0, y: 0 })
  const [dragging, setDragging] = useState(false)
  const [dragStart, setDragStart] = useState({ x: 0, y: 0 })
  const [hoverNodeId, setHoverNodeId] = useState<string | null>(null)

  // 结构签名：节点/边变化时重建
  const signature = useMemo(() => {
    const ns = graphData.nodes.map((n) => n.id).join(',')
    const ls = graphData.links.map((l) => `${l.source}->${l.target}:${l.type}`).join('|')
    return `${ns}#${ls}`
  }, [graphData])

  const nodeCount = graphData.nodes.length
  const linkCount = graphData.links.length

  const neighborMap = useMemo(() => {
    const m = new Map<string, Set<string>>()
    for (const l of graphData.links) {
      const s = typeof l.source === 'string' ? l.source : (l.source as any).id
      const t = typeof l.target === 'string' ? l.target : (l.target as any).id
      if (!m.has(s)) m.set(s, new Set())
      if (!m.has(t)) m.set(t, new Set())
      m.get(s)!.add(t)
      m.get(t)!.add(s)
    }
    return m
  }, [graphData.links])

  useEffect(() => {
    const el = svgRef.current
    if (!el) return
    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      const delta = e.deltaY > 0 ? -0.1 : 0.1
      setScale((s) => Math.min(2.5, Math.max(0.4, s + delta)))
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [focused])

  const handleMouseDown = useCallback(
    (e: ReactMouseEvent) => {
      if ((e.target as Element).closest('[data-node]')) return
      e.preventDefault()
      setDragging(true)
      setDragStart({ x: e.clientX - translate.x, y: e.clientY - translate.y })
    },
    [translate],
  )
  const handleMouseMove = useCallback(
    (e: ReactMouseEvent) => {
      if (!dragging) return
      setTranslate({ x: e.clientX - dragStart.x, y: e.clientY - dragStart.y })
    },
    [dragging, dragStart],
  )
  const handleMouseUp = useCallback(() => setDragging(false), [])

  useEffect(() => {
    const svg = svgRef.current
    const group = groupRef.current
    if (!svg || !group || graphData.nodes.length === 0) return

    const svgNS = 'http://www.w3.org/2000/svg'
    const create = (tag: string): SVGElement => document.createElementNS(svgNS, tag)

    const rect = svg.getBoundingClientRect()
    const width = rect.width || 800
    const height = svg.clientHeight || 400

    while (group.firstChild) group.removeChild(group.firstChild)

    const simNodes: SimNode[] = graphData.nodes.map((n) => ({ ...n, borrowed: borrowedSet.has(n.id) }))
    const simLinks: SimLink[] = graphData.links.map((l) => ({ ...l }))

    const defs = create('defs')
    Object.entries(LINK_STYLE).forEach(([type, style]) => {
      const marker = create('marker')
      marker.setAttribute('id', `ag-arrow-${type}`)
      marker.setAttribute('markerWidth', '8')
      marker.setAttribute('markerHeight', '8')
      marker.setAttribute('refX', '6')
      marker.setAttribute('refY', '3')
      marker.setAttribute('orient', 'auto')
      marker.setAttribute('markerUnits', 'strokeWidth')
      const path = create('path')
      path.setAttribute('d', 'M0,0 L0,6 L6,3 z')
      path.setAttribute('fill', style.stroke)
      marker.appendChild(path)
      defs.appendChild(marker)
    })
    group.appendChild(defs)

    const linkLayer = create('g') as SVGGElement
    linkLayer.setAttribute('class', 'ag-links')
    group.appendChild(linkLayer)
    const linkEls: SVGPathElement[] = simLinks.map((l) => {
      const path = create('path') as SVGPathElement
      const style = LINK_STYLE[l.type]
      path.setAttribute('stroke', style.stroke)
      path.setAttribute('stroke-width', '1.5')
      path.setAttribute('stroke-dasharray', style.dash)
      path.setAttribute('fill', 'none')
      path.setAttribute('opacity', String(style.opacity))
      path.setAttribute('marker-end', `url(#ag-arrow-${l.type})`)
      path.setAttribute('class', 'ag-link')
      linkLayer.appendChild(path)
      return path
    })

    const nodeLayer = create('g') as SVGGElement
    nodeLayer.setAttribute('class', 'ag-nodes')
    group.appendChild(nodeLayer)

    interface NodeEl {
      g: SVGGElement
      applyDim: (dim: boolean) => void
    }
    const nodeEls: NodeEl[] = simNodes.map((node) => {
      const g = create('g') as SVGGElement
      g.setAttribute('class', 'ag-node')
      g.setAttribute('data-node', node.id)

      const { w, h } = nodeSize(node)
      const color = nodeColor(node, !!node.borrowed)
      const halfW = w / 2
      const halfH = h / 2

      const shadow = create('rect')
      shadow.setAttribute('x', String(-halfW))
      shadow.setAttribute('y', String(-halfH + 1))
      shadow.setAttribute('width', String(w))
      shadow.setAttribute('height', String(h))
      shadow.setAttribute('rx', '10')
      shadow.setAttribute('ry', '10')
      shadow.setAttribute('fill', 'rgba(15,20,25,0.06)')
      g.appendChild(shadow)

      const rect = create('rect')
      rect.setAttribute('x', String(-halfW))
      rect.setAttribute('y', String(-halfH))
      rect.setAttribute('width', String(w))
      rect.setAttribute('height', String(h))
      rect.setAttribute('rx', '10')
      rect.setAttribute('ry', '10')
      rect.setAttribute('fill', color.bg)
      rect.setAttribute('stroke', color.border)
      rect.setAttribute('stroke-width', '1.5')
      g.appendChild(rect)

      const stripe = create('rect')
      stripe.setAttribute('x', String(-halfW))
      stripe.setAttribute('y', String(-halfH))
      stripe.setAttribute('width', '4')
      stripe.setAttribute('height', String(h))
      stripe.setAttribute('rx', '2')
      stripe.setAttribute('fill', TYPE_BADGE[node.type])
      g.appendChild(stripe)

      const badge = create('rect')
      badge.setAttribute('x', String(halfW - 26))
      badge.setAttribute('y', String(-halfH - 4))
      badge.setAttribute('width', '24')
      badge.setAttribute('height', '14')
      badge.setAttribute('rx', '4')
      badge.setAttribute('fill', TYPE_BADGE[node.type])
      badge.setAttribute('opacity', '0.95')
      g.appendChild(badge)
      const badgeText = create('text')
      badgeText.setAttribute('x', String(halfW - 14))
      badgeText.setAttribute('y', String(-halfH + 6))
      badgeText.setAttribute('text-anchor', 'middle')
      badgeText.setAttribute('font-size', '9')
      badgeText.setAttribute('font-weight', '700')
      badgeText.setAttribute('fill', '#fff')
      badgeText.setAttribute('letter-spacing', '0.04em')
      badgeText.textContent = TYPE_LABEL[node.type]
      g.appendChild(badgeText)

      const title = create('text')
      title.setAttribute('x', '0')
      title.setAttribute('y', String(-4))
      title.setAttribute('text-anchor', 'middle')
      title.setAttribute('font-size', '13')
      title.setAttribute('font-weight', '600')
      title.setAttribute('fill', color.fg)
      title.setAttribute('style', 'font-family: var(--font-sans); letter-spacing: -0.01em;')
      title.textContent = node.label
      g.appendChild(title)

      const sub = create('text')
      sub.setAttribute('x', '0')
      sub.setAttribute('y', '12')
      sub.setAttribute('text-anchor', 'middle')
      sub.setAttribute('font-size', '10')
      sub.setAttribute('fill', color.fg)
      sub.setAttribute('opacity', '0.65')
      sub.setAttribute('style', 'font-family: var(--font-sans);')
      let subText = ''
      if (node.type === 'agent') {
        subText = node.borrowed ? '借调视角' : node.stance ? truncate(node.stance, 14) : '常驻 Agent'
      } else if (node.type === 'conflict') {
        subText = node.conflictType ? translateConflictType(node.conflictType) : '冲突节点'
      } else {
        subText = sourceLabel(node.evidenceSource || '')
      }
      sub.textContent = subText
      g.appendChild(sub)

      const enter = (e: MouseEvent): void => {
        setHoverNodeId(node.id)
        setTooltip({ x: e.clientX, y: e.clientY, text: tooltipText(node) })
      }
      const move = (e: MouseEvent): void => {
        setTooltip({ x: e.clientX, y: e.clientY, text: tooltipText(node) })
      }
      const leave = (): void => {
        setHoverNodeId((v) => (v === node.id ? null : v))
        setTooltip(null)
      }
      const applyDim = (dim: boolean): void => {
        if (dim) g.setAttribute('opacity', '0.18')
        else g.setAttribute('opacity', '1')
      }
      g.addEventListener('mouseenter', enter)
      g.addEventListener('mousemove', move)
      g.addEventListener('mouseleave', leave)
      g.style.cursor = 'pointer'

      nodeLayer.appendChild(g)
      return { g, applyDim }
    })

    const simulation = forceSimulation<SimNode, SimLink>(simNodes)
      .force('charge', forceManyBody<SimNode>().strength(-280))
      .force(
        'link',
        forceLink<SimNode, SimLink>(simLinks)
          .id((d) => d.id)
          .distance((l) => linkDistance(l.type))
          .strength((l) => l.weight * 0.6),
      )
      .force('center', forceCenter<SimNode>(width / 2, height / 2))
      .force('collide', forceCollide<SimNode>().radius((d) => Math.max(NODE_W[d.type], NODE_H) / 2 + 12))
      .alphaDecay(0.045)

    simulation.on('tick', () => {
      simLinks.forEach((l, i) => {
        const s = l.source as SimNode
        const t = l.target as SimNode
        const line = linkEls[i]
        if (line && s.x != null && s.y != null && t.x != null && t.y != null) {
          const mx = (s.x + t.x) / 2
          const my = (s.y + t.y) / 2
          const dx = t.x - s.x
          const dy = t.y - s.y
          const dist = Math.sqrt(dx * dx + dy * dy)
          const offset = Math.min(40, dist * 0.12)
          const cx1 = (s.x + mx) / 2
          const cy1 = (s.y + my) / 2 - offset
          const cx2 = (t.x + mx) / 2
          const cy2 = (t.y + my) / 2 + offset
          line.setAttribute('d', `M ${s.x},${s.y} C ${cx1},${cy1} ${cx2},${cy2} ${t.x},${t.y}`)
        }
      })
      simNodes.forEach((n, i) => {
        const item = nodeEls[i]
        if (item && n.x != null && n.y != null) {
          item.g.setAttribute('transform', `translate(${n.x},${n.y})`)
        }
      })
    })

    return () => {
      simulation.stop()
    }
  }, [signature, borrowedSet, focused])

  useEffect(() => {
    if (!groupRef.current) return
    const nodeGroups = groupRef.current.querySelectorAll<SVGGElement>('[data-node]')
    const highlight = hoverNodeId
    const neighbors = highlight ? neighborMap.get(highlight) ?? new Set() : new Set()
    nodeGroups.forEach((g) => {
      const id = g.getAttribute('data-node')!
      if (!highlight) {
        g.setAttribute('opacity', '1')
        return
      }
      if (id === highlight || neighbors.has(id)) {
        g.setAttribute('opacity', '1')
      } else {
        g.setAttribute('opacity', '0.18')
      }
    })
    const links = groupRef.current.querySelectorAll<SVGPathElement>('.ag-link')
    links.forEach((l) => l.setAttribute('opacity', highlight ? '0.15' : '0.75'))
  }, [hoverNodeId, neighborMap, graphData])

  if (nodeCount === 0) {
    return (
      <div className="graph-container graph-empty">
        <span className="graph-title">Agent / 冲突 / 证据 拓扑图</span>
        <span className="graph-empty-hint">当前会议暂无图数据（需要 team_config 或 conflict）。</span>
      </div>
    )
  }

  const compactHeight = Math.max(360, Math.min(540, 80 + nodeCount * 18))
  const body = (
    <div className={`graph-container ${focused ? 'is-focused' : ''}`}>
      <div className="graph-header">
        <div className="graph-title-block">
          <span className="graph-title">Agent / 冲突 / 证据 拓扑图</span>
          <span className="graph-stats">
            {nodeCount} 节点 · {linkCount} 连线
          </span>
        </div>
        <div className="graph-zoom-controls">
          <button type="button" className="btn btn-sm" onClick={() => setScale((s) => Math.min(2.5, s + 0.2))}>
            +
          </button>
          <span className="graph-zoom-label">{Math.round(scale * 100)}%</span>
          <button type="button" className="btn btn-sm" onClick={() => setScale((s) => Math.max(0.4, s - 0.2))}>
            −
          </button>
          <button
            type="button"
            className="btn btn-sm"
            onClick={() => {
              setScale(1)
              setTranslate({ x: 0, y: 0 })
            }}
          >
            重置
          </button>
          <button
            type="button"
            className="btn btn-sm btn-primary"
            onClick={() => setFocused(true)}
            title="聚焦模式（撑起画布专注查看，不改变缩放）"
          >
            <svg width="13" height="13" viewBox="0 0 13 13" fill="none" style={{ marginRight: 4 }}>
              <path
                d="M2 5V2H5M11 5V2H8M2 8V11H5M11 8V11H8"
                stroke="currentColor"
                strokeWidth="1.4"
                strokeLinecap="round"
              />
            </svg>
            聚焦查看
          </button>
        </div>
      </div>

      <div className="graph-scroll">
        <svg
          ref={svgRef}
          width="100%"
          height={focused ? '100%' : compactHeight}
          className="agent-graph-svg"
          onMouseDown={handleMouseDown}
          onMouseMove={handleMouseMove}
          onMouseUp={handleMouseUp}
          onMouseLeave={handleMouseUp}
          style={{ cursor: dragging ? 'grabbing' : 'grab' }}
        >
          <defs>
            <pattern id="ag-grid" width="32" height="32" patternUnits="userSpaceOnUse">
              <path d="M 32 0 L 0 0 0 32" fill="none" stroke="#f4f6f8" strokeWidth="1" />
            </pattern>
          </defs>
          <rect width="100%" height="100%" fill="url(#ag-grid)" opacity={0.6} />
          <g ref={groupRef} transform={`translate(${translate.x}, ${translate.y}) scale(${scale})`} />
        </svg>
      </div>

      <div className="graph-legend">
        <span className="legend-item"><span className="legend-dot" style={{ background: '#3b82f6' }} /> Agent</span>
        <span className="legend-item"><span className="legend-dot" style={{ background: '#f59e0b' }} /> 冲突</span>
        <span className="legend-item"><span className="legend-dot" style={{ background: '#06b6d4' }} /> 证据</span>
        <span className="legend-item legend-line-item"><span className="legend-line-solid" style={{ background: '#94a3b8' }} /> argues</span>
        <span className="legend-item legend-line-item"><span className="legend-line-solid" style={{ background: '#f59e0b' }} /> conflicts</span>
        <span className="legend-item legend-line-item"><span className="legend-line-solid" style={{ background: '#10b981' }} /> supports</span>
      </div>

      <div className="graph-hint">滚轮缩放 · 空白处拖拽 · hover 节点查看详情</div>

      {tooltip && (
        <div className="ag-tooltip" style={{ left: tooltip.x + 12, top: tooltip.y + 12 }}>
          {tooltip.text.split('\n').map((line, i) => (
            <div key={i}>{line}</div>
          ))}
        </div>
      )}
    </div>
  )

  return (
    <FocusMode
      open={focused}
      onClose={() => setFocused(false)}
      title={
        <span>
          Agent / 冲突 / 证据 拓扑图 ·{' '}
          <span style={{ color: 'var(--text-muted)', fontWeight: 400, fontSize: 12 }}>
            {nodeCount} 节点 · {linkCount} 连线
          </span>
        </span>
      }
      hint="按 Esc 或点击背景关闭"
    >
      {body}
    </FocusMode>
  )
}

function truncate(s: string, n: number): string {
  if (!s) return ''
  return s.length > n ? s.slice(0, n - 1) + '…' : s
}

function translateConflictType(t: string): string {
  const m: Record<string, string> = {
    'technical': '技术选型',
    'scope': '范围/优先级',
    'resource': '资源/预算',
    'product': '产品定位',
    'ux': '交互/体验',
    'data': '数据策略',
    'security': '安全合规',
  }
  return m[t] || t
}
