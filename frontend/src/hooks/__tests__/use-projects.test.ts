/**
 * 项目与议题池 hooks 元数据测试（ADR-017 Phase 2 前端接线）。
 *
 * 覆盖场景：
 * 1. 状态机镜像：allowedTransitions 与后端 issue_service.ALLOWED_TRANSITIONS 一致
 *    （有意省略 in_progress → conflict：系统置入，非用户动作）
 * 2. 终态（resolved/wontfix）无合法流转目标
 * 3. 未知状态兜底返回空数组（非正向）
 * 4. 会议绑定门控：isBindable 仅 open/scheduled/conflict 为 true（conflict 重绑会，D11）
 * 5. 合入门控：isMergeable 仅 in_progress/conflict 为 true（镜像后端 MERGEABLE_STATUSES）
 * 6. 状态标签完整覆盖六种状态（UI 不得出现裸英文状态）
 */
import { describe, it, expect } from 'vitest';
import {
  ALLOWED_TRANSITIONS,
  ISSUE_STATUSES,
  ISSUE_STATUS_LABELS,
  allowedTransitions,
  isBindable,
  isMergeable,
} from '@/hooks/use-projects';

describe('use-projects 状态机元数据', () => {
  it('allowedTransitions 与后端状态机对齐', () => {
    expect(allowedTransitions('open')).toEqual(['scheduled', 'in_progress', 'wontfix']);
    expect(allowedTransitions('scheduled')).toEqual(['in_progress', 'open', 'wontfix']);
    expect(allowedTransitions('in_progress')).toEqual(['resolved', 'open', 'wontfix']);
  });

  it('conflict 态交回用户处置：回池/重新绑会/闭环/放弃（D11）', () => {
    expect(allowedTransitions('conflict')).toEqual(['open', 'in_progress', 'resolved', 'wontfix']);
  });

  it('终态无任何合法流转目标', () => {
    expect(allowedTransitions('resolved')).toEqual([]);
    expect(allowedTransitions('wontfix')).toEqual([]);
  });

  it('未知状态兜底为空数组而非抛错（非正向）', () => {
    expect(allowedTransitions('not-a-status')).toEqual([]);
    expect(allowedTransitions('')).toEqual([]);
  });

  it('isBindable：open/scheduled/conflict 可绑定会议（conflict 重绑会重做，D11）', () => {
    expect(isBindable('open')).toBe(true);
    expect(isBindable('scheduled')).toBe(true);
    expect(isBindable('conflict')).toBe(true);
  });

  it('其余状态不可绑定（非正向）', () => {
    expect(isBindable('in_progress')).toBe(false);
    expect(isBindable('resolved')).toBe(false);
    expect(isBindable('wontfix')).toBe(false);
    expect(isBindable('unknown')).toBe(false);
  });

  it('isMergeable：仅 in_progress/conflict 可发起合入（镜像后端 MERGEABLE_STATUSES）', () => {
    expect(isMergeable('in_progress')).toBe(true);
    expect(isMergeable('conflict')).toBe(true);
  });

  it('其余状态不可合入（非正向）', () => {
    expect(isMergeable('open')).toBe(false);
    expect(isMergeable('scheduled')).toBe(false);
    expect(isMergeable('resolved')).toBe(false);
    expect(isMergeable('wontfix')).toBe(false);
    expect(isMergeable('unknown')).toBe(false);
  });

  it('六种状态均有中文标签且流转表键完整', () => {
    expect(ISSUE_STATUSES).toHaveLength(6);
    for (const status of ISSUE_STATUSES) {
      expect(ISSUE_STATUS_LABELS[status]).toBeTruthy();
      expect(ALLOWED_TRANSITIONS[status]).toBeDefined();
    }
  });
});
