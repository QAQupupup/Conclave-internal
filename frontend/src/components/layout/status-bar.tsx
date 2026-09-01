import * as React from 'react';
import { useMeetingStore } from '@/stores/meeting-slice';
import { useWSStore } from '@/stores/ws-slice';
import { cn, formatDurationFromStart } from '@/lib/utils';
import { STAGE_LABELS } from '@/lib/constants';
import { isDemoMode } from '@/lib/mock-data';

export function StatusBar() {
  const wsStatus = useWSStore((s) => s.status);
  const wsError = useWSStore((s) => s.error);
  const reconnectCount = useWSStore((s) => s.reconnectCount);
  const meeting = useMeetingStore();

  const isConnected = wsStatus === 'connected';
  const isInMeeting = !!meeting.currentMeetingId;
  // MR-2：演示模式必须有持久可见标识，避免用户把 mock 数据当成真实数据
  const demo = isDemoMode();

  return (
    <footer className="flex h-6 flex-shrink-0 items-center gap-3 border-t border-border-soft bg-bg-primary px-4 text-[11px] text-text-tertiary">
      {demo && (
        <>
          <span className="rounded-sm bg-warning/15 px-1.5 py-px font-medium text-warning">
            演示数据
          </span>
          <div className="h-3 w-px bg-border-soft" />
        </>
      )}
      <div className="flex items-center gap-1.5">
        <span
          className={cn(
            'inline-block h-1.5 w-1.5 rounded-full',
            isConnected ? 'bg-success' : wsStatus === 'connecting' ? 'bg-warning animate-pulse' : 'bg-danger'
          )}
        />
        <span>
          {isConnected
            ? '已连接'
            : wsStatus === 'connecting'
              ? reconnectCount > 0
                ? wsError || `重连中 (${reconnectCount})`
                : '连接中...'
              : '未连接'}
        </span>
      </div>

      {isInMeeting && (
        <React.Fragment>
          <div className="h-3 w-px bg-border-soft" />
          <span className="flex items-center gap-1.5">
            <span
              className={cn(
                'inline-block h-1.5 w-1.5 rounded-full',
                meeting.status === 'running' && 'animate-pulse bg-stage-running',
                meeting.status === 'paused' && 'bg-stage-paused',
                meeting.status === 'done' && 'bg-stage-done',
                meeting.status === 'error' && 'bg-stage-error'
              )}
            />
            {meeting.status === 'running' ? '运行中' : meeting.status === 'paused' ? '已暂停' : meeting.status === 'done' ? '已结束' : meeting.status === 'error' ? '异常' : meeting.status === 'aborted' ? '已终止' : meeting.status === 'pending' ? '等待中' : meeting.status}
          </span>
          <div className="h-3 w-px bg-border-soft" />
          <span>阶段: {STAGE_LABELS[meeting.stage] || meeting.stage}</span>
          <div className="h-3 w-px bg-border-soft" />
          <span>消息: {meeting.messages.length}</span>
          <div className="h-3 w-px bg-border-soft" />
          <span>Agent: {meeting.agents.length}</span>
          <div className="h-3 w-px bg-border-soft" />
          <span>{formatDurationFromStart(meeting.startedAt, meeting.status === 'running')}</span>
        </React.Fragment>
      )}

      <div className="ml-auto" />
    </footer>
  );
}
