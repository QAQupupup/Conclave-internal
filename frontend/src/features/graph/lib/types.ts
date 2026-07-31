// 知识图谱数据类型

export type NodeType = 'topic' | 'claim' | 'evidence' | 'conflict' | 'source' | 'agent';

export type EdgeType = 'supports' | 'contradicts' | 'relates_to' | 'proposed_by' | 'derived_from' | 'has_conflict';

export interface GraphNode {
  id: string;
  type: NodeType;
  label: string;
  x: number;
  y: number;
  vx: number;
  vy: number;
  fixed?: boolean;
  meta?: Record<string, unknown>;
  color?: string;
  size?: number;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  type: EdgeType;
  weight?: number;
  meta?: Record<string, unknown>;
}

export interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

// 节点类型样式配置
export const NODE_STYLE: Record<NodeType, {
  shape: 'circle' | 'diamond' | 'hexagon' | 'square' | 'triangle';
  defaultSize: number;
  defaultColor: string;
  label: string;
}> = {
  topic: { shape: 'circle', defaultSize: 32, defaultColor: 'var(--color-brand-500)', label: '主题' },
  claim: { shape: 'diamond', defaultSize: 22, defaultColor: 'var(--color-role-moderator)', label: '论点' },
  evidence: { shape: 'circle', defaultSize: 14, defaultColor: 'var(--color-success)', label: '证据' },
  conflict: { shape: 'triangle', defaultSize: 18, defaultColor: 'var(--color-danger)', label: '冲突' },
  source: { shape: 'square', defaultSize: 12, defaultColor: 'var(--color-text-tertiary)', label: '来源' },
  agent: { shape: 'hexagon', defaultSize: 20, defaultColor: 'var(--color-role-engineer)', label: 'Agent' },
};

// 边类型样式配置
export const EDGE_STYLE: Record<EdgeType, {
  stroke: string;
  strokeWidth: number;
  dashed: boolean;
  label: string;
}> = {
  supports: { stroke: 'var(--color-success)', strokeWidth: 1.5, dashed: false, label: '支持' },
  contradicts: { stroke: 'var(--color-danger)', strokeWidth: 1.5, dashed: true, label: '矛盾' },
  relates_to: { stroke: 'var(--color-border-emphasis)', strokeWidth: 1, dashed: false, label: '相关' },
  proposed_by: { stroke: 'var(--color-role-architect)', strokeWidth: 1, dashed: false, label: '提出' },
  derived_from: { stroke: 'var(--color-info)', strokeWidth: 1, dashed: true, label: '来源' },
  has_conflict: { stroke: 'var(--color-danger)', strokeWidth: 1.5, dashed: true, label: '冲突' },
};

// 角色颜色映射
export const ROLE_COLORS: Record<string, string> = {
  moderator: 'var(--color-role-moderator)',
  product_architect: 'var(--color-role-architect)',
  engineer: 'var(--color-role-engineer)',
  security_expert: 'var(--color-role-security)',
  ux_designer: 'var(--color-role-ux)',
  data_engineer: 'var(--color-role-data)',
};
