import { useCallback, useEffect, useRef, useState } from 'react'
import type { MouseEvent as ReactMouseEvent } from 'react'
import { useMeeting } from '../store/MeetingContext.tsx'

/** SVG 逻辑关系图：展示 claims → conflicts → decisions 因果链
 *  支持缩放（滚轮）、拖动（鼠标拖拽）、自适应布局
 *  与 AgentGraph 的力导向图不同：这里采用结构化的三列流程图布局
 */
export function LogicGraph() {
  const { store } = useMeeting()
  const state = store.meeting
  const svgRef = useRef<SVGSVGElement>(null)
  const [scale, setScale] = useState(1)
  const [translate, setTranslate] = useState({ x: 0, y: 0 })
  const [dragging, setDragging] = useState(false)
  const [dragStart, setDragStart] = useState({ x: 0, y: 0 })

  // 收集节点和边
  const claims = state?.claims || []
  const conflicts = state?.conflicts || []
  const decisions = state?.decision_record?.decisions || []
  const adopted = state?.decision_record?.adopted_claims || []

  // 滚轮缩放：使用原生非被动监听器，确保 preventDefault 生效，避免外层报告滚动
  useEffect(() => {
    const el = svgRef.current
    if (!el) return
    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      const delta = e.deltaY > 0 ? -0.1 : 0.1
      setScale((s) => Math.min(3, Math.max(0.3, s + delta)))
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [])

  // 拖拽平移
  const handleMouseDown = useCallback(
    (e: ReactMouseEvent) => {
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

  if (claims.length === 0 && conflicts.length === 0) {
    return <div className="logic-graph-empty">暂无逻辑关系数据</div>
  }

  // 布局：三列（claims → conflicts → decisions）
  const colWidth = 280
  const nodeHeight = 60
  const gapY = 16
  const padding = 40

  const claimNodes = claims.map((c: any, i: number) => ({
    id: `claim-${i}`,
    type: 'claim',
    text:
      typeof c === 'string' ? c : c.text || c.summary || JSON.stringify(c).slice(0, 60),
    x: padding,
    y: padding + i * (nodeHeight + gapY),
    adopted: adopted.some((a: any) =>
      typeof a === 'string' ? a.includes(c.text || '') : false,
    ),
  }))

  const conflictNodes = conflicts.map((c: any, i: number) => ({
    id: `conflict-${i}`,
    type: 'conflict',
    text: c.summary || c.description || `冲突 ${i + 1}`,
    sideA: c.side_a || '',
    sideB: c.side_b || '',
    x: padding + colWidth,
    y: padding + i * (nodeHeight + gapY) * 1.5,
  }))

  const decisionNodes = decisions.map((d: any, i: number) => ({
    id: `decision-${i}`,
    type: 'decision',
    text: d.rationale || '',
    verdict: d.verdict || '',
    x: padding + colWidth * 2,
    y: conflictNodes[i]?.y ?? padding + i * (nodeHeight + gapY),
  }))

  const allNodes: any[] = [...claimNodes, ...conflictNodes, ...decisionNodes]
  const svgWidth = padding * 2 + colWidth * 3
  const svgHeight =
    Math.max(
      claimNodes.length * (nodeHeight + gapY),
      conflictNodes.length * (nodeHeight + gapY) * 1.5,
      decisionNodes.length * (nodeHeight + gapY),
    ) +
    padding * 2

  // 边：conflict → decision（裁决解决冲突）
  const edges: Array<{ from: string; to: string; type: string }> = []
  conflicts.forEach((_: any, i: number) => {
    if (i < decisions.length) {
      edges.push({ from: `conflict-${i}`, to: `decision-${i}`, type: 'resolves' })
    }
  })

  const nodeColor = (type: string): string => {
    switch (type) {
      case 'claim':
        return '#4a9eff'
      case 'conflict':
        return '#ff6f6f'
      case 'decision':
        return '#6fdc6f'
      default:
        return '#888'
    }
  }

  return (
    <div className="logic-graph-container">
      <div className="logic-graph-controls">
        <button className="btn btn-sm" onClick={() => setScale((s) => Math.min(3, s + 0.2))}>
          +
        </button>
        <span className="logic-graph-zoom">{Math.round(scale * 100)}%</span>
        <button className="btn btn-sm" onClick={() => setScale((s) => Math.max(0.3, s - 0.2))}>
          −
        </button>
        <button
          className="btn btn-sm"
          onClick={() => {
            setScale(1)
            setTranslate({ x: 0, y: 0 })
          }}
        >
          重置
        </button>
      </div>
      <div className="logic-graph-viewport" style={{ cursor: dragging ? 'grabbing' : 'grab' }}>
        <svg
          ref={svgRef}
          width="100%"
          height="100%"
          viewBox={`0 0 ${svgWidth} ${svgHeight}`}
          preserveAspectRatio="xMidYMid meet"
          onMouseDown={handleMouseDown}
          onMouseMove={handleMouseMove}
          onMouseUp={handleMouseUp}
          onMouseLeave={handleMouseUp}
        >
          <g transform={`translate(${translate.x}, ${translate.y}) scale(${scale})`}>
            {/* 列标题 */}
            <text x={padding + 60} y={20} fill="#888" fontSize="12">
              主张 (Claims)
            </text>
            <text x={padding + colWidth + 50} y={20} fill="#888" fontSize="12">
              冲突 (Conflicts)
            </text>
            <text x={padding + colWidth * 2 + 50} y={20} fill="#888" fontSize="12">
              裁决 (Decisions)
            </text>

            {/* 箭头定义 */}
            <defs>
              <marker id="arrowhead" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto">
                <polygon points="0 0, 8 3, 0 6" fill="#666" />
              </marker>
            </defs>

            {/* 边 */}
            {edges.map((e, i) => {
              const from = allNodes.find((n) => n.id === e.from)
              const to = allNodes.find((n) => n.id === e.to)
              if (!from || !to) return null
              const x1 = from.x + 200
              const y1 = from.y + nodeHeight / 2
              const x2 = to.x
              const y2 = to.y + nodeHeight / 2
              const midX = (x1 + x2) / 2
              return (
                <path
                  key={`edge-${i}`}
                  d={`M ${x1},${y1} C ${midX},${y1} ${midX},${y2} ${x2},${y2}`}
                  fill="none"
                  stroke={e.type === 'resolves' ? '#6fdc6f' : '#666'}
                  strokeWidth="1.5"
                  strokeDasharray={e.type === 'resolves' ? 'none' : '4 2'}
                  markerEnd="url(#arrowhead)"
                />
              )
            })}

            {/* 节点 */}
            {allNodes.map((node) => (
              <g key={node.id} transform={`translate(${node.x}, ${node.y})`}>
                <rect
                  width="200"
                  height={nodeHeight}
                  rx="6"
                  fill="var(--bg-card, #1e1e32)"
                  stroke={nodeColor(node.type)}
                  strokeWidth="1.5"
                />
                {node.type === 'conflict' && (
                  <text x="10" y="14" fill={nodeColor(node.type)} fontSize="10" fontWeight="600">
                    ⚡ {node.sideA} vs {node.sideB}
                  </text>
                )}
                {node.type === 'decision' && (
                  <text x="10" y="14" fill={nodeColor(node.type)} fontSize="10" fontWeight="600">
                    ✓ {node.verdict}
                  </text>
                )}
                <text x="10" y={node.type === 'claim' ? 20 : 32} fill="#e0e0e0" fontSize="11">
                  {node.text.slice(0, 35)}
                  {node.text.length > 35 ? '...' : ''}
                </text>
                {node.type === 'claim' && node.adopted && (
                  <circle cx="190" cy="10" r="4" fill="#6fdc6f" />
                )}
              </g>
            ))}
          </g>
        </svg>
      </div>
    </div>
  )
}
