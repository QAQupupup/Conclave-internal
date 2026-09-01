import { describe, it, expect } from 'vitest';
import { buildToolCallsFromEvents } from '@/components/meeting/operation-replay-utils';
import type { RawMeetingEvent } from '@/lib/api';

function ev(type: string, payload: Record<string, unknown>, ts: string, seq: number): RawMeetingEvent {
  return { type, meeting_id: 'm1', payload, ts, seq };
}

describe('buildToolCallsFromEvents', () => {
  it('从 started/step/completed 事件重建完整调用记录', () => {
    const events: RawMeetingEvent[] = [
      ev('tool.started', { call_id: 'c1', tool_name: 'web_search', arguments: { query: 'x' }, iteration: 0 }, '2026-01-01T00:00:00Z', 1),
      ev('tool.step', { call_id: 'c1', tool_name: 'web_search', step_type: 'search_started', data: { label: '搜索：x', status: 'running' } }, '2026-01-01T00:00:01Z', 2),
      ev('tool.step', { call_id: 'c1', tool_name: 'web_search', step_type: 'results_found', data: { label: '找到 3 条', status: 'completed', screenshot: 'b64', url: 'https://a.com' } }, '2026-01-01T00:00:02Z', 3),
      ev('tool.completed', { call_id: 'c1', tool_name: 'web_search', success: true, latency_ms: 400, summary: { count: 3 } }, '2026-01-01T00:00:03Z', 4),
    ];

    const calls = buildToolCallsFromEvents(events);
    expect(calls).toHaveLength(1);
    const c = calls[0];
    expect(c.id).toBe('c1');
    expect(c.status).toBe('completed');
    expect(c.success).toBe(true);
    expect(c.latencyMs).toBe(400);
    expect(c.steps).toHaveLength(2);
    // 截图与 URL 应从 step data 透传
    expect(c.steps[1].screenshot).toBe('b64');
    expect(c.steps[1].url).toBe('https://a.com');
  });

  it('忽略非工具事件与无 call_id 的事件', () => {
    const events: RawMeetingEvent[] = [
      ev('agent.speak', { content: 'hi' }, '2026-01-01T00:00:00Z', 1),
      ev('tool.step', { tool_name: 'web_search', step_type: 'x', data: {} }, '2026-01-01T00:00:01Z', 2),
      ev('tool.failed', { call_id: 'ghost', tool_name: 'web_search', success: false }, '2026-01-01T00:00:02Z', 3),
    ];
    expect(buildToolCallsFromEvents(events)).toEqual([]);
  });

  it('tool.failed 将状态标记为 failed 并保留错误信息', () => {
    const events: RawMeetingEvent[] = [
      ev('tool.started', { call_id: 'c2', tool_name: 'browser.goto', arguments: {}, iteration: 0 }, '2026-01-01T00:00:00Z', 1),
      ev('tool.failed', { call_id: 'c2', tool_name: 'browser.goto', success: false, error: 'timeout', latency_ms: 50 }, '2026-01-01T00:00:02Z', 2),
    ];
    const calls = buildToolCallsFromEvents(events);
    expect(calls).toHaveLength(1);
    expect(calls[0].status).toBe('failed');
    expect(calls[0].success).toBe(false);
    expect(calls[0].error).toBe('timeout');
  });

  it('空输入返回空数组', () => {
    expect(buildToolCallsFromEvents([])).toEqual([]);
  });
});