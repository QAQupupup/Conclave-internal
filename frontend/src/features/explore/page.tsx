import * as React from 'react';
import { useParams, useNavigate } from 'react-router';
import { StageTimeline } from '@/components/meeting/stage-timeline';
import { MessageStream } from '@/components/meeting/message-stream';
import { ThoughtTree } from '@/components/meeting/thought-tree';
import { CanvasRail } from '@/components/meeting/canvas-rail';
import { CanvasLayer } from '@/components/meeting/canvas-layer';
import { SidePanel } from '@/components/ui/side-panel';
import { Button } from '@/components/ui/button';
import { useUIStore } from '@/stores/ui-slice';
import { useMeeting } from '@/hooks/use-meetings';
import { useMeetingStore } from '@/stores/meeting-slice';
import { SpinnerIcon } from '@/components/ui/svg-icons';

export default function ExplorePage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { data: meeting, isLoading, error } = useMeeting(id);
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
      {/* 左栏：阶段时间线（SidePanel：同位切换柄 + 拖拽调宽） */}
      <SidePanel
        side="left"
        collapsed={timelineCollapsed}
        onToggle={toggleTimeline}
        label="阶段时间线"
        width={timelineWidth}
        onWidthChange={setTimelineWidth}
        minSize={200}
        maxSize={380}
      >
        <StageTimeline className="h-full" />
      </SidePanel>

      {/* Center: Message Stream (flex-1) */}
      <div className="flex min-w-0 flex-1">
        <MessageStream className="flex-1" />
      </div>

      {/* 悬浮画布入口徽标轨（洞察 ×3 + 操作回放） */}
      <CanvasRail meetingId={id!} />

      {/* 右栏：Agent 状态树（洞察内容已迁移至悬浮画布） */}
      <SidePanel
        side="right"
        collapsed={thoughtTreeCollapsed}
        onToggle={toggleThoughtTree}
        label="Agent 状态树"
        width={thoughtTreeWidth}
        onWidthChange={setThoughtTreeWidth}
        minSize={240}
        maxSize={480}
      >
        <ThoughtTree className="h-full" />
      </SidePanel>

      {/* 悬浮画布层：洞察画布（M/L/XL 档）+ 操作回放画布，单焦点互斥 */}
      <CanvasLayer meetingId={id!} />
    </div>
  );
}
