import * as React from 'react';
import { useParams, useNavigate } from 'react-router';
import { StageTimeline } from '@/components/meeting/stage-timeline';
import { MessageStream } from '@/components/meeting/message-stream';
import { ThoughtTree } from '@/components/meeting/thought-tree';
import { InsightsPanel } from '@/components/meeting/insights-panel';
import { ResizableHandle } from '@/components/ui/resizable';
import { Button } from '@/components/ui/button';
import { useUIStore } from '@/stores';
import { useMeeting, useControlMeeting } from '@/hooks/use-meetings';
import { useMeetingStore } from '@/stores';
import {
  PanelLeftCloseIcon,
  PanelLeftOpenIcon,
  PanelRightCloseIcon,
  PanelRightOpenIcon,
  SpinnerIcon,
} from '@/components/ui/svg-icons';
import { wsClient } from '@/lib/ws';

export default function ExplorePage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { data: meeting, isLoading, error } = useMeeting(id);
  const controlMeeting = useControlMeeting();
  const timelineWidth = useUIStore((s) => s.timelineWidth);
  const thoughtTreeWidth = useUIStore((s) => s.thoughtTreeWidth);
  const timelineCollapsed = useUIStore((s) => s.timelineCollapsed);
  const thoughtTreeCollapsed = useUIStore((s) => s.thoughtTreeCollapsed);
  const setTimelineWidth = useUIStore((s) => s.setTimelineWidth);
  const setThoughtTreeWidth = useUIStore((s) => s.setThoughtTreeWidth);
  const toggleTimeline = useUIStore((s) => s.toggleTimeline);
  const toggleThoughtTree = useUIStore((s) => s.toggleThoughtTree);
  const setMeeting = useMeetingStore((s) => s.setMeeting);

  // Initialize store from API data when loaded
  React.useEffect(() => {
    if (meeting && id) {
      setMeeting(id, meeting.title || '探索中');
      if (meeting.agents) useMeetingStore.getState().setAgents(meeting.agents);
      if (meeting.stage) useMeetingStore.getState().setStage(meeting.stage);
      if (meeting.status) useMeetingStore.getState().setStatus(meeting.status);
      if (meeting.startedAt) useMeetingStore.setState({ startedAt: meeting.startedAt });
    }
  }, [meeting, id, setMeeting]);

  // Responsive: auto-collapse sidebars on small screens (< 1024px)
  React.useEffect(() => {
    const RESPONSIVE_BREAKPOINT = 1024;
    let wasSmallScreen = window.innerWidth < RESPONSIVE_BREAKPOINT;

    // Auto-collapse on initial load if small screen
    if (wasSmallScreen) {
      useUIStore.getState().setTimelineCollapsed(true);
      useUIStore.getState().setThoughtTreeCollapsed(true);
    }

    const handleResize = () => {
      const isSmallScreen = window.innerWidth < RESPONSIVE_BREAKPOINT;
      // Only auto-collapse when transitioning from large to small
      if (isSmallScreen && !wasSmallScreen) {
        useUIStore.getState().setTimelineCollapsed(true);
        useUIStore.getState().setThoughtTreeCollapsed(true);
      }
      wasSmallScreen = isSmallScreen;
    };

    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  const handleTimelineResize = (newSize: number) => {
    setTimelineWidth(Math.max(200, Math.min(380, newSize)));
  };

  const handleThoughtTreeResize = (newSize: number) => {
    setThoughtTreeWidth(Math.max(240, Math.min(480, newSize)));
  };

  const handleStop = () => {
    if (id) controlMeeting.mutate({ id, signal: 'stop' });
  };

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center bg-bg-secondary">
        <div className="flex flex-col items-center gap-3">
          <SpinnerIcon size={24} className="animate-spin text-brand-500" />
          <span className="text-sm text-text-tertiary">加载会议...</span>
        </div>
      </div>
    );
  }

  if (error || !meeting) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-4 bg-bg-secondary">
        <div className="text-sm text-danger">
          加载失败，讨论可能已被删除或您没有访问权限
          {import.meta.env.DEV && (error as Error)?.message && (
            <div className="mt-1 text-xs text-text-tertiary">{(error as Error).message}</div>
          )}
        </div>
        <Button variant="outline" onClick={() => navigate('/board')}>返回看板</Button>
      </div>
    );
  }

  return (
    <div className="flex h-full w-full bg-bg-secondary">
      {/* Left: Collapsed timeline toggle */}
      {timelineCollapsed && (
        <button
          onClick={toggleTimeline}
          className="flex w-6 flex-shrink-0 items-center justify-center border-r border-border-soft bg-bg-primary hover:bg-bg-tertiary transition-colors group"
          title="展开阶段时间线"
          aria-label="展开阶段时间线"
        >
          <PanelLeftOpenIcon size={14} className="text-text-tertiary group-hover:text-text-secondary" />
        </button>
      )}

      {/* Left: Stage Timeline */}
      {!timelineCollapsed && (
        <>
          <div
            className="flex flex-shrink-0 flex-col border-r border-border-soft"
            style={{ width: timelineWidth }}
          >
            <div className="flex h-8 items-center justify-end border-b border-border-soft px-1">
              <Button variant="ghost" size="icon" className="h-6 w-6" onClick={toggleTimeline} title="折叠时间线" aria-label="折叠时间线">
                <PanelLeftCloseIcon size={13} />
              </Button>
            </div>
            <StageTimeline className="min-h-0 flex-1" />
          </div>
          <ResizableHandle
            direction="horizontal"
            onResize={handleTimelineResize}
            minSize={200}
            maxSize={380}
            currentSize={timelineWidth}
          />
        </>
      )}

      {/* Center: Message Stream (flex-1) */}
      <div className="flex min-w-0 flex-1">
        <MessageStream className="flex-1" />
      </div>

      {/* Right: Thought Tree */}
      {!thoughtTreeCollapsed && (
        <>
          <ResizableHandle
            direction="horizontal"
            onResize={handleThoughtTreeResize}
            minSize={240}
            maxSize={480}
            currentSize={thoughtTreeWidth}
            reverse
          />
          <div
            className="flex flex-shrink-0 flex-col border-l border-border-soft"
            style={{ width: thoughtTreeWidth }}
          >
            <div className="flex h-8 items-center justify-between border-b border-border-soft px-1">
              <span className="px-1 text-[11px] font-medium text-text-tertiary">侧栏</span>
              <Button variant="ghost" size="icon" className="h-6 w-6" onClick={toggleThoughtTree} title="折叠侧栏" aria-label="折叠侧栏">
                <PanelRightCloseIcon size={13} />
              </Button>
            </div>
            <div className="flex min-h-0 flex-1 flex-col">
              {/* Agent 状态树（上半） */}
              <div className="flex min-h-0 flex-1 flex-col border-b border-border-soft">
                <div className="flex h-7 flex-shrink-0 items-center border-b border-border-soft px-2 text-[11px] font-medium text-text-tertiary">
                  Agent 状态树
                </div>
                <ThoughtTree className="min-h-0 flex-1" />
              </div>
              {/* 可观测性面板（下半）：冲突/证据、相关会议、关键指标 */}
              <div className="flex min-h-0 flex-1 flex-col">
                <InsightsPanel meetingId={id!} />
              </div>
            </div>
          </div>
        </>
      )}

      {/* Right: Collapsed thought tree toggle */}
      {thoughtTreeCollapsed && (
        <button
          onClick={toggleThoughtTree}
          className="flex w-6 flex-shrink-0 items-center justify-center border-l border-border-soft bg-bg-primary hover:bg-bg-tertiary transition-colors group"
          title="展开 Agent 状态树"
          aria-label="展开 Agent 状态树"
        >
          <PanelRightOpenIcon size={14} className="text-text-tertiary group-hover:text-text-secondary" />
        </button>
      )}
    </div>
  );
}
