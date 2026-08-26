// Mock 知识图谱数据生成器
// 在后端提供 graph API 之前，提供合理的演示数据

import type { GraphData, GraphNode } from './types';

// 生成演示图谱数据
export function generateMockGraph(meetingTitle?: string): GraphData {
  const nodes: GraphNode[] = [];
  const edges: GraphData['edges'] = [];

  // 中心主题节点
  const topicId = 'topic-main';
  nodes.push({
    id: topicId,
    type: 'topic',
    label: meetingTitle || '多Agent系统架构设计',
    x: 0,
    y: 0,
    vx: 0,
    vy: 0,
    size: 36,
    meta: { description: '核心讨论议题' },
  });

  // 子主题
  const subTopics = [
    { id: 'topic-1', label: 'Agent编排模式', x: -150, y: -100 },
    { id: 'topic-2', label: '通信协议设计', x: 150, y: -80 },
    { id: 'topic-3', label: '状态管理', x: -100, y: 120 },
    { id: 'topic-4', label: '错误恢复', x: 120, y: 100 },
  ];

  for (const t of subTopics) {
    nodes.push({ id: t.id, type: 'topic', label: t.label, x: t.x, y: t.y, vx: 0, vy: 0, size: 24 });
    edges.push({ id: `e-${topicId}-${t.id}`, source: topicId, target: t.id, type: 'relates_to' });
  }

  // Agent 节点
  const agents = [
    { id: 'agent-mod', label: '主持人', role: 'moderator', x: -200, y: 0 },
    { id: 'agent-arch', label: '架构师', role: 'product_architect', x: 0, y: -180 },
    { id: 'agent-eng', label: '工程师', role: 'engineer', x: 200, y: -30 },
    { id: 'agent-sec', label: '安全专家', role: 'security_expert', x: 180, y: 180 },
    { id: 'agent-ux', label: 'UX设计师', role: 'ux_designer', x: -180, y: 200 },
  ];

  for (const a of agents) {
    nodes.push({
      id: a.id,
      type: 'agent',
      label: a.label,
      x: a.x,
      y: a.y,
      vx: 0,
      vy: 0,
      size: 22,
      meta: { role: a.role },
    });
  }

  // 论点（Claims）
  const claims = [
    { id: 'claim-1', label: '应使用响应式编排而非固定流程', agent: 'agent-arch', topic: 'topic-1', x: -200, y: -150 },
    { id: 'claim-2', label: 'AG-UI协议支持双向流式通信', agent: 'agent-eng', topic: 'topic-2', x: 200, y: -130 },
    { id: 'claim-3', label: '事件溯源模式便于调试和回放', agent: 'agent-eng', topic: 'topic-3', x: -150, y: 60 },
    { id: 'claim-4', label: '需要断路器防止级联失败', agent: 'agent-sec', topic: 'topic-4', x: 100, y: 150 },
    { id: 'claim-5', label: 'WebSocket+SSE双通道更可靠', agent: 'agent-eng', topic: 'topic-2', x: 230, y: -30 },
    { id: 'claim-6', label: '会话快照支持断点续传', agent: 'agent-arch', topic: 'topic-3', x: -50, y: 160 },
    { id: 'claim-7', label: '固定流程更可控，适合审计', agent: 'agent-sec', topic: 'topic-1', x: -100, y: -60 },
  ];

  for (const c of claims) {
    nodes.push({ id: c.id, type: 'claim', label: c.label, x: c.x, y: c.y, vx: 0, vy: 0, size: 18, meta: { agentId: c.agent } });
    edges.push({ id: `e-${c.id}-${c.topic}`, source: c.id, target: c.topic, type: 'relates_to' });
    edges.push({ id: `e-${c.agent}-${c.id}`, source: c.agent, target: c.id, type: 'proposed_by' });
  }

  // 冲突
  edges.push({ id: 'conflict-1', source: 'claim-1', target: 'claim-7', type: 'contradicts', meta: { description: '响应式 vs 固定流程的争论' } });

  // 证据节点
  const evidences = [
    { id: 'ev-1', label: 'React Flow性能数据', claim: 'claim-2', source: 'src-1', x: 270, y: -170 },
    { id: 'ev-2', label: 'Event Sourcing案例', claim: 'claim-3', source: 'src-2', x: -230, y: 40 },
    { id: 'ev-3', label: '断路器模式白皮书', claim: 'claim-4', source: 'src-3', x: 50, y: 200 },
    { id: 'ev-4', label: 'SSE重连机制测试', claim: 'claim-5', source: 'src-4', x: 280, y: 30 },
  ];

  for (const ev of evidences) {
    nodes.push({ id: ev.id, type: 'evidence', label: ev.label, x: ev.x, y: ev.y, vx: 0, vy: 0, size: 12 });
    edges.push({ id: `e-${ev.claim}-${ev.id}`, source: ev.id, target: ev.claim, type: 'supports' });
    edges.push({ id: `e-${ev.id}-${ev.source}`, source: ev.id, target: ev.source, type: 'derived_from' });
  }

  // 来源节点
  const sources = [
    { id: 'src-1', label: 'React Flow Docs', x: 300, y: -200 },
    { id: 'src-2', label: 'Martin Fowler Blog', x: -270, y: 10 },
    { id: 'src-3', label: 'Netflix Hystrix', x: 0, y: 240 },
    { id: 'src-4', label: 'MDN SSE Spec', x: 310, y: 70 },
  ];

  for (const s of sources) {
    nodes.push({ id: s.id, type: 'source', label: s.label, x: s.x, y: s.y, vx: 0, vy: 0, size: 10 });
  }

  return { nodes, edges };
}

// 从会议数据生成图谱（简化版，实际需要后端 API）
export function buildGraphFromMeeting(meeting: {
  id: string;
  title: string;
  messages?: Array<{ agentId?: string; agentName?: string; content: string; role?: string }>;
  agents?: Array<{ id: string; name: string; role: string }>;
}): GraphData {
  // 目前返回 mock 数据，等后端有 graph API 时替换
  return generateMockGraph(meeting.title);
}
