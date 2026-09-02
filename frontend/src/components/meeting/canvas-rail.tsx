import * as React from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { useMeetingDetailRaw } from '@/hooks/use-meetings';
import { useUIStore, type CanvasKind } from '@/stores/ui-slice';
import { cn } from '@/lib/utils';
import {
  ActivityIcon,
  AlertCircleIcon,
  ClockIcon,
  LinkIcon,
} from '@/components/ui/svg-icons';

interface RailItem {
  kind: CanvasKind;
  label: string;
  Icon: React.ComponentType<{ size?: number; className?: string }>;
}

const INSIGHT_ITEMS: RailItem[] = [
  { kind: 'conflicts', label: '冲突与证据', Icon: AlertCircleIcon },
  { kind: 'related', label: '相关会议', Icon: LinkIcon },
  { kind: 'observability', label: '可观测', Icon: ActivityIcon },
];

const REPLAY_ITEM: RailItem = { kind: 'replay', label: '操作回放', Icon: ClockIcon };

/**
 * 悬浮画布入口徽标轨：对话流右侧的垂直小徽标列。
 * - 悬停显示功能名（title），点击打开对应悬浮画布；再次点击当前徽标收起画布。
 * - 单焦点互斥由 ui-slice.openCanvas 保证（打开一个自动替换另一个）。
 * - 冲突徽标带数量角标（冲突条目 + 图谱支撑边），数据与洞察画布共用同一
 *   queryKey，react-query 缓存去重，不产生额外请求。
 */
export function CanvasRail({ meetingId }: { meetingId: string }) {
  const activeCanvas = useUIStore((s) => s.activeCanvas);
  const openCanvas = useUIStore((s) => s.openCanvas);
  const closeCanvas = useUIStore((s) => s.closeCanvas);

  const detail = useMeetingDetailRaw(meetingId);
  const graph = useQuery({
    queryKey: ['graph', 'overview', meetingId],
    queryFn: () => api.graphOverview(meetingId),
    enabled: !!meetingId,
  });

  const conflicts = Array.isArray(detail.data?.conflicts) ? detail.data!.conflicts : [];
  const edges = Array.isArray(graph.data?.edges) ? graph.data!.edges : [];
  const conflictBadge = conflicts.length + edges.filter((e) => e.type === 'supports').length;

  const toggle = (kind: CanvasKind) => {
    if (activeCanvas === kind) {
      closeCanvas();
    } else {
      openCanvas(kind);
    }
  };

  const renderBadge = ({ kind, label, Icon }: RailItem, badge?: number) => {
    const active = activeCanvas === kind;
    return (
      <button
        key={kind}
        type="button"
        onClick={() => toggle(kind)}
        title={label}
        aria-label={label}
        aria-pressed={active}
        className={cn(
          'relative flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-md border transition-colors duration-(--duration-hover)',
          active
            ? 'border-brand-500/40 bg-brand-soft text-brand-600'
            : 'border-border-soft bg-bg-primary text-text-tertiary hover:border-border-default hover:text-text-secondary',
        )}
      >
        <Icon size={15} />
        {typeof badge === 'number' && badge > 0 && (
          <span
            aria-hidden="true"
            className="absolute -right-1.5 -top-1.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-danger px-1 text-[9px] font-medium leading-none text-white"
          >
            {badge > 99 ? '99+' : badge}
          </span>
        )}
      </button>
    );
  };

  return (
    <div className="flex w-10 flex-shrink-0 flex-col items-center gap-2 border-l border-border-soft py-4">
      {INSIGHT_ITEMS.map((item) =>
        renderBadge(item, item.kind === 'conflicts' ? conflictBadge : undefined),
      )}
      {/* 分隔线：洞察家族与会议级工具（回放）分组 */}
      <div className="my-1 h-px w-5 bg-border-soft" aria-hidden="true" />
      {renderBadge(REPLAY_ITEM)}
    </div>
  );
}
