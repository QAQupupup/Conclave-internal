/**
 * 项目与议题池 hooks 元数据测试（ADR-017 Phase 2 前端接线）。
 *
 * 覆盖场景：
 * 1. 状态机镜像：allowedTransitions 与后端 issue_service.ALLOWED_TRANSITIONS 一致
 * 2. 终态（resolved/wontfix）无合法流转目标
 * 3. 未知状态兜底返回空数组（非正向）
 * 4. 会议绑定门控：isBindable 仅 open/scheduled 为 true（非正向覆盖其余状态）
 * 5. 状态标签完整覆盖五种状态（UI 不得出现裸英文状态）
 */
import { describe, it, expect } from 'vitest';
import {
  ALLOWED_TRANSITIONS,
  ISSUE_STATUSES,
  ISSUE_STATUS_LABELS,
  allowedTransitions,
  isBindable,
} from '@/hooks/use-projects';

describe('use-projects 状态机元数据', () => {
  it('allowedTransitions 与后端状态机对齐', () => {
    expect(allowedTransitions('open')).toEqual(['scheduled', 'in_progress', 'wontfix']);
    expect(allowedTransitions('scheduled')).toEqual(['in_progress', 'open', 'wontfix']);
    expect(allowedTransitions('in_progress')).toEqual(['resolved', 'open', 'wontfix']);
  });

  it('终态无任何合法流转目标', () => {
    expect(allowedTransitions('resolved')).toEqual([]);
    expect(allowedTransitions('wontfix')).toEqual([]);
  });

  it('未知状态兜底为空数组而非抛错（非正向）', () => {
    expect(allowedTransitions('not-a-status')).toEqual([]);
    expect(allowedTransitions('')).toEqual([]);
  });

  it('isBindable 仅 open/scheduled 可绑定会议', () => {
    expect(isBindable('open')).toBe(true);
    expect(isBindable('scheduled')).toBe(true);
  });

  it('非 open/scheduled 状态不可绑定（非正向）', () => {
    expect(isBindable('in_progress')).toBe(false);
    expect(isBindable('resolved')).toBe(false);
    expect(isBindable('wontfix')).toBe(false);
    expect(isBindable('unknown')).toBe(false);
  });

  it('五种状态均有中文标签且流转表键完整', () => {
    expect(ISSUE_STATUSES).toHaveLength(5);
    for (const status of ISSUE_STATUSES) {
      expect(ISSUE_STATUS_LABELS[status]).toBeTruthy();
      expect(ALLOWED_TRANSITIONS[status]).toBeDefined();
    }
  });
});
