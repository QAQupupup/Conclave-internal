// 逻辑关系图：SVG 结构化三列流程图
// 列：Claim → Conflict → Decision
// 边：claim → conflict (虚线, 灰色) 表示"输入"；conflict → decision (实线, 绿色) 表示"解决"
// 优化点：
//  1) 节点高度按内容自动撑开（最多 6 行截断），不再硬编码 60
//  2) 文本用 <tspan> 多行换行 + 末尾省略号，避免溢出
//  3) 提供 fit-to-viewport：组件挂载/数据变化时自动计算最佳 scale，让用户一眼看全
//  4) 鼠标悬停显示完整内容（tooltip）作为兜底
//  5) adopted 判定严格按 claim.id，避免文本包含造成误判
//  6) 边的起点/终点精确到节点中线，贝塞尔弧线
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { MouseEvent as ReactMouseEvent } from 'react'
import { useMeeting } from '../store/MeetingContext.tsx'

/* ---------------- 尺寸常量 ---------------- */
const NODE_WIDTH = 240          // 节点宽
const PADDING = 32              // 容器内边距
const COL_GAP_X = 80            // 列间距
const ROW_GAP_Y = 18            // 行间距
const LINE_H = 16               // 文字行高（SVG 单位）
const CHARS_PER_LINE = 16       // 每行最大字符数（粗略：中文按 1 算）
// 节点内文字最多显示行数（按节点类型分别配置，避免长文本压扁节点）
const MAX_LINES_CLAIM = 3       // claim 节点正文最多 3 行
const MAX_LINES_CONFLICT = 4    // conflict 节点正文最多 4 行
const MAX_LINES_DECISION = 3    // decision 节点正文最多 3 行
const NODE_PAD_X = 14           // 节点内边距（左右）
const NODE_PAD_Y = 12           // 节点内边距（上下）
const HEADER_H = 20             // 节点顶部 tag 行高度
const MIN_NODE_H = 60
const MAX_CLAIMS_VISIBLE = 20   // 主张列最多显示的节点数（超出做溢出滚动）
const COL_TITLE_H = 36          // 列标题占位
const ARROW_GAP = 16            // 节点到边界的间距

/* ---------------- 颜色（与 index.css 角色色保持一致） ---------------- */
const COLOR_CLAIM_BORDER = '#9aa6b8'      // 冷灰蓝
const COLOR_CLAIM_FILL = '#ffffff'
const COLOR_CLAIM_ADOPTED_BG = '#f0fdf4'  // 浅绿
const COLOR_CLAIM_ADOPTED_BORDER = '#10b981'

const COLOR_CONFLICT_BORDER = '#f59e0b'   // 琥珀
const COLOR_CONFLICT_FILL = '#fffbeb'
const COLOR_CONFLICT_SIDE = '#b45309'     // 深琥珀

const COLOR_DECISION_BORDER = '#10b981'   // 翠绿
const COLOR_DECISION_FILL = '#f0fdf4'
const COLOR_DECISION_VERDICT = '#047857'  // 深绿

const COLOR_EDGE_RESOLVE = '#10b981'
const COLOR_EDGE_FEED = '#cbd5e1'         // 浅灰
const COLOR_TEXT = '#0f1419'
const COLOR_TEXT_MUTED = '#4a5568'
const COLOR_TEXT_FAINT = '#8b95a3'

/* ---------------- 文本处理 ---------------- */
/** 节点正文最大行数（按类型） */
function maxLinesFor(node: GraphNode): number {
  if (node.kind === 'claim') return MAX_LINES_CLAIM
  if (node.kind === 'conflict') return MAX_LINES_CONFLICT
  return MAX_LINES_DECISION
}

/** 将长文本按字符数切分为多行，最后一行加省略号 */
function wrapText(text: string, maxChars = CHARS_PER_LINE, maxLines = MAX_LINES_CONFLICT): string[] {
  if (!text) return ['']
  const lines: string[] = []
  let i = 0
  while (i < text.length && lines.length < maxLines) {
    let end = i + maxChars
    if (end >= text.length) {
      lines.push(text.slice(i))
      break
    }
    // 尝试在标点/空格处断行（仅在英文场景生效，中文按字符切）
    let breakAt = -1
    for (let k = end; k > i + maxChars - 4 && k > i; k--) {
      const ch = text[k]
      if (ch === ' ' || ch === '，' || ch === '；' || ch === '、' || ch === '。' || ch === '：') {
        breakAt = k + 1
        break
      }
    }
    if (breakAt > 0) {
      lines.push(text.slice(i, breakAt).trim())
      i = breakAt
    } else {
      lines.push(text.slice(i, end))
      i = end
    }
  }
  // 末行加省略号
  if (i < text.length && lines.length === maxLines) {
    const last = lines[lines.length - 1]
    lines[lines.length - 1] = last.replace(/[.。，、；： ]+$/, '') + '…'
  }
  return lines
}

/** 节点正文文本（用于计算行数） */
function nodeBodyText(node: GraphNode): string {
  if (node.kind === 'claim') return node.text
  if (node.kind === 'conflict') return node.summary
  return node.rationale
}

/** 节点文字高度（含 tag 行 + 正文行） */
function nodeTextHeight(node: GraphNode): number {
  const bodyLines = wrapText(nodeBodyText(node), CHARS_PER_LINE, maxLinesFor(node)).length
  return HEADER_H + bodyLines * LINE_H + NODE_PAD_Y
}

function nodeHeight(node: GraphNode): number {
  return Math.max(MIN_NODE_H, nodeTextHeight(node))
}

/* ---------------- 节点 / 边类型 ---------------- */
interface ClaimNode {
  kind: 'claim'
  id: string
  rawId: string
  text: string
  role?: string
  adopted: boolean
}
interface ConflictNode {
  kind: 'conflict'
  id: string
  summary: string
  sideA: string
  sideB: string
}
interface DecisionNode {
  kind: 'decision'
  id: string
  verdict: string
  rationale: string
  conflictId?: string
}
type GraphNode = ClaimNode | ConflictNode | DecisionNode

interface NodePos {
  node: GraphNode
  x: number
  y: number
  w: number
  h: number
}

/* ---------------- 主组件 ---------------- */
export function LogicGraph() {
  const { store } = useMeeting()
  const state = store.meeting
  const containerRef = useRef<HTMLDivElement | null>(null)
  const svgRef = useRef<SVGSVGElement | null>(null)

  const [scale, setScale] = useState(1)
  const [translate, setTranslate] = useState({ x: 0, y: 0 })
  const [dragging, setDragging] = useState(false)
  const dragStart = useRef({ x: 0, y: 0, tx: 0, ty: 0 })
  const [viewportSize, setViewportSize] = useState({ w: 0, h: 0 })
  const [tooltip, setTooltip] = useState<{ x: number; y: number; content: string } | null>(null)
  const [userZoomed, setUserZoomed] = useState(false)  // 标记用户是否主动调过缩放

  /* ---------- 解析数据 ---------- */
  const claims = (state?.claims || []) as any[]
  const conflicts = (state?.conflicts || []) as any[]
  const decisions = ((state?.decision_record as any)?.decisions || []) as any[]
  const adoptedIds = new Set<string>(
    ((state?.decision_record as any)?.adopted_claims || []) as string[],
  )

  /* ---------- 构建节点 ---------- */
  const claimNodes: ClaimNode[] = useMemo(
    () =>
      claims.map((c: any, i: number) => {
        const rawId: string = c.id || c.claim_id || `claim-${i}`
        const text: string = (
          c.claim || c.text || c.summary || ''
        ).toString()
        const role: string | undefined = c.proposed_by || c.role
        return {
          kind: 'claim',
          id: `c-${i}`,
          rawId,
          text,
          role,
          adopted: adoptedIds.has(rawId),
        }
      }),
    [claims, adoptedIds],
  )

  const conflictNodes: ConflictNode[] = useMemo(
    () =>
      conflicts.map((c: any, i: number) => ({
        kind: 'conflict' as const,
        id: `k-${i}`,
        summary: c.summary || c.description || `冲突 ${i + 1}`,
        sideA: c.side_a || '',
        sideB: c.side_b || '',
      })),
    [conflicts],
  )

  const decisionNodes: DecisionNode[] = useMemo(
    () =>
      decisions.map((d: any, i: number) => ({
        kind: 'decision' as const,
        id: `d-${i}`,
        verdict: d.verdict || '',
        rationale: d.rationale || '',
        conflictId: d.conflict_id,
      })),
    [decisions],
  )

  /* ---------- 布局：按冲突对齐决策；主张列左对齐 ---------- */
  const layout = useMemo(() => {
    const claimW = NODE_WIDTH
    const conflictW = NODE_WIDTH
    const decisionW = NODE_WIDTH
    const col0X = PADDING
    const col1X = col0X + claimW + COL_GAP_X
    const col2X = col1X + conflictW + COL_GAP_X
    const totalW = col2X + decisionW + PADDING

    const claimPos: NodePos[] = []
    const conflictPos: NodePos[] = []
    const decisionPos: NodePos[] = []

    // 冲突按 y 间距 1.0；为留出空间给子标签
    const rowGap = (n: GraphNode) => nodeHeight(n) + ROW_GAP_Y

    // 冲突 + 决策成对布局，y 对齐（一个 conflict 配一个 decision）
    let y = PADDING + COL_TITLE_H
    for (let i = 0; i < conflictNodes.length; i++) {
      const c = conflictNodes[i]
      const h = nodeHeight(c)
      conflictPos.push({ node: c, x: col1X, y, w: conflictW, h })
      const d = decisionNodes[i]
      if (d) {
        const dh = nodeHeight(d)
        // 决策节点垂直居中对齐冲突
        const dy = y + (h - dh) / 2
        decisionPos.push({ node: d, x: col2X, y: dy, w: decisionW, h: dh })
      }
      y += rowGap(c)
    }

    // 主张：按自然高度堆叠；当 claim 数量过多时折叠溢出项，给出 "N more" 提示
    const claimLimit = MAX_CLAIMS_VISIBLE
    const claimOverflow = Math.max(0, claimNodes.length - claimLimit)
    const visibleClaimNodes = claimOverflow > 0 ? claimNodes.slice(0, claimLimit) : claimNodes
    if (visibleClaimNodes.length > 0) {
      const conflictTotalH = y - PADDING - COL_TITLE_H  // 冲突列占的总高
      const startY = PADDING + COL_TITLE_H
      let cy = startY
      for (let i = 0; i < visibleClaimNodes.length; i++) {
        const c = visibleClaimNodes[i]
        const h = nodeHeight(c)
        claimPos.push({ node: c, x: col0X, y: cy, w: claimW, h })
        cy += h + ROW_GAP_Y
      }
      // 如果 claim 列总高 < 冲突列总高，让 claim 列最后一个节点居中延伸
      if (cy < startY + conflictTotalH && claimPos.length > 0) {
        const last = claimPos[claimPos.length - 1]
        last.h = Math.max(last.h, startY + conflictTotalH - last.y)
      }
    }

    const totalH = Math.max(
      y + PADDING,
      PADDING + COL_TITLE_H + claimPos.reduce((acc, n) => Math.max(acc, n.y + n.h), 0) + PADDING,
    )

    return { claimPos, conflictPos, decisionPos, totalW, totalH, claimOverflow }
  }, [claimNodes, conflictNodes, decisionNodes])

  /* ---------- 边：claim→conflict(虚线,均布) + conflict→decision(实线) ---------- */
  const edges = useMemo(() => {
    const list: Array<{
      from: NodePos
      to: NodePos
      kind: 'feed' | 'resolve'
      key: string
    }> = []
    // resolve: 1:1
    for (let i = 0; i < layout.conflictPos.length; i++) {
      const c = layout.conflictPos[i]
      const d = layout.decisionPos[i]
      if (d) list.push({ from: c, to: d, kind: 'resolve', key: `r-${i}` })
    }
    // feed: 每个 claim 按索引连到对应 conflict（如果存在），否则均布
    if (layout.claimPos.length > 0 && layout.conflictPos.length > 0) {
      layout.claimPos.forEach((cp, i) => {
        const target = layout.conflictPos[i % layout.conflictPos.length]
        list.push({ from: cp, to: target, kind: 'feed', key: `f-${i}` })
      })
    }
    return list
  }, [layout])

  /* ---------- 溢出 badge：claim 列底部的 "+N more" 节点 ---------- */
  const overflowBadge = useMemo<NodePos | null>(() => {
    if (layout.claimOverflow <= 0) return null
    const lastClaim = layout.claimPos[layout.claimPos.length - 1]
    if (!lastClaim) return null
    return {
      node: {
        kind: 'claim',
        id: '__overflow__',
        rawId: '__overflow__',
        text: `还有 ${layout.claimOverflow} 条主张未显示（hover 节点查看完整内容）`,
        role: '提示',
        adopted: false,
      },
      x: PADDING,
      y: lastClaim.y + lastClaim.h + 8,
      w: NODE_WIDTH,
      h: 40,
    }
  }, [layout.claimOverflow, layout.claimPos])

  /* ---------- 自适应 fit-to-viewport ---------- */
  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const ro = new ResizeObserver(() => {
      const rect = el.getBoundingClientRect()
      setViewportSize({ w: rect.width, h: rect.height })
    })
    ro.observe(el)
    const rect = el.getBoundingClientRect()
    setViewportSize({ w: rect.width, h: rect.height })
    return () => ro.disconnect()
  }, [])

  // 数据变化 / 视口变化 时，若用户未主动调过缩放，则重新 fit
  useEffect(() => {
    if (userZoomed) return
    if (viewportSize.w === 0 || viewportSize.h === 0) return
    if (layout.totalW === 0 || layout.totalH === 0) return
    const sx = (viewportSize.w - 24) / layout.totalW
    const sy = (viewportSize.h - 24) / layout.totalH
    // 优先 fit，最小 0.7（避免缩放过小导致文字模糊），最大 1.0
    const s = Math.max(0.7, Math.min(sx, sy, 1))
    setScale(s)
    setTranslate({
      x: Math.max(0, (viewportSize.w - layout.totalW * s) / 2),
      y: Math.max(0, (viewportSize.h - layout.totalH * s) / 2),
    })
  }, [viewportSize, layout.totalW, layout.totalH, userZoomed])

  /* ---------- 滚轮缩放：原生非被动监听，外层滚动不被打扰 ---------- */
  useEffect(() => {
    const el = svgRef.current
    if (!el) return
    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      setUserZoomed(true)
      const delta = e.deltaY > 0 ? -0.1 : 0.1
      setScale((s) => Math.min(2, Math.max(0.5, s + delta)))
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [])

  /* ---------- 拖拽平移 ---------- */
  const handleMouseDown = useCallback(
    (e: ReactMouseEvent) => {
      // 仅在点击空白处（不是节点）时拖拽
      const target = e.target as Element
      if (target.closest('[data-node]')) return
      e.preventDefault()
      setDragging(true)
      dragStart.current = { x: e.clientX, y: e.clientY, tx: translate.x, ty: translate.y }
    },
    [translate],
  )
  const handleMouseMove = useCallback(
    (e: ReactMouseEvent) => {
      if (!dragging) return
      setTranslate({
        x: dragStart.current.tx + (e.clientX - dragStart.current.x),
        y: dragStart.current.ty + (e.clientY - dragStart.current.y),
      })
    },
    [dragging],
  )
  const stopDrag = useCallback(() => setDragging(false), [])

  /* ---------- 控制 ---------- */
  const fit = useCallback(() => {
    setUserZoomed(false)
    // 触发 effect 重新算
    setViewportSize((s) => ({ ...s }))
  }, [])
  const zoomIn = () => {
    setUserZoomed(true)
    setScale((s) => Math.min(2, s + 0.15))
  }
  const zoomOut = () => {
    setUserZoomed(true)
    setScale((s) => Math.max(0.5, s - 0.15))
  }
  const reset = () => {
    setUserZoomed(false)
    setScale(1)
    setTranslate({ x: 0, y: 0 })
  }

  /* ---------- 渲染前过滤（必须在所有 hooks 之后） ---------- */
  if (claimNodes.length === 0 && conflictNodes.length === 0 && decisionNodes.length === 0) {
    return <div className="logic-graph-empty">暂无逻辑关系数据（需要至少 1 个 claim 或 conflict）</div>
  }

  const allNodes: NodePos[] = [...layout.claimPos, ...layout.conflictPos, ...layout.decisionPos]
  // overflowBadge 已在 hooks 阶段计算
  // 不把 overflowBadge 加到 allNodes，避免被三列视图逻辑重复渲染（独立渲染在 claim 列底部）

  return (
    <div className="logic-graph-container">
      <div className="logic-graph-toolbar">
        <span className="logic-graph-title">逻辑关系图</span>
        <span className="logic-graph-stats">
          {claimNodes.length} 主张 · {conflictNodes.length} 冲突 · {decisionNodes.length} 裁决
        </span>
        <div className="logic-graph-controls">
          <button className="btn btn-sm" onClick={zoomOut} title="缩小">−</button>
          <span className="logic-graph-zoom">{Math.round(scale * 100)}%</span>
          <button className="btn btn-sm" onClick={zoomIn} title="放大">+</button>
          <button className="btn btn-sm" onClick={fit} title="适应窗口">适应</button>
          <button className="btn btn-sm" onClick={reset} title="重置">重置</button>
        </div>
      </div>

      <div
        ref={containerRef}
        className="logic-graph-viewport"
        style={{ cursor: dragging ? 'grabbing' : 'grab' }}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={stopDrag}
        onMouseLeave={stopDrag}
      >
        <svg
          ref={svgRef}
          width="100%"
          height="100%"
          // 视口 = 实际像素；内部 g 用 transform 控制 pan/zoom
          style={{ display: 'block' }}
        >
          {/* 视口背景（淡网格） */}
          <defs>
            <pattern id="lg-grid" width="32" height="32" patternUnits="userSpaceOnUse">
              <path d="M 32 0 L 0 0 0 32" fill="none" stroke="#f4f6f8" strokeWidth="1" />
            </pattern>
            <marker
              id="lg-arrow-resolve"
              markerWidth="8"
              markerHeight="8"
              refX="7"
              refY="4"
              orient="auto"
            >
              <path d="M0,0 L8,4 L0,8 z" fill={COLOR_EDGE_RESOLVE} />
            </marker>
            <marker
              id="lg-arrow-feed"
              markerWidth="6"
              markerHeight="6"
              refX="6"
              refY="3"
              orient="auto"
            >
              <path d="M0,0 L6,3 L0,6 z" fill={COLOR_EDGE_FEED} />
            </marker>
          </defs>
          <rect
            x={translate.x}
            y={translate.y}
            width={layout.totalW * scale}
            height={layout.totalH * scale}
            fill="url(#lg-grid)"
            opacity={0.6}
          />

          <g
            transform={`translate(${translate.x} ${translate.y}) scale(${scale})`}
            onMouseMove={handleMouseMove}
          >
            {/* 列标题 */}
            <g>
              <text
                x={PADDING + NODE_WIDTH / 2}
                y={PADDING + 16}
                textAnchor="middle"
                fill={COLOR_TEXT_MUTED}
                fontSize="13"
                fontWeight="600"
                style={{ letterSpacing: '0.04em' }}
              >
                主张 · CLAIMS ({claimNodes.length})
              </text>
              <text
                x={PADDING + NODE_WIDTH + COL_GAP_X + NODE_WIDTH / 2}
                y={PADDING + 16}
                textAnchor="middle"
                fill={COLOR_CONFLICT_SIDE}
                fontSize="13"
                fontWeight="600"
                style={{ letterSpacing: '0.04em' }}
              >
                冲突 · CONFLICTS ({conflictNodes.length})
              </text>
              <text
                x={PADDING + (NODE_WIDTH + COL_GAP_X) * 2 + NODE_WIDTH / 2}
                y={PADDING + 16}
                textAnchor="middle"
                fill={COLOR_DECISION_VERDICT}
                fontSize="13"
                fontWeight="600"
                style={{ letterSpacing: '0.04em' }}
              >
                裁决 · DECISIONS ({decisionNodes.length})
              </text>
            </g>

            {/* 边（在节点之下） */}
            {edges.map((e) => {
              const fx = e.from.x + e.from.w + ARROW_GAP
              const fy = e.from.y + e.from.h / 2
              const tx = e.to.x - ARROW_GAP
              const ty = e.to.y + e.to.h / 2
              const midX = (fx + tx) / 2
              const d = `M ${fx},${fy} C ${midX},${fy} ${midX},${ty} ${tx},${ty}`
              const isResolve = e.kind === 'resolve'
              return (
                <path
                  key={e.key}
                  d={d}
                  fill="none"
                  stroke={isResolve ? COLOR_EDGE_RESOLVE : COLOR_EDGE_FEED}
                  strokeWidth={isResolve ? 1.6 : 1}
                  strokeDasharray={isResolve ? undefined : '4 3'}
                  markerEnd={isResolve ? 'url(#lg-arrow-resolve)' : 'url(#lg-arrow-feed)'}
                  opacity={isResolve ? 0.9 : 0.7}
                />
              )
            })}

            {/* 节点 */}
            {allNodes.map((np) => {
              const n = np.node
              if (n.kind === 'claim') return <ClaimNodeView key={n.id} pos={np} onHover={setTooltip} />
              if (n.kind === 'conflict') return <ConflictNodeView key={n.id} pos={np} onHover={setTooltip} />
              return <DecisionNodeView key={n.id} pos={np} onHover={setTooltip} />
            })}

            {/* 溢出 badge：claim 列底部的 "+N more" 提示 */}
            {overflowBadge && (
              <ClaimNodeView key="__overflow__" pos={overflowBadge} onHover={setTooltip} />
            )}
          </g>
        </svg>

        {/* 浮层 tooltip（鼠标悬停显示完整文本） */}
        {tooltip && (
          <div
            className="logic-graph-tooltip"
            style={{
              left: tooltip.x + 12,
              top: tooltip.y + 12,
            }}
          >
            {tooltip.content}
          </div>
        )}

        {/* 图例 */}
        <div className="logic-graph-legend">
          <div className="legend-item">
            <span className="legend-line" style={{ background: COLOR_EDGE_RESOLVE }} />
            解决
          </div>
          <div className="legend-item">
            <span className="legend-line dashed" style={{ borderColor: COLOR_EDGE_FEED }} />
            涉及
          </div>
          <div className="legend-item">
            <span className="legend-swatch" style={{ background: COLOR_CLAIM_ADOPTED_BG, borderColor: COLOR_CLAIM_ADOPTED_BORDER }} />
            已采纳
          </div>
        </div>

        {/* 提示：滚轮缩放、拖拽平移 */}
        <div className="logic-graph-hint">滚轮缩放 · 空白处拖拽</div>
      </div>
    </div>
  )
}

/* ---------------- 节点视图 ---------------- */

function NodeFrame({
  pos,
  fill,
  stroke,
  children,
  onHover,
  fullText,
  adopted,
}: {
  pos: NodePos
  fill: string
  stroke: string
  children: React.ReactNode
  onHover: (t: { x: number; y: number; content: string } | null) => void
  fullText: string
  adopted?: boolean
}) {
  return (
    <g
      data-node="1"
      transform={`translate(${pos.x} ${pos.y})`}
      onMouseEnter={(e) => {
        const r = (e.currentTarget.ownerSVGElement?.parentElement as HTMLElement)?.getBoundingClientRect()
        onHover({
          x: e.clientX - (r?.left ?? 0),
          y: e.clientY - (r?.top ?? 0),
          content: fullText,
        })
      }}
      onMouseMove={(e) => {
        const r = (e.currentTarget.ownerSVGElement?.parentElement as HTMLElement)?.getBoundingClientRect()
        onHover({
          x: e.clientX - (r?.left ?? 0),
          y: e.clientY - (r?.top ?? 0),
          content: fullText,
        })
      }}
      onMouseLeave={() => onHover(null)}
    >
      <rect
        width={pos.w}
        height={pos.h}
        rx={6}
        ry={6}
        fill={fill}
        stroke={stroke}
        strokeWidth={adopted ? 1.6 : 1.2}
      />
      {children}
    </g>
  )
}

function ClaimNodeView({
  pos,
  onHover,
}: {
  pos: NodePos
  onHover: (t: { x: number; y: number; content: string } | null) => void
}) {
  const n = pos.node as ClaimNode
  const lines = wrapText(n.text, CHARS_PER_LINE, MAX_LINES_CLAIM)
  const fill = n.adopted ? COLOR_CLAIM_ADOPTED_BG : COLOR_CLAIM_FILL
  const stroke = n.adopted ? COLOR_CLAIM_ADOPTED_BORDER : COLOR_CLAIM_BORDER
  return (
    <NodeFrame
      pos={pos}
      fill={fill}
      stroke={stroke}
      onHover={onHover}
      fullText={n.text}
      adopted={n.adopted}
    >
      {/* tag */}
      <text x={NODE_PAD_X} y={HEADER_H - 6} fill={COLOR_TEXT_FAINT} fontSize="10" fontWeight="600">
        {n.adopted ? '✓ ADOPTED' : 'CLAIM'}
        {n.role ? ` · ${n.role}` : ''}
      </text>
      {n.adopted && (
        <circle cx={pos.w - 10} cy={10} r={4} fill={COLOR_DECISION_BORDER} />
      )}
      {/* body */}
      <g transform={`translate(${NODE_PAD_X} ${HEADER_H + 2})`}>
        {lines.map((line, i) => (
          <text
            key={i}
            x={0}
            y={(i + 1) * LINE_H}
            fill={COLOR_TEXT}
            fontSize="12"
            style={{ fontFamily: 'var(--font-sans)' }}
          >
            {line}
          </text>
        ))}
      </g>
    </NodeFrame>
  )
}

function ConflictNodeView({
  pos,
  onHover,
}: {
  pos: NodePos
  onHover: (t: { x: number; y: number; content: string } | null) => void
}) {
  const n = pos.node as ConflictNode
  const fullText = `${n.summary}\n\nA 方: ${n.sideA}\nB 方: ${n.sideB}`
  const lines = wrapText(n.summary, CHARS_PER_LINE, MAX_LINES_CONFLICT)
  return (
    <NodeFrame
      pos={pos}
      fill={COLOR_CONFLICT_FILL}
      stroke={COLOR_CONFLICT_BORDER}
      onHover={onHover}
      fullText={fullText}
    >
      {/* 左侧强调条 */}
      <rect x={0} y={0} width={3} height={pos.h} fill={COLOR_CONFLICT_BORDER} />
      <text x={NODE_PAD_X} y={HEADER_H - 6} fill={COLOR_CONFLICT_SIDE} fontSize="10" fontWeight="700">
        ⚡ CONFLICT
      </text>
      <g transform={`translate(${NODE_PAD_X} ${HEADER_H + 2})`}>
        {lines.map((line, i) => (
          <text
            key={i}
            x={0}
            y={(i + 1) * LINE_H}
            fill={COLOR_TEXT}
            fontSize="12"
            fontWeight="600"
            style={{ fontFamily: 'var(--font-sans)' }}
          >
            {line}
          </text>
        ))}
      </g>
      {/* A/B 标签 */}
      <g transform={`translate(${NODE_PAD_X} ${pos.h - 10})`}>
        <text x={0} y={0} fill={COLOR_CONFLICT_SIDE} fontSize="10" fontWeight="600">
          A: {n.sideA ? n.sideA.slice(0, 14) + (n.sideA.length > 14 ? '…' : '') : '?'}
        </text>
        <text x={pos.w - NODE_PAD_X * 2 - 20} y={0} fill={COLOR_CONFLICT_SIDE} fontSize="10" fontWeight="600">
          B: {n.sideB ? n.sideB.slice(0, 14) + (n.sideB.length > 14 ? '…' : '') : '?'}
        </text>
      </g>
    </NodeFrame>
  )
}

function DecisionNodeView({
  pos,
  onHover,
}: {
  pos: NodePos
  onHover: (t: { x: number; y: number; content: string } | null) => void
}) {
  const n = pos.node as DecisionNode
  const fullText = `裁决: ${n.verdict}\n\n${n.rationale}`
  const lines = wrapText(n.rationale, CHARS_PER_LINE, MAX_LINES_DECISION)
  return (
    <NodeFrame
      pos={pos}
      fill={COLOR_DECISION_FILL}
      stroke={COLOR_DECISION_BORDER}
      onHover={onHover}
      fullText={fullText}
    >
      <text x={NODE_PAD_X} y={HEADER_H - 6} fill={COLOR_DECISION_VERDICT} fontSize="10" fontWeight="700">
        ✓ DECISION · {n.verdict || 'verdict'}
      </text>
      <g transform={`translate(${NODE_PAD_X} ${HEADER_H + 2})`}>
        {lines.map((line, i) => (
          <text
            key={i}
            x={0}
            y={(i + 1) * LINE_H}
            fill={COLOR_TEXT}
            fontSize="12"
            style={{ fontFamily: 'var(--font-sans)' }}
          >
            {line}
          </text>
        ))}
      </g>
    </NodeFrame>
  )
}
