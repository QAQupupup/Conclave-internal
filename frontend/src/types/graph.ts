// 力导向图数据类型：节点（agent / 冲突 / 证据）与连线
// 对齐 docs/iteration-2-design.md §5.2

/** 力导向图节点 */
export interface GraphNode {
  id: string // agent role 或 conflict id
  label: string
  type: 'agent' | 'conflict' | 'evidence'
  role?: string // agent 角色名
  stance?: string // agent 立场
  conflictType?: string // 冲突类型
  evidenceSource?: string // 证据来源
}

/** 力导向图连线 */
export interface GraphLink {
  source: string
  target: string
  type: 'argues' | 'conflicts' | 'supports' | 'cites'
  weight: number
}

/** 完整图数据 */
export interface ForceGraphData {
  nodes: GraphNode[]
  links: GraphLink[]
}
