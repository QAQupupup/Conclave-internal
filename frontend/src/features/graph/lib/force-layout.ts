// 简单的力导向布局算法（纯 JS 实现）
// 基于 spring-force 模型：节点间排斥 + 边弹簧吸引 + 中心引力

import type { GraphNode, GraphEdge } from './types';

interface LayoutConfig {
  width: number;
  height: number;
  repulsion?: number;    // 节点间排斥力系数
  attraction?: number;  // 边弹簧吸引力系数
  damping?: number;     // 阻尼系数
  centerGravity?: number; // 中心引力系数
  iterations?: number;  // 迭代次数
}

export function forceLayout(
  nodes: GraphNode[],
  edges: GraphEdge[],
  config: LayoutConfig
): GraphNode[] {
  const {
    width,
    height,
    repulsion = 8000,
    attraction = 0.008,
    damping = 0.85,
    centerGravity = 0.01,
    iterations = 100,
  } = config;

  const cx = width / 2;
  const cy = height / 2;

  // 深拷贝节点
  const layoutNodes = nodes.map((n) => ({ ...n, vx: 0, vy: 0 }));

  // 如果节点没有初始位置，随机分布
  for (const node of layoutNodes) {
    if (node.x === 0 && node.y === 0) {
      node.x = cx + (Math.random() - 0.5) * width * 0.6;
      node.y = cy + (Math.random() - 0.5) * height * 0.6;
    }
  }

  // 构建邻接表
  const adjacency = new Map<string, string[]>();
  for (const edge of edges) {
    if (!adjacency.has(edge.source)) adjacency.set(edge.source, []);
    if (!adjacency.has(edge.target)) adjacency.set(edge.target, []);
    adjacency.get(edge.source)!.push(edge.target);
    adjacency.get(edge.target)!.push(edge.source);
  }

  for (let iter = 0; iter < iterations; iter++) {
    // 1. 节点间排斥力（Coulomb's law）
    for (let i = 0; i < layoutNodes.length; i++) {
      for (let j = i + 1; j < layoutNodes.length; j++) {
        const a = layoutNodes[i];
        const b = layoutNodes[j];
        if (a.fixed && b.fixed) continue;

        const dx = b.x - a.x;
        const dy = b.y - a.y;
        let dist = Math.sqrt(dx * dx + dy * dy);
        if (dist < 1) dist = 1;

        const force = repulsion / (dist * dist);
        const fx = (dx / dist) * force;
        const fy = (dy / dist) * force;

        if (!a.fixed) {
          a.vx -= fx;
          a.vy -= fy;
        }
        if (!b.fixed) {
          b.vx += fx;
          b.vy += fy;
        }
      }
    }

    // 2. 边弹簧吸引力（Hooke's law）
    for (const edge of edges) {
      const a = layoutNodes.find((n) => n.id === edge.source);
      const b = layoutNodes.find((n) => n.id === edge.target);
      if (!a || !b) continue;
      if (a.fixed && b.fixed) continue;

      const dx = b.x - a.x;
      const dy = b.y - a.y;
      const dist = Math.sqrt(dx * dx + dy * dy);
      if (dist < 1) continue;

      const idealLength = 100 + (edge.weight || 1) * 20;
      const displacement = dist - idealLength;
      const force = displacement * attraction;
      const fx = (dx / dist) * force;
      const fy = (dy / dist) * force;

      if (!a.fixed) {
        a.vx += fx;
        a.vy += fy;
      }
      if (!b.fixed) {
        b.vx -= fx;
        b.vy -= fy;
      }
    }

    // 3. 中心引力
    for (const node of layoutNodes) {
      if (node.fixed) continue;
      node.vx += (cx - node.x) * centerGravity;
      node.vy += (cy - node.y) * centerGravity;
    }

    // 4. 应用阻尼和位置更新
    for (const node of layoutNodes) {
      if (node.fixed) {
        node.vx = 0;
        node.vy = 0;
        continue;
      }
      node.vx *= damping;
      node.vy *= damping;
      node.x += node.vx;
      node.y += node.vy;

      // 边界约束
      const padding = 40;
      node.x = Math.max(padding, Math.min(width - padding, node.x));
      node.y = Math.max(padding, Math.min(height - padding, node.y));
    }
  }

  return layoutNodes;
}

// 计算 SVG 路径（贝塞尔曲线）
export function getEdgePath(
  source: { x: number; y: number },
  target: { x: number; y: number },
  curvature = 0
): string {
  if (curvature === 0) {
    return `M${source.x},${source.y} L${target.x},${target.y}`;
  }
  const mx = (source.x + target.x) / 2;
  const my = (source.y + target.y) / 2;
  const dx = target.x - source.x;
  const dy = target.y - source.y;
  // 垂直偏移
  const nx = -dy * curvature;
  const ny = dx * curvature;
  return `M${source.x},${source.y} Q${mx + nx},${my + ny} ${target.x},${target.y}`;
}
