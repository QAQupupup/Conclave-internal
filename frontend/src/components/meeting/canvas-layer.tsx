import * as React from 'react';
import { FloatingPanel } from '@/components/ui/floating-panel';
import { InsightsCanvas, type InsightsTab } from '@/components/meeting/insights-panel';
import { OperationReplayContent } from '@/components/meeting/operation-replay';
import { useUIStore } from '@/stores/ui-slice';

const INSIGHT_TITLES: Record<InsightsTab, string> = {
  conflicts: '冲突与证据',
  related: '相关会议',
  observability: '可观测',
};

/**
 * 悬浮画布层：按 ui-slice.activeCanvas 渲染当前画布（单焦点，互斥）。
 * - 洞察三 tab 共用一个画布（tab 即焦点）：默认 M 档，M/L/XL 双向切换（持久化）。
 * - 操作回放为独立画布：默认 L 档，同样支持档位切换与拖拽吸附。
 * - 画布内容组件无条件传入 children：FloatingPanel 在关闭时整体不挂载，
 *   退场动画期间保留内容 200ms，避免外壳还在动画、内容已消失。
 */
export function CanvasLayer({ meetingId }: { meetingId: string }) {
  const activeCanvas = useUIStore((s) => s.activeCanvas);
  const insightsCanvasSize = useUIStore((s) => s.insightsCanvasSize);
  const replayCanvasSize = useUIStore((s) => s.replayCanvasSize);
  const openCanvas = useUIStore((s) => s.openCanvas);
  const closeCanvas = useUIStore((s) => s.closeCanvas);
  const setInsightsCanvasSize = useUIStore((s) => s.setInsightsCanvasSize);
  const setReplayCanvasSize = useUIStore((s) => s.setReplayCanvasSize);

  const insightTab: InsightsTab | null =
    activeCanvas === 'conflicts' || activeCanvas === 'related' || activeCanvas === 'observability'
      ? activeCanvas
      : null;

  // 退场动画期间沿用最后一次聚焦的 tab（标题与内容随外壳一起退场）
  const lastTabRef = React.useRef<InsightsTab>('conflicts');
  if (insightTab !== null) {
    lastTabRef.current = insightTab;
  }
  const shownTab = insightTab ?? lastTabRef.current;

  return (
    <>
      <FloatingPanel
        open={insightTab !== null}
        onClose={closeCanvas}
        size={insightsCanvasSize}
        title={INSIGHT_TITLES[shownTab]}
        onSizeChange={setInsightsCanvasSize}
        popoutHref={`/meeting/${meetingId}/canvas/${shownTab}`}
      >
        <InsightsCanvas meetingId={meetingId} tab={shownTab} onTabChange={openCanvas} />
      </FloatingPanel>
      <FloatingPanel
        open={activeCanvas === 'replay'}
        onClose={closeCanvas}
        size={replayCanvasSize}
        title="操作回放"
        onSizeChange={setReplayCanvasSize}
        popoutHref={`/meeting/${meetingId}/canvas/replay`}
      >
        <OperationReplayContent meetingId={meetingId} />
      </FloatingPanel>
    </>
  );
}
