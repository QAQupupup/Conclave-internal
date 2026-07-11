// AgentGraph v2：会议桌拓扑图
// 设计理念：
//   - 圆桌隐喻：主持人在桌首，Agent 围坐，冲突/证据/产出物依次在桌上出现
//   - 留白简约底 + 低饱和糖果色点缀（色条、小圆点、状态标记）
//   - 不用力导向图，固定布局避免抖动；节点按阶段动态出现/淡入
//   - Agent 卡片：图标圆点(糖果色) + 中文名(主) + bias标签(胶囊)
//   - 支持动态路由(flow_plan/dynamic_routing)：跳过的阶段在进度条上标注
//   - 连线用柔和贝塞尔曲线，按关系类型着色；不画全连接，只画有语义的连线
import { useEffect, useMemo, useRef, useState } from 'react'
import { useMeeting } from '../store/MeetingContext.tsx'
import { ROLE_META, STAGE_LABELS, STAGE_ORDER } from '../types/events.ts'
import type { MeetingState, Role, Stage } from '../types/events.ts'
import { FocusMode } from './FocusMode.tsx'
import type { GraphNode, GraphLink } from '../types/graph.ts'

// ============================================================
// 布局常量（画布坐标系，viewBox 0 0 W H）
// ============================================================
const W = 780
const H = 540
const CX = W / 2
const CY = H / 2 + 10

// 桌面椭圆参数
const TABLE_RX = 220
const TABLE_RY = 125
const TABLE_BOTTOM = CY + TABLE_RY

// Agent 卡片尺寸
const AGENT_CARD_W = 140
const AGENT_CARD_H = 56
const CONFLICT_SIZE = 28       // 冲突菱形对角线一半
const EVIDENCE_W = 80
const EVIDENCE_H = 28
const ARTIFACT_W = 110
const ARTIFACT_H = 36

// ============================================================
// 糖果色调色板（节点类型色，低饱和）
// ============================================================
const CANDY = {
  conflict: '#E8A5A5',     // 柔和珊瑚粉（冲突）
  conflictBg: '#FDF2F2',
  evidence: '#89BFD6',     // 柔和天蓝（证据）
  evidenceBg: '#EEF5F9',
  artifact: '#C7B7E2',     // 柔和淡紫（产出物）
  artifactBg: '#F4F0F9',
  link: '#D5DAE0',         // 默认连线色（极淡灰蓝）
  linkConflict: '#E8A5A5',
  linkSupport: '#9CCBB5',
  table: '#F5F6F8',        // 桌面底色
  tableBorder: '#EAECF0',
  textPrimary: '#2D3748',
  textSecondary: '#5A6878',
  textTertiary: '#8492A6',
  borrowed: '#B0B5BE',     // 借调角色灰色
} as const

// ============================================================
// 数据构建：从 MeetingState 计算节点/连线/位置
// ============================================================

interface Positioned { x: number; y: number }
interface AgentNode extends GraphNode, Positioned {
  role: Role
  en: string
  bias: string
  candy: string
  candySoft: string
  icon: string
  borrowed?: boolean
  status?: 'speaking' | 'spoken' | 'waiting'
}
interface ConflictNode extends GraphNode, Positioned {
  conflictType: string
  summary: string
  sideA?: string
  sideB?: string
  pairA?: string    // 关联的 agent id
  pairB?: string
  resolved?: boolean
  verdict?: 'a' | 'b' | 'compromise'
}
interface EvidenceNode extends GraphNode, Positioned {
  source: string
  supports: 'a' | 'b' | 'neutral' | 'irrelevant'
  conflictId: string
}
interface ArtifactNode extends GraphNode, Positioned {
  deliverableType?: string
}
interface TableLink extends GraphLink {
  from: Positioned
  to: Positioned
  curved?: number
}

interface LayoutData {
  agents: AgentNode[]
  conflicts: ConflictNode[]
  evidences: EvidenceNode[]
  artifact: ArtifactNode | null
  links: TableLink[]
  stage: Stage | null
  status: string
  skippedStages: Stage[]
}

// 角色在桌面的座位位置：主持人在桌首(顶部正中)，其余角色左右对称分布
// 左侧：安全、产品、工程；右侧：UX、数据、市场

function polarToCartesian(angleDeg: number, rx: number, ry: number): { x: number; y: number } {
  const rad = ((angleDeg - 90) * Math.PI) / 180 // -90 使 0度在正上方
  return {
    x: CX + Math.cos(rad) * rx,
    y: CY + Math.sin(rad) * ry,
  }
}

function buildLayout(meeting: MeetingState): LayoutData {
  const stage = (meeting.stage ?? 'clarify') as Stage
  const status = meeting.status ?? 'idle'
  const team = meeting.team_config ?? []
  const borrowed = meeting.borrowed_agents ?? []
  const conflicts = meeting.conflicts ?? []
  const evidenceSet = meeting.evidence_set ?? []
  const artifact = meeting.artifact ?? null
  const decisions = meeting.decision_record?.decisions ?? []

  // 解析跳过的阶段
  const flowPlan = meeting.flow_plan ?? 'full'
  let skippedStages: Stage[] = []
  if (flowPlan === 'simple') {
    skippedStages = ['cross_team', 'evidence_check', 'arbitrate']
  } else if (flowPlan === 'standard') {
    // standard 模式下无冲突时跳过 evidence_check，但这里无法预判，留空
    skippedStages = []
  }

  // ---- Agent 节点定位 ----
  // 将主持人放在桌首，其他 team 成员按 SEAT_MAP 角度均匀分布
  const agents: AgentNode[] = []
  const agentAngleMap = new Map<string, number>()

  // 始终有主持人（桌首，椭圆顶部上方）
  const modMeta = ROLE_META.moderator
  const modPos = polarToCartesian(0, TABLE_RX + 5, TABLE_RY + 40)
  agents.push({
    id: 'moderator',
    label: modMeta.label,
    type: 'agent',
    role: 'moderator',
    en: modMeta.en,
    bias: modMeta.bias,
    candy: modMeta.candy,
    candySoft: modMeta.candySoft,
    icon: modMeta.icon,
    x: modPos.x,
    y: modPos.y,
    // 主持人只在澄清阶段开场、跨队辩论引导、仲裁阶段裁决时发言；队内发言阶段不发言
    status: (stage === 'clarify' || stage === 'arbitrate') ? 'speaking' :
            (stage === 'cross_team' || stage === 'evidence_check') ? 'spoken' : 'waiting',
  })
  agentAngleMap.set('moderator', 0)

  // 团队成员：按 SEAT_MAP 预定义角度定位
  // 为了在不同 team 配置下都均匀分布，我们先收集参会角色，按角度排序后微调到椭圆均匀分布
  const teamRoles = team.map(m => m.role).filter(r => r !== 'moderator')
  // 如果某个角色没有预定义座位，按左右交替分配
  const leftRoles = ['security_expert', 'product_architect', 'engineer']
  const rightRoles = ['ux_designer', 'data_engineer', 'marketing_expert']

  // 分配座位：沿下半圆弧均匀分布
  // 极坐标：0°=顶部(主持人)顺时针，90°=右，180°=底，270°=左
  // Agent 弧形：120°(右下方) → 180°(底) → 240°(左下方)，共120°，给两侧留更多边距
  const ARC_START = 120
  const ARC_END = 240
  const ARC_SPAN = ARC_END - ARC_START
  const R_ADJ = 42  // 比桌面椭圆外扩距离

  // 按角色偏好排序：右侧角色放弧的右端(小角度)，左侧角色放左端(大角度)，未知角色居中
  const sortedTeam = [...teamRoles].sort((a, b) => {
    const aSide = rightRoles.includes(a) ? 0 : (leftRoles.includes(a) ? 2 : 1)
    const bSide = rightRoles.includes(b) ? 0 : (leftRoles.includes(b) ? 2 : 1)
    return aSide - bSide
  })

  sortedTeam.forEach((roleId, idx) => {
    const count = sortedTeam.length
    let angle: number
    if (count === 1) {
      angle = 180
    } else {
      angle = ARC_START + (ARC_SPAN * idx) / (count - 1)
    }
    const meta = ROLE_META[roleId as Role] ?? {
      label: roleId, en: roleId.slice(0, 8), bias: '—',
      candy: CANDY.borrowed, candySoft: '#F7F8F9', icon: 'M6 6h4v4H6V6zm0 8h4v4H6v-4zm8-8h4v4h-4V6zm0 8h4v4h-4v-4z',
    }
    const pos = polarToCartesian(angle, TABLE_RX + R_ADJ, TABLE_RY + R_ADJ * 0.55)
    // 根据当前阶段判断发言状态
    let status: AgentNode['status'] = 'waiting'
    if (stage === 'intra_team') status = 'speaking'
    else if (['cross_team', 'evidence_check', 'arbitrate'].includes(stage)) status = 'spoken'
    else if (stage === 'produce') status = 'spoken'

    agents.push({
      id: roleId,
      label: meta.label,
      type: 'agent',
      role: roleId as Role,
      en: meta.en,
      bias: meta.bias,
      candy: meta.candy,
      candySoft: meta.candySoft,
      icon: meta.icon,
      x: pos.x,
      y: pos.y,
      status,
    })
    agentAngleMap.set(roleId, angle)
  })

  // 借调角色：放在右侧最外端，用虚线边框/灰色标记
  borrowed.forEach((b, bi) => {
    const bid = `borrow:${b.role}`
    const angle = ARC_START - 15 - bi * 12  // 弧右端稍外
    const meta = ROLE_META[b.role as Role] ?? {
      label: b.role, en: b.role.slice(0, 8), bias: 'loaned',
      candy: CANDY.borrowed, candySoft: '#F7F8F9', icon: 'M12 2l3 6 6 1-4.5 4 1 6-5.5-3-5.5 3 1-6L3 9l6-1z',
    }
    const pos = polarToCartesian(angle, TABLE_RX + R_ADJ + 15, TABLE_RY + R_ADJ * 0.55 + 8)
    agents.push({
      id: bid,
      label: meta.label,
      type: 'agent',
      role: b.role as Role,
      en: meta.en,
      bias: '借调',
      candy: CANDY.borrowed,
      candySoft: '#F7F8F9',
      icon: meta.icon,
      borrowed: true,
      x: pos.x,
      y: pos.y,
      status: 'waiting',
    })
  })

  // ---- 冲突节点：定位在相关两个 Agent 之间的桌面上 ----
  const conflictNodes: ConflictNode[] = []
  conflicts.forEach((c, i) => {
    const cid = c.id ?? `conflict-${i}`
    // 简单策略：冲突节点放在桌面中央偏上区域，多个冲突垂直排列
    const n = conflicts.length
    const spacing = 48
    const offsetY = (i - (n - 1) / 2) * spacing
    const pos = { x: CX, y: CY - 20 + offsetY }

    // 检查裁决结果
    const decision = decisions.find((d: any) => d.conflict_id === cid)
    const resolved = !!decision
    const verdict = decision?.verdict as 'a' | 'b' | 'compromise' | undefined

    conflictNodes.push({
      id: cid,
      label: `冲突 ${i + 1}`,
      type: 'conflict',
      conflictType: c.conflict_type ?? 'preference',
      summary: c.summary ?? '',
      sideA: c.side_a,
      sideB: c.side_b,
      x: pos.x,
      y: pos.y,
      resolved,
      verdict,
    })
  })

  // ---- 证据节点：定位在冲突节点周围 ----
  const evidenceNodes: EvidenceNode[] = []
  evidenceSet.forEach((es) => {
    const cid = es.conflict_id
    const assessments = es.assessments ?? []
    const cNode = conflictNodes.find(c => c.id === cid)
    if (!cNode) return
    assessments.forEach((a, j) => {
      const eid = `evidence-${cid}-${j}`
      // 证据放在冲突两侧交替
      const side = j % 2 === 0 ? -1 : 1
      const offsetX = side * (70 + Math.floor(j / 2) * 20)
      const offsetY = (Math.floor(j / 2) % 2 === 0 ? -1 : 1) * 20
      evidenceNodes.push({
        id: eid,
        label: a.source?.startsWith('web') ? '网络' : a.source?.startsWith('doc') ? '文档' : a.source?.startsWith('common') ? '常识' : '证据',
        type: 'evidence',
        source: a.source ?? '',
        supports: a.supports ?? 'neutral',
        conflictId: cid,
        x: cNode.x + offsetX,
        y: cNode.y + offsetY,
      })
    })
  })

  // ---- 产出物节点：桌尾（底部中央） ----
  let artifactNode: ArtifactNode | null = null
  const deliverableType = artifact?.deliverable_type ?? (meeting as any).deliverable_type
  if (stage === 'produce') {
    const label = !deliverableType ? '产出物' :
      deliverableType === 'prd_openapi' ? 'PRD + API' :
      deliverableType === 'prd' ? 'PRD 文档' :
      deliverableType === 'openapi' ? 'OpenAPI' :
      deliverableType === 'code_analysis' ? '代码分析' :
      deliverableType === 'data_science' ? '数据科学' :
      deliverableType === 'tested_system' ? '可测系统' :
      deliverableType === 'deployable_service' ? '可部署服务' : '产出物'
    artifactNode = {
      id: 'artifact',
      label,
      type: 'artifact' as any,
      deliverableType,
      x: CX,
      y: TABLE_BOTTOM + 40,
    }
  }

  // ---- 连线：主持人到各 Agent（argues）；Agent 到冲突（conflicts）；证据到冲突（supports/cites） ----
  const links: TableLink[] = []

  // 主持人→各Agent 连线（所有阶段都显示，但低存在感）
  const mod = agents.find(a => a.id === 'moderator')
  if (mod) {
    agents.forEach(a => {
      if (a.id === 'moderator') return
      links.push({
        source: mod.id, target: a.id, type: 'argues', weight: 0.3,
        from: mod, to: a,
      })
    })
  }

  // 跨队辩论及以后：Agent→冲突 连线
  if (['cross_team', 'evidence_check', 'arbitrate', 'produce'].includes(stage) && mod) {
    conflictNodes.forEach(c => {
      // 所有团队成员到冲突的连线（用很淡的灰色）
      agents.forEach(a => {
        if (a.id === 'moderator' || a.borrowed) return
        links.push({
          source: a.id, target: c.id, type: 'argues', weight: 0.15,
          from: a, to: c,
        })
      })
      // 主持人到冲突（仲裁关系）
      links.push({
        source: mod.id, target: c.id, type: 'argues', weight: 0.3,
        from: mod, to: c,
        curved: 0,
      })
    })
  }

  // 证据对照阶段：证据→冲突连线
  if (['evidence_check', 'arbitrate', 'produce'].includes(stage)) {
    evidenceNodes.forEach(e => {
      const cNode = conflictNodes.find(c => c.id === e.conflictId)
      if (cNode) {
        links.push({
          source: e.id, target: e.conflictId,
          type: e.supports === 'a' || e.supports === 'b' ? 'supports' : 'cites',
          weight: 0.6,
          from: e, to: cNode,
        })
      }
    })
  }

  return { agents, conflicts: conflictNodes, evidences: evidenceNodes, artifact: artifactNode, links, stage, status, skippedStages }
}

// ============================================================
// SVG 辅助
// ============================================================

function bezierPath(from: Positioned, to: Positioned, curvature = 0.3): string {
  const dx = to.x - from.x
  const dy = to.y - from.y
  const mx = (from.x + to.x) / 2
  const my = (from.y + to.y) / 2
  // 垂直于连线方向偏移控制点，形成弧线
  const nx = -dy * curvature
  const ny = dx * curvature
  return `M ${from.x},${from.y} Q ${mx + nx},${my + ny} ${to.x},${to.y}`
}

function linkColor(type: string, supports?: string): string {
  if (type === 'conflicts') return CANDY.linkConflict
  if (type === 'supports') {
    if (supports === 'a' || supports === 'b') return CANDY.linkSupport
    return CANDY.link
  }
  if (type === 'cites') return CANDY.evidence
  return CANDY.link
}

// ============================================================
// 组件
// ============================================================

export function AgentGraph() {
  const { store } = useMeeting()
  const meeting = store.meeting
  if (!meeting) return null

  const layout = useMemo(() => buildLayout(meeting), [
    meeting.stage, meeting.status,
    JSON.stringify(meeting.team_config),
    JSON.stringify(meeting.borrowed_agents),
    JSON.stringify(meeting.conflicts),
    JSON.stringify(meeting.evidence_set),
    (meeting as any).deliverable_type,
    meeting.artifact?.deliverable_type,
    JSON.stringify(meeting.decision_record),
    meeting.flow_plan,
  ])

  return <AgentGraphInner layout={layout} />
}

function AgentGraphInner({ layout }: { layout: LayoutData }) {
  const [focused, setFocused] = useState(false)
  const [hoverId, setHoverId] = useState<string | null>(null)
  const svgRef = useRef<SVGSVGElement>(null)
  const [scale, setScale] = useState(1)
  const [translate, setTranslate] = useState({ x: 0, y: 0 })
  const [dragging, setDragging] = useState(false)
  const [dragStart, setDragStart] = useState({ x: 0, y: 0 })

  const { agents, conflicts, evidences, artifact, links, stage, skippedStages } = layout
  const nodeCount = agents.length + conflicts.length + evidences.length + (artifact ? 1 : 0)
  const linkCount = links.length

  // 滚轮缩放
  useEffect(() => {
    const el = svgRef.current
    if (!el) return
    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      const delta = e.deltaY > 0 ? -0.1 : 0.1
      setScale(s => Math.min(2, Math.max(0.5, s + delta)))
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [focused])

  // 判断哪些节点在当前阶段可见（淡入显示）
  const stageIndex = stage ? STAGE_ORDER.indexOf(stage) : -1
  const isVisible = {
    conflicts: stageIndex >= STAGE_ORDER.indexOf('cross_team'),
    evidences: stageIndex >= STAGE_ORDER.indexOf('evidence_check'),
    artifact: stageIndex >= STAGE_ORDER.indexOf('produce'),
  }

  // 邻居映射（hover 高亮用）
  const neighborMap = useMemo(() => {
    const m = new Map<string, Set<string>>()
    links.forEach(l => {
      const sid = typeof l.source === 'string' ? l.source : (l.source as any).id
      const tid = typeof l.target === 'string' ? l.target : (l.target as any).id
      if (!m.has(sid)) m.set(sid, new Set())
      if (!m.has(tid)) m.set(tid, new Set())
      m.get(sid)!.add(tid)
      m.get(tid)!.add(sid)
    })
    return m
  }, [links])

  const isDim = (id: string) => hoverId && hoverId !== id && !(neighborMap.get(hoverId)?.has(id))

  const onMouseDown = (e: React.MouseEvent) => {
    if ((e.target as Element).closest('[data-node]')) return
    e.preventDefault()
    setDragging(true)
    setDragStart({ x: e.clientX - translate.x, y: e.clientY - translate.y })
  }
  const onMouseMove = (e: React.MouseEvent) => {
    if (!dragging) return
    setTranslate({ x: e.clientX - dragStart.x, y: e.clientY - dragStart.y })
  }
  const onMouseUp = () => setDragging(false)

  const body = (
    <div className={`graph-container ${focused ? 'is-focused' : ''}`}>
      <div className="graph-header">
        <div className="graph-title-block">
          <span className="graph-title">会议拓扑</span>
          <span className="graph-stats">{agents.length} 位成员{conflicts.length > 0 ? ` · ${conflicts.length} 项冲突` : ''}</span>
        </div>
        <div className="graph-zoom-controls">
          <button type="button" className="btn btn-sm" onClick={() => setScale(s => Math.min(2, s + 0.15))}>+</button>
          <span className="graph-zoom-label">{Math.round(scale * 100)}%</span>
          <button type="button" className="btn btn-sm" onClick={() => setScale(s => Math.max(0.5, s - 0.15))}>−</button>
          <button type="button" className="btn btn-sm" onClick={() => { setScale(1); setTranslate({ x: 0, y: 0 }) }}>重置</button>
          {!focused && (
            <button type="button" className="btn btn-sm btn-primary" onClick={() => setFocused(true)}>
              <svg width="13" height="13" viewBox="0 0 13 13" fill="none" style={{ marginRight: 4 }}>
                <path d="M2 5V2H5M11 5V2H8M2 8V11H5M11 8V11H8" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
              </svg>
              聚焦查看
            </button>
          )}
        </div>
      </div>

      {/* 阶段进度迷你条 */}
      <StageMiniBar current={stage} skipped={skippedStages} />

      <div className="graph-scroll">
        <svg
          ref={svgRef}
          viewBox={`0 0 ${W} ${H}`}
          width="100%"
          height={focused ? '100%' : 420}
          preserveAspectRatio="xMidYMid meet"
          className="agent-graph-svg ag-fade-in"
          onMouseDown={onMouseDown}
          onMouseMove={onMouseMove}
          onMouseUp={onMouseUp}
          onMouseLeave={onMouseUp}
          style={{ cursor: dragging ? 'grabbing' : 'grab', fontFamily: 'var(--font-sans, system-ui)' }}
        >
          <defs>
            <pattern id="ag-grid2" width="28" height="28" patternUnits="userSpaceOnUse">
              <path d="M 28 0 L 0 0 0 28" fill="none" stroke="#f6f7f9" strokeWidth="1" />
            </pattern>
            {/* 柔和阴影 */}
            <filter id="ag-shadow" x="-20%" y="-20%" width="140%" height="140%">
              <feDropShadow dx="0" dy="1" stdDeviation="2" floodColor="#1a202c" floodOpacity="0.06" />
            </filter>
            <filter id="ag-shadow-sm" x="-20%" y="-20%" width="140%" height="140%">
              <feDropShadow dx="0" dy="1" stdDeviation="1" floodColor="#1a202c" floodOpacity="0.05" />
            </filter>
          </defs>

          <rect width={W} height={H} fill="url(#ag-grid2)" opacity={0.5} />

          <g transform={`translate(${translate.x}, ${translate.y}) scale(${scale})`}>
            {/* 桌面椭圆 */}
            <ellipse
              cx={CX} cy={CY} rx={TABLE_RX} ry={TABLE_RY}
              fill={CANDY.table}
              stroke={CANDY.tableBorder}
              strokeWidth={1}
              strokeDasharray="4 4"
              opacity={0.7}
            />
            {/* 桌面中心文字：议题 */}
            <text x={CX} y={CY + 4} textAnchor="middle" fontSize={11} fill={CANDY.textTertiary} letterSpacing="0.08em">
              CONCLAVE · 会议桌
            </text>

            {/* 连线层 */}
            <g className="ag-links">
              {links.map((l, i) => {
                const sid = typeof l.source === 'string' ? l.source : (l.source as any).id
                const tid = typeof l.target === 'string' ? l.target : (l.target as any).id
                const dim = isDim(sid) || isDim(tid)
                const evNode = evidences.find(e => e.id === sid)
                const color = linkColor(l.type, evNode?.supports)
                const isModLink = sid === 'moderator' || tid === 'moderator'
                const sw = l.type === 'supports' ? 1.5 : l.type === 'conflicts' ? 1.5 : isModLink ? 1 : 0.8
                return (
                  <path
                    key={`link-${i}`}
                    d={bezierPath(l.from, l.to, l.type === 'supports' ? 0.1 : 0.2)}
                    fill="none"
                    stroke={color}
                    strokeWidth={sw}
                    strokeDasharray={l.type === 'cites' ? '3 3' : l.type === 'argues' && !isModLink ? '2 3' : ''}
                    opacity={dim ? 0.08 : l.type === 'argues' && !isModLink ? 0.25 : isModLink ? 0.35 : 0.7}
                    strokeLinecap="round"
                  />
                )
              })}
            </g>

            {/* 冲突节点 */}
            {isVisible.conflicts && (
              <g className="ag-conflicts" style={{ opacity: 1, transition: 'opacity 0.4s ease' }}>
                {conflicts.map(c => {
                  const dim = isDim(c.id)
                  const fill = c.resolved
                    ? (c.verdict === 'compromise' ? '#F0F4F2' : '#EDF7F2')
                    : CANDY.conflictBg
                  const stroke = c.resolved
                    ? (c.verdict === 'compromise' ? '#B0B8C0' : CANDY.linkSupport)
                    : CANDY.conflict
                  return (
                    <g
                      key={c.id}
                      data-node={c.id}
                      transform={`translate(${c.x}, ${c.y})`}
                      opacity={dim ? 0.2 : 1}
                      style={{ transition: 'opacity 0.2s ease' }}
                      onMouseEnter={() => setHoverId(c.id)}
                      onMouseLeave={() => setHoverId(null)}
                      filter="url(#ag-shadow-sm)"
                    >
                      {/* 菱形 */}
                      <polygon
                        points={`0,${-CONFLICT_SIZE} ${CONFLICT_SIZE},0 0,${CONFLICT_SIZE} ${-CONFLICT_SIZE},0`}
                        fill={fill}
                        stroke={stroke}
                        strokeWidth={1.5}
                      />
                      {c.resolved ? (
                        <text x={0} y={4} textAnchor="middle" fontSize={11} fill={stroke} fontWeight={600}>✓</text>
                      ) : (
                        <text x={0} y={4} textAnchor="middle" fontSize={12} fill={stroke} fontWeight={700}>!</text>
                      )}
                      <text x={0} y={CONFLICT_SIZE + 14} textAnchor="middle" fontSize={10} fill={CANDY.textSecondary}>
                        {c.label}
                      </text>
                    </g>
                  )
                })}
              </g>
            )}

            {/* 证据节点 */}
            {isVisible.evidences && (
              <g className="ag-evidence" style={{ opacity: 1, transition: 'opacity 0.4s ease 0.1s' }}>
                {evidences.map(e => {
                  const dim = isDim(e.id)
                  const stroke = e.supports === 'a' || e.supports === 'b' ? CANDY.evidence : CANDY.link
                  return (
                    <g
                      key={e.id}
                      data-node={e.id}
                      transform={`translate(${e.x}, ${e.y})`}
                      opacity={dim ? 0.2 : 1}
                      style={{ transition: 'opacity 0.2s ease' }}
                      onMouseEnter={() => setHoverId(e.id)}
                      onMouseLeave={() => setHoverId(null)}
                    >
                      <rect
                        x={-EVIDENCE_W / 2} y={-EVIDENCE_H / 2}
                        width={EVIDENCE_W} height={EVIDENCE_H} rx={6} ry={6}
                        fill={CANDY.evidenceBg}
                        stroke={stroke}
                        strokeWidth={1}
                      />
                      {/* 文档图标 */}
                      <line x1={-EVIDENCE_W / 2 + 8} y1={-EVIDENCE_H / 2 + 8} x2={-EVIDENCE_W / 2 + 8} y2={EVIDENCE_H / 2 - 8} stroke={stroke} strokeWidth={1.5} strokeLinecap="round" />
                      <text x={-EVIDENCE_W / 2 + 16} y={4} fontSize={10} fill={CANDY.textSecondary}>{e.label}</text>
                    </g>
                  )
                })}
              </g>
            )}

            {/* Agent 卡片 */}
            <g className="ag-agents">
              {agents.map(a => {
                const dim = isDim(a.id)
                const isMod = a.id === 'moderator'
                const speaking = a.status === 'speaking'
                return (
                  <AgentCard
                    key={a.id}
                    agent={a}
                    dim={!!dim}
                    isModerator={isMod}
                    speaking={speaking}
                    onHover={setHoverId}
                  />
                )
              })}
            </g>

            {/* 产出物节点 */}
            {isVisible.artifact && artifact && (
              <g
                className="ag-artifact"
                transform={`translate(${artifact.x}, ${artifact.y})`}
                style={{ opacity: 1, animation: 'ag-fadeup 0.5s ease' }}
                filter="url(#ag-shadow)"
              >
                <rect
                  x={-ARTIFACT_W / 2} y={-ARTIFACT_H / 2}
                  width={ARTIFACT_W} height={ARTIFACT_H} rx={10} ry={10}
                  fill={CANDY.artifactBg}
                  stroke={CANDY.artifact}
                  strokeWidth={1.5}
                />
                {/* 文件图标 */}
                <g transform={`translate(${-ARTIFACT_W / 2 + 10}, 0)`}>
                  <path d="M0,-8 L6,-8 L10,-4 L10,8 L0,8 Z" fill="none" stroke={CANDY.artifact} strokeWidth={1.2} strokeLinejoin="round" />
                  <path d="M6,-8 L6,-4 L10,-4" fill="none" stroke={CANDY.artifact} strokeWidth={1.2} strokeLinejoin="round" />
                </g>
                <text x={-ARTIFACT_W / 2 + 26} y={4} fontSize={12} fontWeight={600} fill="#5A4F7A">{artifact.label}</text>
              </g>
            )}
          </g>
        </svg>
      </div>

      {/* 图例 */}
      <div className="graph-legend">
        <span className="legend-item">
          <span className="legend-dot" style={{ background: '#8B8FC8' }} />主持人
        </span>
        <span className="legend-item">
          <span className="legend-dot" style={{ background: '#5EAD8F' }} />Agent
        </span>
        <span className="legend-item">
          <span className="legend-dot" style={{ background: CANDY.conflict, borderRadius: 2, transform: 'rotate(45deg)' }} />冲突
        </span>
        <span className="legend-item">
          <span className="legend-dot" style={{ background: CANDY.evidence }} />证据
        </span>
        {isVisible.artifact && (
          <span className="legend-item">
            <span className="legend-dot" style={{ background: CANDY.artifact }} />产出物
          </span>
        )}
      </div>

      <div className="graph-hint">滚轮缩放 · 拖拽平移 · hover 高亮关系链</div>
    </div>
  )

  return (
    <FocusMode
      open={focused}
      onClose={() => setFocused(false)}
      title={
        <span>
          会议拓扑 ·{' '}
          <span style={{ color: 'var(--text-muted)', fontWeight: 400, fontSize: 12 }}>
            {nodeCount} 节点 · {linkCount} 连线 · 当前：{stage ? STAGE_LABELS[stage] : '—'}
          </span>
        </span>
      }
      hint="按 Esc 或点击背景关闭"
    >
      {body}
    </FocusMode>
  )
}

// ============================================================
// Agent 卡片子组件
// ============================================================

function AgentCard({
  agent, dim, isModerator, speaking, onHover,
}: {
  agent: AgentNode
  dim: boolean
  isModerator: boolean
  speaking: boolean
  onHover: (id: string | null) => void
}) {
  const w = isModerator ? AGENT_CARD_W + 8 : AGENT_CARD_W
  const h = AGENT_CARD_H
  const { candy, candySoft, borrowed } = agent
  const bgColor = borrowed ? '#FAFBFC' : '#FFFFFF'
  const borderColor = borrowed ? CANDY.borrowed : '#E8ECF1'
  const stripeColor = candy

  // bias 标签：等宽字体 fontSize 9.5px
  const biasText = agent.bias || ''
  const biasW = biasText.length * 6 + 14

  // 布局参数
  const iconR = 15
  const iconCx = -w / 2 + 26
  const textX = iconCx + iconR + 11

  return (
    <g
      data-node={agent.id}
      transform={`translate(${agent.x}, ${agent.y})`}
      opacity={dim ? 0.2 : 1}
      style={{ transition: 'opacity 0.2s ease' }}
      onMouseEnter={() => onHover(agent.id)}
      onMouseLeave={() => onHover(null)}
      filter="url(#ag-shadow)"
    >
      {/* 发言中脉冲环 */}
      {speaking && (
        <circle
          r={Math.max(w, h) / 2 + 8}
          fill="none"
          stroke={stripeColor}
          strokeWidth={1.2}
          opacity={0.3}
          style={{ animation: 'ag-pulse 1.8s ease-out infinite', transformOrigin: 'center' }}
        />
      )}

      {/* 卡片主体 */}
      <rect
        x={-w / 2} y={-h / 2}
        width={w} height={h}
        rx={10} ry={10}
        fill={bgColor}
        stroke={borderColor}
        strokeWidth={1}
        strokeDasharray={borrowed ? '3 2' : ''}
      />

      {/* 左侧糖果色条 */}
      <rect
        x={-w / 2} y={-h / 2}
        width={3.5} height={h}
        rx={1.7} ry={1.7}
        fill={stripeColor}
      />

      {/* 图标圆点 */}
      <circle cx={iconCx} cy={-4} r={iconR} fill={candySoft} />
      {/* 图标：16x16 坐标系，放大1.5倍以填满圆点 */}
      <g transform={`translate(${iconCx - 12}, ${-16}) scale(1.5)`}>
        <path
          d={agent.icon}
          fill="none"
          stroke={candy}
          strokeWidth={1.5}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </g>

      {/* 中文名 */}
      <text
        x={textX}
        y={-8}
        fontSize={13}
        fontWeight={600}
        fill={CANDY.textPrimary}
        style={{ letterSpacing: '-0.01em' }}
      >
        {agent.label}
      </text>

      {/* bias 标签胶囊 */}
      {biasText && (
        <g transform={`translate(${textX}, ${9})`}>
          <rect
            x={0} y={0}
            width={biasW}
            height={16}
            rx={8} ry={8}
            fill={candySoft}
          />
          <text
            x={8}
            y={11.5}
            fontSize={9}
            fill={candy}
            fontWeight={600}
            fontFamily="'JetBrains Mono', 'SF Mono', Menlo, Consolas, monospace"
          >
            {biasText}
          </text>
        </g>
      )}

      {/* 借调角标 */}
      {borrowed && (
        <g transform={`translate(${w / 2 - 22}, ${-h / 2 + 2})`}>
          <rect x={0} y={0} width={22} height={12} rx={3} ry={3} fill={CANDY.borrowed} opacity={0.8} />
          <text x={11} y={9} fontSize={8} fill="#fff" textAnchor="middle" fontWeight={600}>借调</text>
        </g>
      )}
    </g>
  )
}

// ============================================================
// 阶段迷你进度条
// ============================================================

function StageMiniBar({ current, skipped }: { current: Stage | null; skipped: Stage[] }) {
  const skippedSet = new Set(skipped)
  const currentIdx = current ? STAGE_ORDER.indexOf(current) : -1

  return (
    <div className="ag-stage-bar">
      {STAGE_ORDER.map((s, i) => {
        const isDone = currentIdx > i
        const isCurrent = i === currentIdx
        const isSkipped = skippedSet.has(s)
        return (
          <div key={s} className="ag-stage-pill" data-state={isCurrent ? 'current' : isDone ? 'done' : isSkipped ? 'skipped' : 'pending'}>
            <span className="ag-stage-dot" />
            <span className="ag-stage-label">{STAGE_LABELS[s]}</span>
          </div>
        )
      })}
    </div>
  )
}
