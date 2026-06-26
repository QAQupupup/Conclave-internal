// 力导向图可视化组件：展示 agent / 冲突 / 证据 拓扑关系
// 使用 d3-force 物理模拟 + SVG 渲染（仅依赖 d3-force 子包，不引入完整 d3）
// 对齐 docs/iteration-2-design.md §5
import { useEffect, useMemo, useRef, useState } from 'react'
import { forceCenter, forceCollide, forceLink, forceManyBody, forceSimulation } from 'd3-force'
import type { SimulationLinkDatum, SimulationNodeDatum } from 'd3-force'
import { useMeeting } from '../store/MeetingContext.tsx'
import { ROLE_LABELS } from '../types/events.ts'
import type { MeetingState, Role } from '../types/events.ts'
import type { ForceGraphData, GraphLink, GraphNode } from '../types/graph.ts'

// ---------- 视觉常量 ----------

// 节点半径（agent 圆形 / conflict 菱形半对角线 / evidence 方形半边长）
const NODE_RADIUS = { agent: 20, conflict: 18, evidence: 14 } as const

// agent 节点按角色着色（与 index.css 角色变量一致）
const ROLE_COLORS: Record<string, string> = {
  moderator: '#1971c2',
  product_architect: '#7048e8',
  engineer: '#2f9e44',
}
const OTHER_AGENT_COLOR = '#868e96'
const CONFLICT_COLOR = '#e8590c'
const EVIDENCE_COLOR = '#15aabf'

// 连线样式：颜色 + 虚线模式（argues 实线 / conflicts 红色虚线 / supports 绿色实线 / cites 灰色点线）
const LINK_STYLE: Record<GraphLink['type'], { stroke: string; dash: string }> = {
  argues: { stroke: '#868e96', dash: '' },
  conflicts: { stroke: '#e03131', dash: '6 4' },
  supports: { stroke: '#2f9e44', dash: '' },
  cites: { stroke: '#adb5bd', dash: '2 4' },
}

// ---------- d3-force 模拟用的节点 / 连线类型 ----------

/** 模拟节点：GraphNode + d3 力学坐标字段 */
interface SimNode extends SimulationNodeDatum, GraphNode {}

/** 模拟连线：保留 type/weight，source/target 在 forceLink 初始化时被解析为节点对象 */
interface SimLink extends SimulationLinkDatum<SimNode> {
  type: GraphLink['type']
  weight: number
}

// ---------- 辅助函数 ----------

function agentColor(role: string | undefined): string {
  if (role && ROLE_COLORS[role]) return ROLE_COLORS[role]
  return OTHER_AGENT_COLOR
}

function nodeRadius(n: SimNode): number {
  if (n.type === 'agent') return NODE_RADIUS.agent
  if (n.type === 'conflict') return NODE_RADIUS.conflict
  return NODE_RADIUS.evidence
}

function labelOffset(type: GraphNode['type']): number {
  if (type === 'agent') return NODE_RADIUS.agent + 14
  if (type === 'conflict') return NODE_RADIUS.conflict + 16
  return NODE_RADIUS.evidence + 14
}

function linkDistance(type: GraphLink['type']): number {
  if (type === 'argues') return 70
  if (type === 'conflicts') return 95
  if (type === 'supports') return 55
  return 45 // cites
}

function tooltipText(n: SimNode): string {
  if (n.type === 'agent') {
    const role = n.role ? (ROLE_LABELS[n.role as Role] ?? n.role) : 'Agent'
    return n.stance ? `${role}\n立场：${n.stance}` : role
  }
  if (n.type === 'conflict') {
    return n.conflictType ? `${n.label}\n类型：${n.conflictType}` : n.label
  }
  return n.evidenceSource ? `${n.label}\n来源：${n.evidenceSource}` : n.label
}

/**
 * 从 MeetingState 推导力导向图结构：
 * - agent 节点：moderator + team_config
 * - conflict 节点：conflicts[]
 * - evidence 节点：evidence_set[].assessments[]（按冲突+序号去重）
 * - 连线：agent↔agent(conflicts) / agent↔conflict(argues) / evidence↔conflict(supports|cites)
 */
function buildGraphData(meeting: MeetingState): ForceGraphData {
  const nodes: GraphNode[] = []
  const links: GraphLink[] = []
  const seen = new Set<string>()
  const addNode = (n: GraphNode): void => {
    if (!seen.has(n.id)) {
      seen.add(n.id)
      nodes.push(n)
    }
  }

  // 1. 主持人节点
  addNode({ id: 'moderator', label: '主持人', type: 'agent', role: 'moderator' })

  // 2. team_config 中的 agent 节点 + 队内不同立场之间的冲突连线
  const team = meeting.team_config ?? []
  team.forEach((m, i) => {
    addNode({
      id: m.role,
      label: ROLE_LABELS[m.role] ?? m.role,
      type: 'agent',
      role: m.role,
      stance: m.stance,
    })
    if (i > 0 && team[0]) {
      links.push({ source: team[0].role, target: m.role, type: 'conflicts', weight: 0.5 })
    }
  })

  // 3. 主持人 ↔ 队内 agent：argues（保证无冲突时图也连通）
  team.forEach((m) => {
    links.push({ source: 'moderator', target: m.role, type: 'argues', weight: 0.4 })
  })

  // 3.5 借调 agent 节点（灰色，标注"借调"）
  const borrowed = meeting.borrowed_agents ?? []
  borrowed.forEach((b) => {
    const bid = `borrow:${b.role}`
    addNode({
      id: bid,
      label: b.role,
      type: 'agent',
      role: b.role,
      stance: '借调视角',
    })
    // 借调 agent 连到主持人（argues，弱权重）
    links.push({ source: 'moderator', target: bid, type: 'argues', weight: 0.3 })
  })

  // 4. 冲突节点 + agent/主持人参与冲突（argues）
  const conflicts = meeting.conflicts ?? []
  conflicts.forEach((c, i) => {
    const cid = c.id ?? `conflict-${i}`
    addNode({
      id: cid,
      label: `冲突${i + 1}`,
      type: 'conflict',
      conflictType: c.conflict_type ?? c.type,
    })
    // 主持人参与仲裁
    links.push({ source: 'moderator', target: cid, type: 'argues', weight: 0.8 })
    // 队内 agent 均为冲突当事方
    team.forEach((m) => {
      links.push({ source: m.role, target: cid, type: 'argues', weight: 0.6 })
    })
  })

  // 5. 证据节点 + evidence↔conflict 连线（supports 为 a/b 时绿色实线，否则 cites 灰色点线）
  const evidenceSet = meeting.evidence_set ?? []
  evidenceSet.forEach((es) => {
    const cid = es.conflict_id
    const assessments = es.assessments ?? []
    assessments.forEach((a, j) => {
      const eid = `evidence-${cid}-${j}`
      const src = a.source ?? ''
      const sourceLabel = src.startsWith('doc:')
        ? '文档证据'
        : src.startsWith('web:')
          ? '网络检索'
          : src.startsWith('common_knowledge')
            ? '通用知识'
            : '证据'
      addNode({ id: eid, label: sourceLabel, type: 'evidence', evidenceSource: src })
      const linkType: GraphLink['type'] =
        a.supports === 'a' || a.supports === 'b' ? 'supports' : 'cites'
      links.push({ source: eid, target: cid, type: linkType, weight: 0.6 })
    })
  })

  return { nodes, links }
}

const EMPTY_GRAPH: ForceGraphData = { nodes: [], links: [] }

// ---------- 组件 ----------

export function AgentGraph() {
  const { store } = useMeeting()
  const [expanded, setExpanded] = useState(false)
  const [tooltip, setTooltip] = useState<{ x: number; y: number; text: string } | null>(null)
  const svgRef = useRef<SVGSVGElement>(null)

  const meeting = store.meeting
  const graphData = useMemo<ForceGraphData>(
    () => (meeting ? buildGraphData(meeting) : EMPTY_GRAPH),
    [meeting],
  )
  // 通过 ref 让 effect 始终读到最新图数据
  const graphDataRef = useRef(graphData)
  graphDataRef.current = graphData

  // 结构签名：仅当节点 / 连线集合变化时重建模拟，避免每条聊天消息都重启布局
  const signature = useMemo(() => {
    const ns = graphData.nodes.map((n) => n.id).join(',')
    const ls = graphData.links.map((l) => `${l.source}->${l.target}:${l.type}`).join('|')
    return `${ns}#${ls}`
  }, [graphData])

  const nodeCount = graphData.nodes.length
  const linkCount = graphData.links.length

  useEffect(() => {
    if (!expanded) return
    const svg = svgRef.current
    const data = graphDataRef.current
    if (!svg || data.nodes.length === 0) return

    const svgNS = 'http://www.w3.org/2000/svg'
    const create = (tag: string): SVGElement => document.createElementNS(svgNS, tag)

    const rect = svg.getBoundingClientRect()
    const width = rect.width || 800
    const height = svg.clientHeight || 300

    // 清空旧内容
    while (svg.firstChild) svg.removeChild(svg.firstChild)

    // 拷贝一份供模拟使用（force 会向其写入坐标）
    const simNodes: SimNode[] = data.nodes.map((n) => ({ ...n }))
    const simLinks: SimLink[] = data.links.map((l) => ({ ...l }))

    // 连线层
    const linkLayer = create('g') as SVGGElement
    linkLayer.setAttribute('class', 'ag-links')
    svg.appendChild(linkLayer)
    const linkEls: SVGLineElement[] = simLinks.map((l) => {
      const line = create('line') as SVGLineElement
      const style = LINK_STYLE[l.type]
      line.setAttribute('stroke', style.stroke)
      line.setAttribute('stroke-width', '1.4')
      line.setAttribute('stroke-dasharray', style.dash)
      line.setAttribute('opacity', '0.75')
      linkLayer.appendChild(line)
      return line
    })

    // 节点层
    const nodeLayer = create('g') as SVGGElement
    nodeLayer.setAttribute('class', 'ag-nodes')
    svg.appendChild(nodeLayer)

    interface NodeEl {
      g: SVGGElement
      enter: (e: MouseEvent) => void
      move: (e: MouseEvent) => void
      leave: () => void
    }
    const nodeEls: NodeEl[] = simNodes.map((node) => {
      const g = create('g') as SVGGElement
      g.setAttribute('class', `ag-node ag-node-${node.type}`)

      if (node.type === 'agent') {
        const c = create('circle') as SVGCircleElement
        c.setAttribute('r', String(NODE_RADIUS.agent))
        c.setAttribute('fill', agentColor(node.role))
        c.setAttribute('stroke', '#fff')
        c.setAttribute('stroke-width', '1.5')
        g.appendChild(c)
      } else if (node.type === 'conflict') {
        const p = create('polygon') as SVGPolygonElement
        const r = NODE_RADIUS.conflict
        p.setAttribute('points', `0,${-r} ${r},0 0,${r} ${-r},0`)
        p.setAttribute('fill', CONFLICT_COLOR)
        p.setAttribute('stroke', '#fff')
        p.setAttribute('stroke-width', '1.5')
        g.appendChild(p)
      } else {
        const r = NODE_RADIUS.evidence
        const re = create('rect') as SVGRectElement
        re.setAttribute('x', String(-r))
        re.setAttribute('y', String(-r))
        re.setAttribute('width', String(r * 2))
        re.setAttribute('height', String(r * 2))
        re.setAttribute('fill', EVIDENCE_COLOR)
        re.setAttribute('stroke', '#fff')
        re.setAttribute('stroke-width', '1.5')
        g.appendChild(re)
      }

      const text = create('text') as SVGTextElement
      text.setAttribute('class', 'ag-label')
      text.setAttribute('text-anchor', 'middle')
      text.setAttribute('x', '0')
      text.setAttribute('y', String(labelOffset(node.type)))
      text.textContent = node.label
      g.appendChild(text)

      const enter = (e: MouseEvent): void => {
        setTooltip({ x: e.clientX, y: e.clientY, text: tooltipText(node) })
      }
      const move = (e: MouseEvent): void => {
        setTooltip({ x: e.clientX, y: e.clientY, text: tooltipText(node) })
      }
      const leave = (): void => setTooltip(null)
      g.addEventListener('mouseenter', enter)
      g.addEventListener('mousemove', move)
      g.addEventListener('mouseleave', leave)

      nodeLayer.appendChild(g)
      return { g, enter, move, leave }
    })

    // d3-force 模拟：斥力 + 弹簧 + 居中 + 碰撞
    const simulation = forceSimulation<SimNode, SimLink>(simNodes)
      .force('charge', forceManyBody<SimNode>().strength(-160))
      .force(
        'link',
        forceLink<SimNode, SimLink>(simLinks)
          .id((d) => d.id)
          .distance((l) => linkDistance(l.type))
          .strength((l) => l.weight * 0.4),
      )
      .force('center', forceCenter<SimNode>(width / 2, height / 2))
      .force('collide', forceCollide<SimNode>().radius((d) => nodeRadius(d) + 8))

    simulation.on('tick', () => {
      simLinks.forEach((l, i) => {
        const s = l.source as SimNode
        const t = l.target as SimNode
        const line = linkEls[i]
        if (line) {
          line.setAttribute('x1', String(s.x ?? 0))
          line.setAttribute('y1', String(s.y ?? 0))
          line.setAttribute('x2', String(t.x ?? 0))
          line.setAttribute('y2', String(t.y ?? 0))
        }
      })
      simNodes.forEach((n, i) => {
        const item = nodeEls[i]
        if (item) {
          item.g.setAttribute('transform', `translate(${n.x ?? 0},${n.y ?? 0})`)
        }
      })
    })

    return () => {
      simulation.stop()
      nodeEls.forEach((item) => {
        item.g.removeEventListener('mouseenter', item.enter)
        item.g.removeEventListener('mousemove', item.move)
        item.g.removeEventListener('mouseleave', item.leave)
      })
    }
  }, [expanded, signature])

  // 会议未开始或无节点时不显示
  if (!meeting || nodeCount === 0) return null

  if (!expanded) {
    return (
      <div className="graph-collapsed-bar">
        <button type="button" className="btn btn-ghost" onClick={() => setExpanded(true)}>
          展开拓扑图（{nodeCount} 节点 / {linkCount} 连线）
        </button>
      </div>
    )
  }

  // 节点超过 20 个时允许滚动（svg 加高，外层限高滚动）
  const svgHeight = nodeCount > 20 ? 460 : 300

  return (
    <div className="graph-container">
      <div className="graph-header">
        <span className="graph-title">Agent / 冲突 / 证据 拓扑图</span>
        <button type="button" className="btn btn-ghost" onClick={() => setExpanded(false)}>
          收起
        </button>
      </div>
      <div className="graph-scroll">
        <svg ref={svgRef} width="100%" height={svgHeight} className="agent-graph-svg" />
      </div>
      {tooltip && (
        <div className="ag-tooltip" style={{ left: tooltip.x + 12, top: tooltip.y + 12 }}>
          {tooltip.text.split('\n').map((line, i) => (
            <div key={i}>{line}</div>
          ))}
        </div>
      )}
    </div>
  )
}
