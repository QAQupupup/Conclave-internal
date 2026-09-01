import * as React from 'react';
import { useNavigate } from 'react-router';
import { useMeetingsOverview } from '@/hooks/use-meetings';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import { ScrollArea } from '@/components/ui/scroll-area';
import { cn, formatRelativeTime, truncate } from '@/lib/utils';
import { STAGE_LABELS } from '@/lib/constants';
import type { Meeting, MeetingStatus } from '@/types';
import {
  MonitorIcon,
  RefreshCwIcon,
  PlayCircleIcon,
  PauseIcon,
  CheckCircleIcon,
  XCircleIcon,
  UsersIcon,
  MessageSquareIcon,
  ClockIcon,
  ArrowRightIcon,
  SpinnerIcon,
  AlertCircleIcon,
  LayoutDashboardIcon,
} from '@/components/ui/svg-icons';

const STATUS_CONFIG: Record<MeetingStatus, { label: string; variant: 'default' | 'secondary' | 'outline' | 'destructive' | 'success' | 'warning'; color: string }> = {
  pending: { label: '待开始', variant: 'outline', color: 'text-text-tertiary' },
  running: { label: '运行中', variant: 'default', color: 'text-white' },
  paused: { label: '已暂停', variant: 'warning', color: 'text-warning' },
  done: { label: '已完成', variant: 'success', color: 'text-success' },
  error: { label: '出错', variant: 'destructive', color: 'text-danger' },
  aborted: { label: '已终止', variant: 'secondary', color: 'text-text-tertiary' },
};

const POLL_INTERVAL_MS = 3000;

/** 稳定空数组引用，避免 useMemo 依赖每帧变化 */
const EMPTY_MEETINGS: Meeting[] = [];

/** 统计快照：状态计数从会议列表本地派生，总数优先用后端真实 total（列表最多取 200 条） */
interface Stats {
  total: number;
  running: number;
  paused: number;
  done: number;
  failed: number;
}

function deriveStats(meetings: Meeting[], knownTotal?: number): Stats {
  let running = 0;
  let paused = 0;
  let done = 0;
  let failed = 0;
  for (const m of meetings) {
    if (m.status === 'running') running += 1;
    else if (m.status === 'paused') paused += 1;
    else if (m.status === 'done') done += 1;
    else if (m.status === 'error' || m.status === 'aborted') failed += 1;
  }
  return { total: knownTotal ?? meetings.length, running, paused, done, failed };
}

export default function MonitoringPage() {
  const navigate = useNavigate();
  const { data, isFetching, isError, refetch, dataUpdatedAt } = useMeetingsOverview(POLL_INTERVAL_MS);

  const meetings = data?.meetings ?? EMPTY_MEETINGS;
  const stats = React.useMemo(() => deriveStats(meetings, data?.total), [meetings, data?.total]);
  const active = React.useMemo(
    () => meetings.filter((m) => m.status === 'running' || m.status === 'paused'),
    [meetings]
  );

  const concurrentLimit = data?.concurrentLimit ?? 0;
  const runningCount = data?.runningCount ?? stats.running;

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex-shrink-0 border-b border-border-soft bg-bg-primary p-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <MonitorIcon size={20} className="text-brand-500" />
            <h2 className="text-lg font-semibold text-text-primary">会话监控</h2>
            <span className="flex items-center gap-1.5 rounded-full border border-border-soft bg-bg-secondary px-2 py-0.5 text-[11px] text-text-tertiary">
              <span className={cn('h-1.5 w-1.5 rounded-full', isFetching ? 'animate-pulse bg-brand-500' : 'bg-success')} />
              {isFetching ? '刷新中' : '实时'}
            </span>
          </div>
          <div className="flex items-center gap-2">
            {dataUpdatedAt ? (
              <span className="hidden text-[11px] text-text-tertiary sm:inline">
                更新于 {formatRelativeTime(dataUpdatedAt)}
              </span>
            ) : null}
            <Button size="sm" variant="outline" onClick={() => refetch()} disabled={isFetching}>
              <RefreshCwIcon size={14} className={cn('mr-1', isFetching && 'animate-spin')} />
              刷新
            </Button>
          </div>
        </div>
        <p className="mt-1 text-xs text-text-tertiary">
          实时总览所有进行中与历史讨论会话
        </p>
      </div>

      <ScrollArea className="flex-1">
        <div className="space-y-6 p-4">
          {/* 加载 / 错误态 */}
          {!data && isFetching ? (
            <div className="flex items-center justify-center py-16 text-text-tertiary">
              <SpinnerIcon size={20} className="animate-spin" />
            </div>
          ) : isError ? (
            <Card>
              <CardContent className="flex items-center gap-2 py-6 text-sm text-danger">
                <AlertCircleIcon size={16} />
                监控数据加载失败，请稍后重试
              </CardContent>
            </Card>
          ) : (
            <>
              {/* 统计卡片 */}
              <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
                <StatCard icon={LayoutDashboardIcon} label="会议总数" value={stats.total} />
                <StatCard icon={PlayCircleIcon} label="运行中" value={stats.running} tone="brand" live={stats.running > 0} />
                <StatCard icon={PauseIcon} label="已暂停" value={stats.paused} tone="warning" />
                <StatCard icon={CheckCircleIcon} label="已完成" value={stats.done} tone="success" />
                <StatCard icon={XCircleIcon} label="异常/终止" value={stats.failed} tone="danger" />
              </div>

              {/* 并发槽位 */}
              <Card>
                <CardHeader className="pb-3">
                  <div className="flex items-center justify-between">
                    <div className="text-base font-semibold text-text-primary">并发槽位</div>
                    <span className="text-xs text-text-tertiary">
                      {concurrentLimit > 0 ? `${runningCount} / ${concurrentLimit}` : `${runningCount} 个运行中`}
                    </span>
                  </div>
                </CardHeader>
                <CardContent>
                  <ConcurrencyGauge running={runningCount} limit={concurrentLimit} />
                </CardContent>
              </Card>

              {/* 进行中的会话 */}
              <section>
                <div className="mb-3 flex items-center gap-2">
                  <span className="relative flex h-2 w-2 items-center justify-center">
                    <span className="absolute h-2 w-2 animate-ping rounded-full bg-brand-500/40" />
                    <span className="relative h-1.5 w-1.5 rounded-full bg-brand-500" />
                  </span>
                  <h3 className="text-sm font-medium text-text-primary">进行中的会话</h3>
                  <Badge variant="secondary" className="text-[10px] text-text-tertiary">{active.length}</Badge>
                </div>
                {active.length === 0 ? (
                  <Card>
                    <CardContent className="py-10 text-center text-sm text-text-tertiary">
                      当前没有进行中的会话
                    </CardContent>
                  </Card>
                ) : (
                  <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                    {active.map((m) => (
                      <ActiveMeetingCard key={m.id} meeting={m} onClick={() => navigate(`/meeting/${m.id}`)} />
                    ))}
                  </div>
                )}
              </section>

              {/* 全部会话表格 */}
              <section>
                <div className="mb-3 flex items-center gap-2">
                  <h3 className="text-sm font-medium text-text-primary">全部会话</h3>
                  <Badge variant="secondary" className="text-[10px] text-text-tertiary">{meetings.length}</Badge>
                </div>
                {meetings.length === 0 ? (
                  <Card>
                    <CardContent className="py-10 text-center text-sm text-text-tertiary">
                      暂无会话记录
                    </CardContent>
                  </Card>
                ) : (
                  <Card>
                    <div className="overflow-x-auto">
                      <table className="w-full text-sm">
                        <thead>
                          <tr className="border-b border-border-soft text-left text-xs text-text-tertiary">
                            <th className="px-4 py-2.5 font-medium">议题</th>
                            <th className="px-4 py-2.5 font-medium">状态</th>
                            <th className="px-4 py-2.5 font-medium">阶段</th>
                            <th className="px-4 py-2.5 font-medium">Agent</th>
                            <th className="px-4 py-2.5 font-medium">消息</th>
                            <th className="px-4 py-2.5 font-medium">创建时间</th>
                            <th className="px-4 py-2.5 font-medium"></th>
                          </tr>
                        </thead>
                        <tbody>
                          {meetings.map((m) => (
                            <MeetingTableRow key={m.id} meeting={m} onClick={() => navigate(`/meeting/${m.id}`)} />
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </Card>
                )}
              </section>
            </>
          )}
        </div>
      </ScrollArea>
    </div>
  );
}

function StatCard({
  icon: Icon,
  label,
  value,
  tone = 'neutral',
  live = false,
}: {
  icon: React.ComponentType<{ size?: number; className?: string }>;
  label: string;
  value: number;
  tone?: 'neutral' | 'brand' | 'success' | 'warning' | 'danger';
  live?: boolean;
}) {
  const toneCls: Record<string, string> = {
    neutral: 'text-text-tertiary',
    brand: 'text-brand-500',
    success: 'text-success',
    warning: 'text-warning',
    danger: 'text-danger',
  };
  return (
    <Card className="p-4">
      <div className="flex items-center justify-between">
        <span className="text-xs text-text-tertiary">{label}</span>
        <Icon size={16} className={toneCls[tone]} />
      </div>
      <div className="mt-1 flex items-baseline gap-2">
        <span className={cn('text-2xl font-semibold', toneCls[tone])}>{value}</span>
        {live && <span className="relative flex h-1.5 w-1.5 translate-y-[-4px]"><span className="absolute h-1.5 w-1.5 animate-ping rounded-full bg-brand-500/40" /><span className="relative h-1.5 w-1.5 rounded-full bg-brand-500" /></span>}
      </div>
    </Card>
  );
}

function ConcurrencyGauge({ running, limit }: { running: number; limit: number }) {
  const pct = limit > 0 ? Math.min(100, Math.round((running / limit) * 100)) : 0;
  const nearLimit = limit > 0 && running >= limit;
  const highLoad = limit > 0 && running >= limit * 0.7;
  return (
    <div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-bg-tertiary">
        <div
          className={cn(
            'h-full rounded-full transition-all duration-300',
            nearLimit ? 'bg-danger' : highLoad ? 'bg-warning' : 'bg-[#335c8e]'
          )}
          style={{ width: `${pct}%` }}
        />
      </div>
      <div className="mt-2 flex items-center justify-between text-[11px] text-text-tertiary">
        <span>{limit > 0 ? `占用率 ${pct}%` : '未配置并发上限'}</span>
        {nearLimit && <span className="flex items-center gap-1 text-danger"><AlertCircleIcon size={12} />已达并发上限</span>}
      </div>
    </div>
  );
}

function ActiveMeetingCard({ meeting, onClick }: { meeting: Meeting; onClick: () => void }) {
  const statusConf = STATUS_CONFIG[meeting.status as MeetingStatus];
  const stageLabel = STAGE_LABELS[meeting.stage] || meeting.stage;
  return (
    <Card className="cursor-pointer transition-all hover:border-brand-500/30 hover:shadow-md" onClick={onClick}>
      <CardHeader className="pb-2">
        <div className="flex items-start justify-between gap-2">
          <div className="line-clamp-2 text-sm font-medium leading-snug text-text-primary">{meeting.title}</div>
          <Badge variant={statusConf.variant} className={cn('flex-shrink-0 text-[10px]', statusConf.color)}>
            {statusConf.label}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="pb-3">
        <div className="flex items-center justify-between text-[11px] text-text-tertiary">
          <span className="flex items-center gap-1">
            <ClockIcon size={12} />
            {formatRelativeTime(meeting.createdAt ?? meeting.created_at ?? Date.now())}
          </span>
          <span className="flex items-center gap-3">
            {meeting.agents?.length > 0 && (
              <span className="flex items-center gap-1"><UsersIcon size={12} />{meeting.agents.length}</span>
            )}
            {(meeting.messageCount ?? meeting.message_count ?? 0) > 0 && (
              <span className="flex items-center gap-1"><MessageSquareIcon size={12} />{meeting.messageCount ?? meeting.message_count}</span>
            )}
          </span>
        </div>
        {meeting.status === 'running' && (
          <div className="mt-2 flex items-center gap-1 text-[11px] text-brand-600">
            <span className="h-1.5 w-1.5 rounded-full bg-brand-500" />
            {stageLabel}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function MeetingTableRow({ meeting, onClick }: { meeting: Meeting; onClick: () => void }) {
  const statusConf = STATUS_CONFIG[meeting.status as MeetingStatus];
  const stageLabel = meeting.status === 'running' || meeting.status === 'paused' ? STAGE_LABELS[meeting.stage] || meeting.stage : '—';
  const agentCount = meeting.agents?.length ?? 0;
  const msgCount = meeting.messageCount ?? meeting.message_count ?? 0;
  return (
    <tr
      className="group cursor-pointer border-b border-border-soft last:border-0 transition-colors hover:bg-bg-secondary"
      onClick={onClick}
    >
      <td className="max-w-[320px] px-4 py-2.5">
        <span className="block truncate text-text-primary" title={meeting.title}>{truncate(meeting.title, 60)}</span>
      </td>
      <td className="px-4 py-2.5">
        <Badge variant={statusConf.variant} className={cn('text-[10px]', statusConf.color)}>
          {statusConf.label}
        </Badge>
      </td>
      <td className="px-4 py-2.5 text-xs text-text-secondary">{stageLabel}</td>
      <td className="px-4 py-2.5 text-xs text-text-secondary">{agentCount > 0 ? agentCount : '—'}</td>
      <td className="px-4 py-2.5 text-xs text-text-secondary">{msgCount > 0 ? msgCount : '—'}</td>
      <td className="px-4 py-2.5 text-xs text-text-tertiary">{formatRelativeTime(meeting.createdAt ?? meeting.created_at ?? Date.now())}</td>
      <td className="px-4 py-2.5 text-right">
        <ArrowRightIcon size={14} className="ml-auto text-text-tertiary opacity-0 transition-opacity group-hover:opacity-100" />
      </td>
    </tr>
  );
}