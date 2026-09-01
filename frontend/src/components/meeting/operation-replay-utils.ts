import type { RawMeetingEvent } from '@/lib/api';
import type { ToolCallRecord, ToolStep } from '@/types';

/** 可回放的工具事件类型 */
const TOOL_EVENT_TYPES = new Set(['tool.started', 'tool.step', 'tool.completed', 'tool.failed']);

/**
 * 从持久化领域事件（后端 /meetings/{id}/events）重建工具调用记录。
 *
 * 供「话题结束后」历史回放使用：会议页首次加载或 WS 尚未连接时，
 * 通过 REST 拉取完整事件流，还原成与实时 store 相同结构的 ToolCallRecord 列表。
 * 事件顺序由后端 seq 保证，这里按 startedAt 稳定排序。
 */
export function buildToolCallsFromEvents(events: RawMeetingEvent[]): ToolCallRecord[] {
  const map = new Map<string, ToolCallRecord>();

  for (const ev of events) {
    if (!TOOL_EVENT_TYPES.has(ev.type)) continue;
    const p = ev.payload || {};
    const callId = typeof p.call_id === 'string' && p.call_id ? p.call_id : '';
    if (!callId) continue;

    switch (ev.type) {
      case 'tool.started': {
        if (map.has(callId)) break;
        map.set(callId, {
          id: callId,
          toolName: String(p.tool_name || ''),
          iteration: Number(p.iteration || 0),
          status: 'running',
          arguments: (p.arguments as Record<string, unknown>) || {},
          reason: typeof p.reason === 'string' ? p.reason : undefined,
          startedAt: ev.ts,
          steps: [],
        });
        break;
      }
      case 'tool.step': {
        const rec = map.get(callId);
        if (!rec) break;
        const d = (p.data as Record<string, unknown>) || {};
        const statusFromData = d.status === 'running' || d.status === 'completed' || d.status === 'failed'
          ? d.status
          : 'completed';
        rec.steps.push({
          id: `${callId}-step-${rec.steps.length}`,
          callId,
          stepType: String(p.step_type || ''),
          label: String(d.label || p.step_type || ''),
          data: d,
          screenshot: typeof d.screenshot === 'string' ? d.screenshot : undefined,
          screenshotRef: typeof d.screenshot_ref === 'string' ? d.screenshot_ref : undefined,
          url: typeof d.url === 'string' ? d.url : undefined,
          status: statusFromData as ToolStep['status'],
          timestamp: ev.ts,
        });
        break;
      }
      case 'tool.completed':
      case 'tool.failed': {
        const rec = map.get(callId);
        if (!rec) break;
        const failed = ev.type === 'tool.failed' || p.success === false;
        rec.status = failed ? 'failed' : 'completed';
        rec.success = !failed;
        if (typeof p.error === 'string') rec.error = p.error;
        if (typeof p.latency_ms === 'number') rec.latencyMs = p.latency_ms;
        if (p.summary && typeof p.summary === 'object') {
          rec.summary = p.summary as Record<string, unknown>;
        }
        rec.completedAt = ev.ts;
        break;
      }
    }
  }

  return [...map.values()].sort((a, b) => a.startedAt.localeCompare(b.startedAt));
}