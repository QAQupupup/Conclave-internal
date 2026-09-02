/**
 * mergeAgentUpdates 单元测试
 *
 * 覆盖场景：
 * 1. 瘦身 delta（仅 {id, state}）不抹掉 name/role（核心回归用例）
 * 2. 完整 delta 覆盖已有字段
 * 3. 空串 name 不覆盖已有非空名称（后端 name 可能为空）
 * 4. delta 中的新 agent 追加到末尾
 * 5. delta 未提及的 agent 保留（delta 可能只列状态变化者）
 * 6. 边界：空 incoming 返回原列表引用；空 current 返回 incoming
 * 7. 纯函数：不修改入参
 * 8. 输出顺序稳定：当前列表顺序 + 新增顺序，避免 UI 跳动
 */
import { describe, it, expect } from 'vitest';
import { mergeAgentUpdates } from '@/lib/agent-merge';
import type { AgentInfo } from '@/types';

const base = (over: Partial<AgentInfo> = {}): AgentInfo => ({
  id: 'a1',
  name: 'Arch',
  role: 'architect',
  state: 'idle',
  ...over,
});

describe('mergeAgentUpdates', () => {
  it('瘦身 delta（仅 id+state）保留 name/role（核心回归）', () => {
    const current = [base()];
    const delta = [{ id: 'a1', state: 'thinking' }] as unknown as AgentInfo[];

    const merged = mergeAgentUpdates(current, delta);

    expect(merged[0]).toEqual({
      id: 'a1',
      name: 'Arch',
      role: 'architect',
      state: 'thinking',
    });
  });

  it('完整 delta 覆盖已有字段', () => {
    const current = [base()];
    const delta = [base({ name: 'NewArch', state: 'speaking' })];

    const merged = mergeAgentUpdates(current, delta);

    expect(merged[0].name).toBe('NewArch');
    expect(merged[0].state).toBe('speaking');
  });

  it('空串 name 不覆盖已有非空名称', () => {
    const current = [base({ name: 'Arch' })];
    const delta = [base({ name: '', state: 'waiting' })];

    const merged = mergeAgentUpdates(current, delta);

    expect(merged[0].name).toBe('Arch');
    expect(merged[0].state).toBe('waiting');
  });

  it('delta 中的新 agent 追加到末尾', () => {
    const current = [base()];
    const delta = [base({ id: 'a2', name: 'Sec', role: 'security', state: 'idle' })];

    const merged = mergeAgentUpdates(current, delta);

    expect(merged).toHaveLength(2);
    expect(merged[1].id).toBe('a2');
    expect(merged[1].name).toBe('Sec');
  });

  it('delta 未提及的 agent 保留', () => {
    const current = [base(), base({ id: 'a2', name: 'Eng', role: 'engineer' })];
    const delta = [{ id: 'a1', state: 'done' }] as unknown as AgentInfo[];

    const merged = mergeAgentUpdates(current, delta);

    expect(merged).toHaveLength(2);
    expect(merged[0].state).toBe('done');
    expect(merged[1]).toEqual(current[1]);
  });

  it('边界：空 incoming 返回原列表', () => {
    const current = [base()];
    expect(mergeAgentUpdates(current, [])).toBe(current);
  });

  it('边界：空 current 返回 incoming', () => {
    const delta = [base()];
    expect(mergeAgentUpdates([], delta)).toBe(delta);
  });

  it('纯函数：不修改入参', () => {
    const current = [base()];
    const currentSnapshot = JSON.parse(JSON.stringify(current));
    const delta = [{ id: 'a1', state: 'thinking' }] as unknown as AgentInfo[];

    mergeAgentUpdates(current, delta);

    expect(current).toEqual(currentSnapshot);
  });

  it('输出顺序稳定：当前顺序优先，新增追加', () => {
    const current = [base({ id: 'a1' }), base({ id: 'a2' }), base({ id: 'a3' })];
    // delta 乱序 + 新增 a4
    const delta = [
      base({ id: 'a4', name: 'New' }),
      { id: 'a2', state: 'speaking' } as unknown as AgentInfo,
    ];

    const merged = mergeAgentUpdates(current, delta);

    expect(merged.map((a) => a.id)).toEqual(['a1', 'a2', 'a3', 'a4']);
  });

  it('异常项防御：delta 含无 id 项时不崩溃、不混入', () => {
    const current = [base()];
    const delta = [undefined as unknown as AgentInfo, { name: 'NoId' } as AgentInfo];

    const merged = mergeAgentUpdates(current, delta);

    expect(merged).toHaveLength(1);
    expect(merged[0].id).toBe('a1');
  });
});
