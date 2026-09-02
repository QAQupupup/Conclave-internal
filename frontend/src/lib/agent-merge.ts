import type { AgentInfo } from '@/types';

/**
 * Agent 列表合并：把 WS STATE_DELTA 携带的 agents 负载合并进当前列表。
 *
 * 背景：STATE_DELTA 的 agents 可能是"瘦身负载"（仅携带 {id, state}）。
 * 若整体替换，name/role 等已有字段会被抹掉，头像退化为 "?"、卡片失去身份信息。
 *
 * 合并规则：
 * 1. 按 id 匹配：已有 agent 仅被 delta 中"已定义且非空"的字段覆盖（name 为空串不覆盖）；
 * 2. delta 中的新 agent（当前列表不存在）追加到末尾；
 * 3. 当前列表中存在但 delta 未提及的 agent 保留（delta 可能只列出状态变化者）。
 *
 * 纯函数，不修改入参；输出顺序 = 当前列表顺序 + 新增项顺序，避免 UI 跳动。
 */
export function mergeAgentUpdates(
  current: AgentInfo[],
  incoming: AgentInfo[],
): AgentInfo[] {
  if (!incoming || incoming.length === 0) return current;
  if (!current || current.length === 0) return incoming;

  const incomingById = new Map<string, AgentInfo>();
  for (const agent of incoming) {
    if (agent && agent.id) incomingById.set(agent.id, agent);
  }

  const merged: AgentInfo[] = current.map((existing) => {
    const delta = incomingById.get(existing.id);
    if (!delta) return existing;
    incomingById.delete(existing.id);
    return {
      ...existing,
      // 空串 name 不覆盖已有名称（后端 agents_summary 的 name 可能为空）
      ...(delta.name ? { name: delta.name } : {}),
      ...(delta.role !== undefined ? { role: delta.role } : {}),
      ...(delta.state !== undefined ? { state: delta.state } : {}),
      ...(delta.avatar !== undefined ? { avatar: delta.avatar } : {}),
    };
  });

  // 剩余的是当前列表没有的新 agent，按 delta 顺序追加
  for (const agent of incoming) {
    if (agent && agent.id && incomingById.has(agent.id)) {
      merged.push(agent);
    }
  }
  return merged;
}
