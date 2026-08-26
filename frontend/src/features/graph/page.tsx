import * as React from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { extractArray } from '@/lib/extract';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { ScrollArea } from '@/components/ui/scroll-area';
import { cn } from '@/lib/utils';
import { toast } from '@/hooks/use-toast';
import {
  NODE_STYLE,
  EDGE_STYLE,
  type GraphNode,
  type GraphEdge,
  type NodeType,
  type GraphData,
} from './lib/types';
import { forceLayout, getEdgePath } from './lib/force-layout';
import { isDemoMode } from '@/lib/mock-data';

// --- Inline SVG Icons ---
function SvgIcon({ children, size = 14, className }: { children: React.ReactNode; size?: number; className?: string }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" className={className}>{children}</svg>;
}
function ZoomInIcon({ size, className }: { size?: number; className?: string }) {
  return <SvgIcon size={size} className={className}><circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" /><line x1="11" y1="8" x2="11" y2="14" /><line x1="8" y1="11" x2="14" y2="11" /></SvgIcon>;
}
function ZoomOutIcon({ size, className }: { size?: number; className?: string }) {
  return <SvgIcon size={size} className={className}><circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" /><line x1="8" y1="11" x2="14" y2="11" /></SvgIcon>;
}
function MaximizeIcon({ size, className }: { size?: number; className?: string }) {
  return <SvgIcon size={size} className={className}><path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3" /></SvgIcon>;
}
function SearchIcon({ size, className }: { size?: number; className?: string }) {
  return <SvgIcon size={size} className={className}><circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" /></SvgIcon>;
}
function RefreshIcon({ size, className }: { size?: number; className?: string }) {
  return <SvgIcon size={size} className={className}><polyline points="23 4 23 10 17 10" /><polyline points="1 20 1 14 7 14" /><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15" /></SvgIcon>;
}
function NetworkIcon({ size, className }: { size?: number; className?: string }) {
  return <SvgIcon size={size} className={className}><rect x="9" y="2" width="6" height="6" rx="1" /><rect x="16" y="16" width="6" height="6" rx="1" /><rect x="2" y="16" width="6" height="6" rx="1" /><line x1="12" y1="8" x2="19" y2="16" /><line x1="5" y1="16" x2="12" y2="8" /><line x1="12" y1="16" x2="12" y2="12" /></SvgIcon>;
}

// Simple SVG icons for graph
function TopicIcon({ size = 12, className }: { size?: number; className?: string }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" className={className}><circle cx="12" cy="12" r="8" /></svg>;
}
function ClaimIcon({ size = 12, className }: { size?: number; className?: string }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" className={className}><polygon points="12,2 22,12 12,22 2,12" /></svg>;
}
function EvidenceIcon({ size = 12, className }: { size?: number; className?: string }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" className={className}><circle cx="12" cy="12" r="5" /></svg>;
}
function SourceIcon({ size = 12, className }: { size?: number; className?: string }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" className={className}><rect x="4" y="4" width="16" height="16" rx="2" /></svg>;
}
function AgentIcon({ size = 12, className }: { size?: number; className?: string }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" className={className}><polygon points="12,2 21,7 21,17 12,22 3,17 3,7" /></svg>;
}

// 渲染节点形状
function NodeShape({ node, selected, hovered, onMouseDown, onMouseEnter, onMouseLeave, onClick }: {
  node: GraphNode;
  selected: boolean;
  hovered: boolean;
  onMouseDown: (e: React.MouseEvent) => void;
  onMouseEnter: () => void;
  onMouseLeave: () => void;
  onClick: () => void;
}) {
  const style = NODE_STYLE[node.type];
  const size = node.size || style.defaultSize;
  const color = node.color || style.defaultColor;
  const r = size / 2;
  const c = 12;

  const renderShape = (fill: string, opacity?: number, stroke?: string, strokeWidth?: number) => {
    const commonProps = { fill, opacity, stroke, strokeWidth };
    switch (style.shape) {
      case 'diamond': {
        const pts = `${c},${c - r} ${c + r},${c} ${c},${c + r} ${c - r},${c}`;
        return <polygon points={pts} {...commonProps} />;
      }
      case 'hexagon': {
        const pts = Array.from({ length: 6 }, (_, i) => {
          const a = (Math.PI / 3) * i - Math.PI / 2;
          return `${c + r * Math.cos(a)},${c + r * Math.sin(a)}`;
        }).join(' ');
        return <polygon points={pts} {...commonProps} />;
      }
      case 'square': {
        return <rect x={c - r} y={c - r} width={size} height={size} rx={2} {...commonProps} />;
      }
      case 'triangle': {
        return <polygon points={`${c},${c - r} ${c + r},${c + r} ${c - r},${c + r}`} {...commonProps} />;
      }
      case 'circle':
      default:
        return <circle cx={c} cy={c} r={r} {...commonProps} />;
    }
  };

  const glowTransform = `scale(1.3) translate(${-c * 0.3 / 1.3}, ${-c * 0.3 / 1.3})`;

  return (
    <g
      transform={`translate(${node.x - c}, ${node.y - c})`}
      onMouseDown={onMouseDown}
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
      onClick={onClick}
      style={{ cursor: 'pointer' }}
      className="transition-transform duration-100"
    >
      {/* Glow effect on hover/select */}
      {(hovered || selected) && (
        <g opacity={0.2}>
          <g transform={glowTransform}>
            {renderShape(color)}
          </g>
        </g>
      )}
      {/* Selection ring */}
      {selected && (
        <circle cx={c} cy={c} r={r + 3} fill="none" stroke={color} strokeWidth={2} strokeDasharray="4 2" />
      )}
      {/* Main shape */}
      {renderShape(color, hovered ? 1 : 0.9, 'var(--color-bg-primary)', 1.5)}
    </g>
  );
}

// 节点标签
function NodeLabel({ node, selected, hovered }: { node: GraphNode; selected: boolean; hovered: boolean }) {
  if (node.type === 'source' && !selected && !hovered) return null;
  const style = NODE_STYLE[node.type];
  const size = node.size || style.defaultSize;
  const showLabel = node.type !== 'source' || selected || hovered;
  if (!showLabel) return null;

  return (
    <g>
      <text
        x={node.x}
        y={node.y + size / 2 + 12}
        textAnchor="middle"
        fill={selected || hovered ? 'var(--color-text-primary)' : 'var(--color-text-secondary)'}
        fontSize={node.type === 'topic' ? 11 : 10}
        fontWeight={node.type === 'topic' ? 600 : 400}
        className="pointer-events-none select-none"
      >
        {node.label.length > 12 ? node.label.slice(0, 12) + '...' : node.label}
      </text>
    </g>
  );
}

// 边渲染
function EdgeLine({ edge, sourceNode, targetNode, highlighted }: {
  edge: GraphEdge;
  sourceNode: GraphNode;
  targetNode: GraphNode;
  highlighted: boolean;
}) {
  const style = EDGE_STYLE[edge.type];
  const path = getEdgePath(sourceNode, targetNode, edge.type === 'contradicts' || edge.type === 'derived_from' ? 0.15 : 0);

  return (
    <path
      d={path}
      fill="none"
      stroke={highlighted ? style.stroke : `color-mix(in srgb, ${style.stroke} 40%, transparent)`}
      strokeWidth={highlighted ? style.strokeWidth + 0.5 : style.strokeWidth}
      strokeDasharray={style.dashed ? '5 3' : undefined}
      className="pointer-events-none transition-all duration-150"
      opacity={highlighted ? 1 : 0.5}
    />
  );
}

const NODE_TYPE_ITEMS: { type: NodeType; label: string; Icon: typeof TopicIcon }[] = [
  { type: 'topic', label: '主题', Icon: TopicIcon },
  { type: 'claim', label: '论点', Icon: ClaimIcon },
  { type: 'evidence', label: '证据', Icon: EvidenceIcon },
  { type: 'source', label: '来源', Icon: SourceIcon },
  { type: 'agent', label: 'Agent', Icon: AgentIcon },
];

// 会议选择器使用的后端返回形状（snake_case meeting_id + 可选 title/topic）
interface MeetingOption {
  id?: string;
  meeting_id?: string;
  topic?: string;
  title?: string;
}

export default function GraphPage() {
  const [zoom, setZoom] = React.useState(1);
  const [pan, setPan] = React.useState({ x: 0, y: 0 });
  const [selectedNodeId, setSelectedNodeId] = React.useState<string | null>(null);
  const [hoveredNodeId, setHoveredNodeId] = React.useState<string | null>(null);
  const [searchQuery, setSearchQuery] = React.useState('');
  const [visibleTypes, setVisibleTypes] = React.useState<Set<NodeType>>(new Set(['topic', 'claim', 'evidence', 'source', 'agent']));
  const [draggingNode, setDraggingNode] = React.useState<string | null>(null);
  const [panning, setPanning] = React.useState(false);
  const [panStart, setPanStart] = React.useState({ x: 0, y: 0 });
  const [layoutData, setLayoutData] = React.useState<GraphData | null>(null);
  const svgRef = React.useRef<SVGSVGElement>(null);
  const dragOffset = React.useRef({ x: 0, y: 0 });

  // Fetch meetings list for selector
  const { data: meetingsData } = useQuery({
    queryKey: ['meetings', 'graph'],
    queryFn: () => api.get<{ items: MeetingOption[]; meetings?: MeetingOption[] }>('/meetings?limit=20'),
    retry: false,
  });

  const meetings = extractArray<MeetingOption>(meetingsData, ['items', 'meetings']);

  // Selected meeting
  const [selectedMeetingId, setSelectedMeetingId] = React.useState<string | null>(null);

  // Fetch graph data via API
  const { data: graphData, isLoading: graphLoading, error: graphError } = useQuery({
    queryKey: ['graph', selectedMeetingId || 'overview'],
    queryFn: async (): Promise<GraphData> => {
      const url = selectedMeetingId
        ? `/graph/overview?meeting_id=${selectedMeetingId}`
        : '/graph/overview';
      return await api.get<GraphData>(url);
    },
    retry: false,
  });

  // Run force layout when graph data changes
  React.useEffect(() => {
    if (!graphData) return;
    // Defensive: ensure nodes and edges are arrays before running layout
    if (!Array.isArray(graphData.nodes) || !Array.isArray(graphData.edges)) return;
    const svgWidth = 800;
    const svgHeight = 600;
    const laidOut = forceLayout(graphData.nodes, graphData.edges, {
      width: svgWidth,
      height: svgHeight,
      iterations: 150,
      repulsion: 6000,
      attraction: 0.01,
    });
    setLayoutData({ nodes: laidOut, edges: graphData.edges });
  }, [graphData]);

  // Filter nodes by visibility and search
  const filteredNodes = React.useMemo(() => {
    if (!layoutData) return [];
    return layoutData.nodes.filter((n) => {
      if (!visibleTypes.has(n.type)) return false;
      if (searchQuery && !n.label.toLowerCase().includes(searchQuery.toLowerCase())) return false;
      return true;
    });
  }, [layoutData, visibleTypes, searchQuery]);

  const filteredNodeIds = React.useMemo(() => new Set(filteredNodes.map((n) => n.id)), [filteredNodes]);

  const filteredEdges = React.useMemo(() => {
    if (!layoutData) return [];
    return layoutData.edges.filter(
      (e) => filteredNodeIds.has(e.source) && filteredNodeIds.has(e.target)
    );
  }, [layoutData, filteredNodeIds]);

  const nodeMap = React.useMemo(() => {
    const map = new Map<string, GraphNode>();
    for (const n of filteredNodes) map.set(n.id, n);
    return map;
  }, [filteredNodes]);

  // Connected node IDs for highlighting
  const connectedIds = React.useMemo(() => {
    if (!selectedNodeId && !hoveredNodeId) return new Set<string>();
    const activeId = hoveredNodeId || selectedNodeId;
    const ids = new Set<string>([activeId!]);
    for (const e of filteredEdges) {
      if (e.source === activeId) ids.add(e.target);
      if (e.target === activeId) ids.add(e.source);
    }
    return ids;
  }, [selectedNodeId, hoveredNodeId, filteredEdges]);

  const highlightedEdges = React.useMemo(() => {
    const activeId = hoveredNodeId || selectedNodeId;
    if (!activeId) return new Set<string>();
    return new Set(
      filteredEdges.filter((e) => e.source === activeId || e.target === activeId).map((e) => e.id)
    );
  }, [hoveredNodeId, selectedNodeId, filteredEdges]);

  // Zoom handling
  const handleWheel = (e: React.WheelEvent) => {
    e.preventDefault();
    const delta = e.deltaY > 0 ? 0.9 : 1.1;
    setZoom((z) => Math.max(0.3, Math.min(3, z * delta)));
  };

  // Pan handling
  const handleMouseDown = (e: React.MouseEvent) => {
    if (e.target === svgRef.current || (e.target as SVGElement).tagName === 'rect') {
      setPanning(true);
      setPanStart({ x: e.clientX - pan.x, y: e.clientY - pan.y });
      setSelectedNodeId(null);
    }
  };

  const handleMouseMove = (e: React.MouseEvent) => {
    if (panning) {
      setPan({ x: e.clientX - panStart.x, y: e.clientY - panStart.y });
    }
    if (draggingNode && layoutData) {
      const svg = svgRef.current;
      if (!svg) return;
      const rect = svg.getBoundingClientRect();
      const x = (e.clientX - rect.left - pan.x) / zoom;
      const y = (e.clientY - rect.top - pan.y) / zoom;
      setLayoutData((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          nodes: prev.nodes.map((n) =>
            n.id === draggingNode ? { ...n, x, y, fixed: true } : n
          ),
        };
      });
    }
  };

  const handleMouseUp = () => {
    setPanning(false);
    setDraggingNode(null);
  };

  const handleNodeMouseDown = (nodeId: string) => (e: React.MouseEvent) => {
    e.stopPropagation();
    setDraggingNode(nodeId);
    const svg = svgRef.current;
    if (!svg) return;
    const node = layoutData?.nodes.find((n) => n.id === nodeId);
    if (!node) return;
    const rect = svg.getBoundingClientRect();
    const x = (e.clientX - rect.left - pan.x) / zoom;
    const y = (e.clientY - rect.top - pan.y) / zoom;
    dragOffset.current = { x: x - node.x, y: y - node.y };
  };

  const resetView = () => {
    setZoom(1);
    setPan({ x: 0, y: 0 });
    toast({ title: '视图已重置' });
  };

  const refreshLayout = () => {
    if (!layoutData) return;
    // Unfix all nodes and re-run layout
    const resetNodes = layoutData.nodes.map((n) => ({ ...n, fixed: false, x: 0, y: 0, vx: 0, vy: 0 }));
    const laidOut = forceLayout(resetNodes, layoutData.edges, {
      width: 800,
      height: 600,
      iterations: 200,
    });
    setLayoutData({ nodes: laidOut, edges: layoutData.edges });
    setZoom(1);
    setPan({ x: 0, y: 0 });
    toast({ title: '布局已刷新' });
  };

  const toggleType = (type: NodeType) => {
    setVisibleTypes((prev) => {
      const next = new Set(prev);
      if (next.has(type)) next.delete(type);
      else next.add(type);
      return next;
    });
  };

  const selectedNode = selectedNodeId ? nodeMap.get(selectedNodeId) : null;

  // Loading state
  if (graphLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="text-sm text-text-tertiary">加载图谱中...</div>
      </div>
    );
  }

  // Real mode without backend graph API — show error state
  if (graphError && !isDemoMode()) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3">
        <NetworkIcon size={32} className="text-text-tertiary" />
        <div className="text-sm font-medium text-text-secondary">图谱加载失败</div>
        <div className="text-xs text-text-tertiary">{(graphError as Error)?.message || '请稍后重试'}</div>
      </div>
    );
  }

  // No data state — API returned but no nodes/edges
  const hasNoData = !graphLoading && layoutData && layoutData.nodes.length === 0;

  // No layout data (still loading)
  if (!layoutData && !hasNoData) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="text-sm text-text-tertiary">加载图谱中...</div>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      {/* Toolbar */}
      <div className="flex flex-shrink-0 items-center gap-2 border-b border-border-soft bg-bg-primary px-4 py-2">
        <div className="flex items-center gap-1.5">
          <NetworkIcon size={16} className="text-brand-500" />
          <h1 className="text-sm font-medium text-text-primary">知识图谱</h1>
        </div>

        <div className="mx-4 h-4 w-px bg-border-default" />

        {/* Meeting selector */}
        <select
          value={selectedMeetingId || ''}
          onChange={(e) => setSelectedMeetingId(e.target.value || null)}
          className="h-7 rounded-md border border-border-soft bg-bg-secondary px-2 text-xs text-text-primary outline-none focus:border-brand-500"
        >
          <option value="">全部会议</option>
          {meetings.map((m: MeetingOption) => (
            <option key={m.meeting_id || m.id} value={m.meeting_id || m.id}>{(m.topic || m.title || m.id)?.slice(0, 40)}</option>
          ))}
        </select>

        {/* Search */}
        <div className="relative ml-2">
          <SearchIcon size={12} className="absolute left-2 top-1/2 -translate-y-1/2 text-text-tertiary" />
          <Input
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="搜索节点..."
            className="h-7 w-44 pl-7 text-xs"
          />
        </div>

        <div className="flex-1" />

        {/* Type filters */}
        <div className="flex items-center gap-1">
          {NODE_TYPE_ITEMS.map(({ type, label, Icon }) => (
            <button
              key={type}
              onClick={() => toggleType(type)}
              className={cn(
                'flex items-center gap-1 rounded-md px-2 py-1 text-[10px] transition-colors',
                visibleTypes.has(type)
                  ? 'bg-bg-tertiary text-text-primary'
                  : 'text-text-tertiary hover:text-text-secondary',
              )}
              title={label}
            >
              <Icon size={10} />
              {label}
            </button>
          ))}
        </div>

        <div className="mx-2 h-4 w-px bg-border-default" />

        {/* Zoom controls */}
        <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => setZoom((z) => Math.min(3, z * 1.2))}>
          <ZoomInIcon size={14} />
        </Button>
        <span className="w-10 text-center text-[10px] text-text-tertiary">{Math.round(zoom * 100)}%</span>
        <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => setZoom((z) => Math.max(0.3, z * 0.8))}>
          <ZoomOutIcon size={14} />
        </Button>
        <Button variant="ghost" size="icon" className="h-7 w-7" onClick={resetView} title="重置视图">
          <MaximizeIcon size={14} />
        </Button>
        <Button variant="ghost" size="icon" className="h-7 w-7" onClick={refreshLayout} title="重新布局">
          <RefreshIcon size={14} />
        </Button>
      </div>

      {/* Main area */}
      <div className="flex flex-1 overflow-hidden">
        {/* Graph canvas */}
        <div className="relative flex-1 overflow-hidden bg-bg-secondary"
          style={{
            backgroundImage: 'radial-gradient(circle, var(--color-border-default) 1px, transparent 1px)',
            backgroundSize: '20px 20px',
          }}
        >
          {/* Empty state */}
          {hasNoData && (
            <div className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-2 bg-bg-secondary/80 backdrop-blur-sm">
              <NetworkIcon size={28} className="text-text-tertiary" />
              <div className="text-sm font-medium text-text-secondary">暂无图谱数据</div>
              <div className="text-xs text-text-tertiary">启动一个讨论并产生对话后，这里会自动生成知识图谱</div>
            </div>
          )}
          <svg
            ref={svgRef}
            className="h-full w-full"
            onWheel={handleWheel}
            onMouseDown={handleMouseDown}
            onMouseMove={handleMouseMove}
            onMouseUp={handleMouseUp}
            onMouseLeave={handleMouseUp}
          >
            <g transform={`translate(${pan.x}, ${pan.y}) scale(${zoom})`}>
              {/* Edges */}
              {filteredEdges.map((edge) => {
                const source = nodeMap.get(edge.source);
                const target = nodeMap.get(edge.target);
                if (!source || !target) return null;
                return (
                  <EdgeLine
                    key={edge.id}
                    edge={edge}
                    sourceNode={source}
                    targetNode={target}
                    highlighted={highlightedEdges.has(edge.id)}
                  />
                );
              })}

              {/* Nodes */}
              {filteredNodes.map((node) => (
                <NodeShape
                  key={node.id}
                  node={node}
                  selected={selectedNodeId === node.id}
                  hovered={hoveredNodeId === node.id || (connectedIds.size > 1 && connectedIds.has(node.id))}
                  onMouseDown={handleNodeMouseDown(node.id)}
                  onMouseEnter={() => setHoveredNodeId(node.id)}
                  onMouseLeave={() => setHoveredNodeId(null)}
                  onClick={() => setSelectedNodeId(node.id === selectedNodeId ? null : node.id)}
                />
              ))}

              {/* Labels */}
              {filteredNodes.map((node) => (
                <NodeLabel
                  key={`label-${node.id}`}
                  node={node}
                  selected={selectedNodeId === node.id}
                  hovered={hoveredNodeId === node.id}
                />
              ))}
            </g>
          </svg>

          {/* Legend */}
          <div className="absolute bottom-3 left-3 rounded-lg border border-border-soft bg-bg-primary/90 p-2.5 backdrop-blur-sm">
            <div className="mb-1.5 text-[10px] font-medium text-text-tertiary">关系类型</div>
            <div className="space-y-1">
              {Object.entries(EDGE_STYLE).map(([type, style]) => (
                <div key={type} className="flex items-center gap-1.5">
                  <svg width="20" height="6">
                    <line
                      x1="0" y1="3" x2="20" y2="3"
                      stroke={style.stroke}
                      strokeWidth={1.5}
                      strokeDasharray={style.dashed ? '3 2' : undefined}
                    />
                  </svg>
                  <span className="text-[10px] text-text-tertiary">{style.label}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Stats */}
          <div className="absolute bottom-3 right-3 rounded-lg border border-border-soft bg-bg-primary/90 px-2.5 py-1.5 text-[10px] text-text-tertiary backdrop-blur-sm">
            {filteredNodes.length} 节点 · {filteredEdges.length} 关系
          </div>
        </div>

        {/* Detail panel */}
        {selectedNode && (
          <div className="w-64 flex-shrink-0 border-l border-border-soft bg-bg-primary">
            <ScrollArea className="h-full">
              <div className="p-4">
                <div className="mb-3 flex items-center gap-2">
                  <span
                    className="flex h-6 w-6 items-center justify-center rounded"
                    style={{ color: selectedNode.color || NODE_STYLE[selectedNode.type].defaultColor }}
                  >
                    {selectedNode.type === 'topic' && <TopicIcon size={14} />}
                    {selectedNode.type === 'claim' && <ClaimIcon size={14} />}
                    {selectedNode.type === 'evidence' && <EvidenceIcon size={14} />}
                    {selectedNode.type === 'source' && <SourceIcon size={14} />}
                    {selectedNode.type === 'agent' && <AgentIcon size={14} />}
                  </span>
                  <Badge variant="outline" className="text-[10px]">
                    {NODE_STYLE[selectedNode.type].label}
                  </Badge>
                </div>
                <h3 className="mb-2 text-sm font-medium text-text-primary">{selectedNode.label}</h3>

                {/* Connected nodes */}
                <div className="space-y-2">
                  <div className="text-[10px] font-medium uppercase tracking-wider text-text-tertiary">关联节点</div>
                  {filteredEdges
                    .filter((e) => e.source === selectedNode.id || e.target === selectedNode.id)
                    .map((edge) => {
                      const otherId = edge.source === selectedNode.id ? edge.target : edge.source;
                      const other = nodeMap.get(otherId);
                      if (!other) return null;
                      return (
                        <button
                          key={edge.id}
                          onClick={() => setSelectedNodeId(otherId)}
                          className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs transition-colors hover:bg-bg-secondary"
                        >
                          <span className="h-1.5 w-1.5 flex-shrink-0 rounded-full" style={{ background: EDGE_STYLE[edge.type].stroke }} />
                          <span className="flex-1 truncate text-text-secondary hover:text-text-primary">{other.label}</span>
                          <span className="text-[10px] text-text-tertiary">{EDGE_STYLE[edge.type].label}</span>
                        </button>
                      );
                    })}
                </div>

                {selectedNode.meta && Object.keys(selectedNode.meta).length > 0 && (
                  <div className="mt-4 space-y-2">
                    <div className="text-[10px] font-medium uppercase tracking-wider text-text-tertiary">属性</div>
                    {Object.entries(selectedNode.meta).map(([k, v]) => (
                      <div key={k} className="flex justify-between text-[11px]">
                        <span className="text-text-tertiary">{k}</span>
                        <span className="text-text-secondary">{String(v)}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </ScrollArea>
          </div>
        )}
      </div>
    </div>
  );
}
