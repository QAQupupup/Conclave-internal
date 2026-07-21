import { render, screen } from '@testing-library/react'
import { vi, describe, it, expect, beforeEach } from 'vitest'
import { AgentGraph } from '../components/AgentGraph.tsx'

// ============================================================
// Mock FocusMode：渲染 children 以便内部 SVG/节点可被断言，
// 同时暴露 data-testid="focus-mode" 用于验证包裹组件存在
// ============================================================
vi.mock('../components/FocusMode.tsx', () => ({
  FocusMode: ({ children }: any) => <div data-testid="focus-mode">{children}</div>,
}))

// ============================================================
// Mock MeetingContext：返回可控 store
// mockStore 在 beforeEach 中重置，useMeeting 闭包惰性读取最新引用
// ============================================================
function makeDefaultStore(): any {
  return {
    meeting: {
      meeting_id: 'm1',
      topic: 'test topic',
      stage: 'intra_team',
      status: 'running',
      messages: [],
      team_config: [
        { role: 'moderator', stance: '中立' },
        { role: 'engineer', stance: 'pro-tech' },
        { role: 'product_architect', stance: 'pro-value' },
      ],
      conflicts: [],
      evidence_set: [],
      artifacts: [],
      borrowed_agents: [],
      flow_plan: null,
      artifact: null,
      decision_record: null,
    },
    replayDone: true,
    lastError: null,
  }
}

let mockStore: any = makeDefaultStore()

vi.mock('../store/MeetingContext.tsx', () => ({
  useMeeting: () => ({ store: mockStore }),
}))

describe('AgentGraph', () => {
  beforeEach(() => {
    mockStore = makeDefaultStore()
  })

  const renderGraph = () => render(<AgentGraph />)

  // 1. 渲染 SVG 容器
  it('renders an SVG container with the expected viewBox', () => {
    const { container } = renderGraph()
    // 使用类名精确匹配主拓扑 SVG（排除 AntD 图标里的 svg）
    const svg = container.querySelector('svg.agent-graph-svg')
    expect(svg).not.toBeNull()
    expect(svg?.getAttribute('viewBox')).toBe('0 0 780 540')
  })

  // 2. 渲染面板标题
  it('renders the panel title 会议拓扑', () => {
    renderGraph()
    expect(screen.getByText(/会议拓扑/)).toBeInTheDocument()
  })

  // 3. 渲染缩放控件（放大、缩小、重置）
  it('renders zoom controls (zoom in, zoom out, reset)', () => {
    renderGraph()
    const buttons = screen.getAllByRole('button')
    expect(buttons.length).toBeGreaterThanOrEqual(3)
    // AntD Button 会在两个 CJK 字符之间自动插入空格 -> "重 置"
    expect(screen.getByRole('button', { name: /重\s*置/ })).toBeInTheDocument()
    // 缩放百分比标签（初始 scale=1 -> 100%）
    expect(screen.getByText(/100\s*%/)).toBeInTheDocument()
  })

  // 4. 渲染所有 team_config 成员对应的 Agent 节点
  it('renders agent nodes for each team_config member', () => {
    const { container } = renderGraph()
    // team_config: moderator + engineer + product_architect => 3 个 agent
    const agentNames = container.querySelectorAll('.ag-agent-name')
    expect(agentNames.length).toBe(3)
    const texts = Array.from(agentNames).map((n) => n.textContent)
    expect(texts).toEqual(expect.arrayContaining(['主持人', '工程师', '产品架构师']))
  })

  // 5. team_config 为空时不崩溃
  it('renders without crashing when team_config is empty', () => {
    mockStore.meeting.team_config = []
    const { container } = renderGraph()
    expect(container.querySelector('svg')).not.toBeNull()
    // 主持人始终渲染
    const agentNames = container.querySelectorAll('.ag-agent-name')
    expect(agentNames.length).toBe(1)
    expect(agentNames[0].textContent).toBe('主持人')
  })

  // 6. 存在冲突时渲染冲突节点（菱形）
  it('renders conflict nodes when conflicts exist', () => {
    mockStore.meeting.stage = 'cross_team'
    mockStore.meeting.conflicts = [
      {
        id: 'c1',
        conflict_type: 'preference',
        summary: '工程师与产品架构师在技术选型上存在分歧',
        side_a: 'engineer',
        side_b: 'product_architect',
      },
    ]
    const { container } = renderGraph()
    expect(container.querySelector('.ag-conflicts-group')).not.toBeNull()
    const conflictNode = container.querySelector('[data-node="c1"]')
    expect(conflictNode).not.toBeNull()
    // 菱形 = polygon
    expect(conflictNode?.querySelector('polygon')).toBeTruthy()
  })

  // 7. 借调 agent 渲染（带借调样式）
  it('renders borrowed agents with borrowed styling', () => {
    mockStore.meeting.borrowed_agents = [{ role: 'data_engineer', spoken: false }]
    const { container } = renderGraph()
    expect(container.querySelector('[data-node="borrow:data_engineer"]')).not.toBeNull()
    // 借调角标 + bias 标签都包含 “借调” 文本
    expect(screen.getAllByText(/借调/).length).toBeGreaterThanOrEqual(1)
  })

  // 8. 显示当前阶段标签
  it('shows the current stage label in the stage mini bar', () => {
    renderGraph()
    // 默认 stage=intra_team -> 队内发言
    expect(screen.getByText('队内发言')).toBeInTheDocument()
  })

  // 9. evidence_set 有数据时渲染证据节点
  it('renders evidence nodes when evidence_set has data', () => {
    mockStore.meeting.stage = 'evidence_check'
    mockStore.meeting.conflicts = [
      {
        id: 'c1',
        conflict_type: 'factual',
        summary: '事实分歧',
        side_a: 'engineer',
        side_b: 'product_architect',
      },
    ]
    mockStore.meeting.evidence_set = [
      {
        conflict_id: 'c1',
        assessments: [{ source: 'web-search-1', supports: 'a' }],
      },
    ]
    const { container } = renderGraph()
    expect(container.querySelector('.ag-evidence-group')).not.toBeNull()
    const evidenceNode = container.querySelector('[data-node="evidence-c1-0"]')
    expect(evidenceNode).not.toBeNull()
    expect(evidenceNode?.querySelector('rect')).toBeTruthy()
  })

  // 10. 产出物阶段渲染产出物节点
  it('renders artifact node when in produce stage with artifact', () => {
    mockStore.meeting.stage = 'produce'
    mockStore.meeting.artifact = { deliverable_type: 'prd' }
    const { container } = renderGraph()
    expect(container.querySelector('.ag-artifact-group')).not.toBeNull()
    expect(screen.getByText('PRD 文档')).toBeInTheDocument()
  })

  // 11. FocusMode 包裹组件存在
  it('renders the FocusMode wrapper', () => {
    renderGraph()
    expect(screen.getByTestId('focus-mode')).toBeInTheDocument()
  })

  // 12. 5+ 成员时全部渲染
  it('renders all agents when team has 5+ members', () => {
    mockStore.meeting.team_config = [
      { role: 'moderator', stance: '中立' },
      { role: 'engineer', stance: 'pro-tech' },
      { role: 'product_architect', stance: 'pro-value' },
      { role: 'security_expert', stance: 'secure' },
      { role: 'ux_designer', stance: 'ux' },
      { role: 'data_engineer', stance: 'data' },
    ]
    const { container } = renderGraph()
    const agentNames = container.querySelectorAll('.ag-agent-name')
    expect(agentNames.length).toBe(6)
    const texts = Array.from(agentNames).map((n) => n.textContent)
    expect(texts).toEqual(
      expect.arrayContaining([
        '主持人',
        '工程师',
        '产品架构师',
        '安全专家',
        'UX 设计师',
        '数据工程师',
      ]),
    )
  })

  // 13. 渲染圆桌椭圆
  it('renders the circular table ellipse', () => {
    const { container } = renderGraph()
    expect(container.querySelector('ellipse')).toBeTruthy()
  })

  // 14. 渲染图例
  it('renders the legend with node-type items', () => {
    const { container } = renderGraph()
    const legend = container.querySelector('.graph-legend')
    expect(legend).not.toBeNull()
    expect(legend?.textContent).toContain('主持人')
    expect(legend?.textContent).toContain('冲突')
    expect(legend?.textContent).toContain('证据')
    expect(legend?.textContent).toContain('Agent')
  })

  // 15. 渲染交互提示文本
  it('renders the interaction hint text', () => {
    renderGraph()
    expect(screen.getByText(/滚轮缩放/)).toBeInTheDocument()
  })

  // 16. 头部统计反映冲突数量
  it('reflects conflict count in the header stats', () => {
    mockStore.meeting.stage = 'cross_team'
    mockStore.meeting.conflicts = [
      {
        id: 'c1',
        conflict_type: 'preference',
        summary: '分歧',
        side_a: 'engineer',
        side_b: 'product_architect',
      },
    ]
    renderGraph()
    expect(screen.getByText(/1 项冲突/)).toBeInTheDocument()
  })
})
