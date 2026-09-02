/**
 * 路由画布页（/meeting/:id/canvas/:kind）—— 画布体系的"整页档"（问题 4）。
 *
 * 与悬浮画布（FloatingPanel M/L/XL 档）的分工：
 * - 悬浮档：会议内旁路速览，边看边聊；
 * - 路由画布：重内容整页阅读（完整冲突证据、操作回放全量），
 *   真实 URL 可收藏/分享/开新标签页，浏览器后退返回会议。
 *
 * 内容组件复用悬浮画布同款（InsightsCanvas / OperationReplayContent），
 * 两者数据均经 react-query 从 API 自加载，新标签页独立打开无需会议页上下文。
 * 洞察三 tab 切换直接改 URL（/canvas/conflicts|related|observability），
 * 每个 tab 都是可分享的独立地址。
 */
import * as React from 'react';
import { useParams, useNavigate, Navigate } from 'react-router';
import { useMeeting } from '@/hooks/use-meetings';
import { InsightsCanvas, type InsightsTab } from '@/components/meeting/insights-panel';
import { OperationReplayContent } from '@/components/meeting/operation-replay';
import { ChevronLeftIcon } from '@/components/ui/svg-icons';
import { truncate } from '@/lib/utils';

const CANVAS_KINDS = ['conflicts', 'related', 'observability', 'replay'] as const;
type CanvasRouteKind = (typeof CANVAS_KINDS)[number];

const KIND_TITLES: Record<CanvasRouteKind, string> = {
  conflicts: '冲突与证据',
  related: '相关会议',
  observability: '可观测',
  replay: '操作回放',
};

function isCanvasKind(v: string | undefined): v is CanvasRouteKind {
  return !!v && (CANVAS_KINDS as readonly string[]).includes(v);
}

export default function MeetingCanvasPage() {
  const { id, kind } = useParams<{ id: string; kind: string }>();
  const navigate = useNavigate();
  const { data: meeting } = useMeeting(id);

  // 非法参数兜底：缺会议 id 回看板；未知画布类别回会议页（非正向路径）
  if (!id) return <Navigate to="/board" replace />;
  if (!isCanvasKind(kind)) return <Navigate to={`/meeting/${id}`} replace />;

  const handleTabChange = (tab: InsightsTab) => {
    navigate(`/meeting/${id}/canvas/${tab}`);
  };

  return (
    <div className="flex w-full min-w-0 flex-col bg-bg-primary">
      {/* 顶栏：会议上下文 + 返回（浏览器后退语义一致） */}
      <div className="flex flex-shrink-0 items-center gap-2 border-b border-border-soft px-6 py-3">
        <button
          type="button"
          onClick={() => navigate(`/meeting/${id}`)}
          className="rounded-md p-1.5 text-text-tertiary transition-colors hover:bg-bg-tertiary hover:text-text-secondary"
          aria-label="返回会议"
          title="返回会议"
        >
          <ChevronLeftIcon size={16} />
        </button>
        <div className="min-w-0">
          <h1 className="text-sm font-semibold text-text-primary">{KIND_TITLES[kind]}</h1>
          <p className="truncate text-xs text-text-tertiary">
            {meeting?.title ? truncate(meeting.title, 60) : '会议加载中...'}
          </p>
        </div>
      </div>

      {/* 内容区：居中限宽阅读容器，内部滚动 */}
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-5xl px-6 py-4">
          {kind === 'replay' ? (
            <OperationReplayContent meetingId={id} />
          ) : (
            <InsightsCanvas meetingId={id} tab={kind} onTabChange={handleTabChange} />
          )}
        </div>
      </div>
    </div>
  );
}
