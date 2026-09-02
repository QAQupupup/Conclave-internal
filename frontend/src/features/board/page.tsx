/**
 * 议题看板列表页（/board）—— Bigfish 中后台列表页范式（问题 5 方案 B）。
 *
 * 创建/编辑表单已拆分至独立页面 /board/new（new-page.tsx），
 * 本页只负责：状态页签筛选 + 关键词搜索 + 表格式列表 + 分页 + 行操作（启动/复用/删除）。
 */
import * as React from 'react';
import { useNavigate } from 'react-router';
import { useMeetings, useDeleteMeeting, useRunMeeting } from '@/hooks/use-meetings';
import { useQueryClient } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { ConfirmDialog } from '@/components/ui/confirm-dialog';
import { cn, formatRelativeTime, truncate } from '@/lib/utils';
import type { Meeting, MeetingStatus } from '@/types';
import { STAGE_LABELS } from '@/lib/constants';
import { toast } from '@/hooks/use-toast';
import {
  Logo,
  PlusIcon,
  SearchIcon,
  ClockIcon,
  UsersIcon,
  MessageSquareIcon,
  SpinnerIcon,
  TrashIcon,
  CopyIcon,
  PlayIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  XIcon,
} from '@/components/ui/svg-icons';

const STATUS_CONFIG: Record<MeetingStatus, { label: string; variant: 'default' | 'secondary' | 'outline' | 'destructive'; color: string }> = {
  // pending 仅用于展示层：草稿会议（status=running 但无运行任务）映射为此态
  pending: { label: '待启动', variant: 'outline', color: 'text-text-tertiary' },
  running: { label: '运行中', variant: 'default', color: 'text-brand-500' },
  paused: { label: '已暂停', variant: 'secondary', color: 'text-warning' },
  done: { label: '已完成', variant: 'secondary', color: 'text-success' },
  error: { label: '出错', variant: 'destructive', color: 'text-danger' },
  aborted: { label: '已终止', variant: 'secondary', color: 'text-text-tertiary' },
};

/**
 * 草稿判定：后端创建会议默认 status=running（无 pending 枚举），
 * "保存草稿"只创建不调用 /run，因此 is_running=false 的 running 会议即草稿。
 */
function isDraftMeeting(m: Meeting): boolean {
  return m.status === 'running' && m.metadata?.is_running === false;
}

/** 状态页签：值为后端 status 参数（逗号分隔多值 OR），空串表示不过滤 */
const STATUS_TABS: Array<{ key: string; label: string; statuses: string }> = [
  { key: 'all', label: '全部', statuses: '' },
  { key: 'active', label: '进行中', statuses: 'running,paused' },
  { key: 'done', label: '已完成', statuses: 'done' },
  { key: 'abnormal', label: '异常', statuses: 'error,aborted' },
];

const PAGE_SIZE = 20;
/** 搜索防抖间隔（毫秒） */
const SEARCH_DEBOUNCE_MS = 300;

export default function BoardPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  // 筛选状态
  const [tabKey, setTabKey] = React.useState('all');
  const [searchInput, setSearchInput] = React.useState('');
  const [q, setQ] = React.useState('');
  const [page, setPage] = React.useState(1);

  // 搜索防抖
  React.useEffect(() => {
    const t = window.setTimeout(() => setQ(searchInput.trim()), SEARCH_DEBOUNCE_MS);
    return () => window.clearTimeout(t);
  }, [searchInput]);

  // 筛选条件变化时回到第一页
  const activeTab = STATUS_TABS.find((t) => t.key === tabKey) ?? STATUS_TABS[0];
  React.useEffect(() => {
    setPage(1);
  }, [tabKey, q]);

  const { data, isLoading, isFetching } = useMeetings({
    page,
    pageSize: PAGE_SIZE,
    status: activeTab.statuses || undefined,
    q: q || undefined,
  });
  const meetings = Array.isArray(data?.items) ? data.items : [];
  const total = data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  // 删除导致当前页为空时回退一页
  React.useEffect(() => {
    if (!isLoading && meetings.length === 0 && page > totalPages) setPage(totalPages);
  }, [isLoading, meetings.length, page, totalPages]);

  // 行操作
  const runMeeting = useRunMeeting();
  const deleteMeeting = useDeleteMeeting();
  const [startingId, setStartingId] = React.useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = React.useState<{ id: string; title: string } | null>(null);

  const handleStartPending = async (e: React.MouseEvent, meeting: Meeting) => {
    e.stopPropagation();
    if (startingId) return;
    setStartingId(meeting.id);
    try {
      await runMeeting.mutateAsync(meeting.id);
      toast({ title: '讨论已启动', description: truncate(meeting.title, 50) });
      queryClient.invalidateQueries({ queryKey: ['meetings'] });
      navigate(`/meeting/${meeting.id}`);
    } catch (err: unknown) {
      toast({ title: '启动失败', description: (err as Error).message, variant: 'error' });
    } finally {
      setStartingId(null);
    }
  };

  const handleDelete = (e: React.MouseEvent, meetingId: string, title: string) => {
    e.stopPropagation();
    setDeleteTarget({ id: meetingId, title });
  };

  const confirmDelete = async () => {
    if (!deleteTarget) return;
    try {
      await deleteMeeting.mutateAsync(deleteTarget.id);
      toast({ title: '已删除', description: '讨论已删除' });
      queryClient.invalidateQueries({ queryKey: ['meetings'] });
    } catch (err: unknown) {
      toast({ title: '删除失败', description: (err as Error).message, variant: 'error' });
    } finally {
      setDeleteTarget(null);
    }
  };

  const hasFilters = tabKey !== 'all' || q !== '';

  return (
    <div className="mx-auto max-w-5xl px-8 pt-6 pb-8">
      {/* 页头：标题 + 主操作 */}
      <div className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center">
            <Logo size={36} />
          </div>
          <div>
            <h1 className="text-xl font-semibold text-text-primary">Conclave 智库</h1>
            <p className="text-sm text-text-tertiary">让多 Agent 团队协同探索复杂议题</p>
          </div>
        </div>
        <Button size="sm" onClick={() => navigate('/board/new')} className="gap-1">
          <PlusIcon size={14} />
          新建议题
        </Button>
      </div>

      {/* 筛选栏：状态页签 + 搜索 */}
      <div className="mt-5 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-1" role="tablist" aria-label="按状态筛选">
          {STATUS_TABS.map((t) => (
            <button
              key={t.key}
              type="button"
              role="tab"
              aria-selected={tabKey === t.key}
              onClick={() => setTabKey(t.key)}
              className={cn(
                'rounded-md px-2.5 py-1.5 text-xs transition-colors',
                tabKey === t.key
                  ? 'bg-brand-soft font-medium text-brand-600'
                  : 'text-text-secondary hover:bg-bg-tertiary hover:text-text-primary',
              )}
            >
              {t.label}
            </button>
          ))}
        </div>
        <div className="relative w-60">
          <SearchIcon size={13} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-text-tertiary" />
          <input
            type="text"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            placeholder="搜索议题关键词..."
            aria-label="搜索议题"
            className="h-8 w-full rounded-md border border-border-default bg-bg-primary pl-8 pr-7 text-xs text-text-primary outline-none transition-colors placeholder:text-text-tertiary focus:border-brand-500/40"
          />
          {searchInput && (
            <button
              type="button"
              onClick={() => setSearchInput('')}
              className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-0.5 text-text-tertiary hover:text-text-secondary"
              aria-label="清空搜索"
            >
              <XIcon size={12} />
            </button>
          )}
        </div>
      </div>

      {/* 列表 */}
      <div className="mt-3 overflow-hidden rounded-lg border border-border-soft bg-bg-primary">
        {/* 表头 */}
        <div className="grid grid-cols-[minmax(0,1fr)_88px_100px_112px] items-center gap-3 border-b border-border-soft bg-bg-secondary/50 px-4 py-2 text-[11px] text-text-tertiary">
          <span>议题</span>
          <span>状态</span>
          <span>创建时间</span>
          <span className="text-right">操作</span>
        </div>

        {isLoading ? (
          <div className="flex items-center justify-center py-16">
            <SpinnerIcon size={20} className="animate-spin text-text-tertiary" />
          </div>
        ) : meetings.length === 0 ? (
          <div className="py-16 text-center">
            <p className="text-sm text-text-tertiary">
              {hasFilters ? '未找到匹配的讨论' : '暂无讨论，发起一个新议题开始吧'}
            </p>
            {hasFilters ? (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="mt-3 text-xs"
                onClick={() => {
                  setTabKey('all');
                  setSearchInput('');
                }}
              >
                清除筛选条件
              </Button>
            ) : (
              <Button type="button" variant="outline" size="sm" className="mt-3 gap-1 text-xs" onClick={() => navigate('/board/new')}>
                <PlusIcon size={12} />
                新建议题
              </Button>
            )}
          </div>
        ) : (
          <ul className={cn('divide-y divide-border-soft', isFetching && 'opacity-60 transition-opacity')}>
            {meetings.map((m) => (
              <MeetingRow
                key={m.id}
                meeting={m}
                isStarting={startingId === m.id}
                onClick={() => navigate(`/meeting/${m.id}`)}
                onStart={(e) => handleStartPending(e, m)}
                onReuse={(e) => {
                  e.stopPropagation();
                  navigate(`/board/new?from=${m.id}`);
                }}
                onDelete={(e) => handleDelete(e, m.id, m.title)}
              />
            ))}
          </ul>
        )}
      </div>

      {/* 分页 */}
      {total > 0 && (
        <div className="mt-3 flex items-center justify-between text-[11px] text-text-tertiary">
          <span>
            共 {total} 条 · 第 {page} / {totalPages} 页
          </span>
          <div className="flex items-center gap-1">
            <button
              type="button"
              disabled={page <= 1 || isFetching}
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              className="rounded-md border border-border-default p-1.5 transition-colors hover:bg-bg-tertiary disabled:cursor-not-allowed disabled:opacity-40"
              aria-label="上一页"
            >
              <ChevronLeftIcon size={13} />
            </button>
            <button
              type="button"
              disabled={page >= totalPages || isFetching}
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              className="rounded-md border border-border-default p-1.5 transition-colors hover:bg-bg-tertiary disabled:cursor-not-allowed disabled:opacity-40"
              aria-label="下一页"
            >
              <ChevronRightIcon size={13} />
            </button>
          </div>
        </div>
      )}

      <ConfirmDialog
        open={!!deleteTarget}
        title="删除讨论"
        description={`确定要删除「${truncate(deleteTarget?.title || '', 30)}」吗？`}
        destructive={true}
        confirmText="删除"
        onConfirm={confirmDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  );
}

/** 列表行：议题（标题 + 内联标签 + 元信息）| 状态 | 时间 | 悬停操作 */
function MeetingRow({
  meeting,
  isStarting,
  onClick,
  onStart,
  onReuse,
  onDelete,
}: {
  meeting: Meeting;
  isStarting: boolean;
  onClick: () => void;
  onStart: (e: React.MouseEvent) => void;
  onReuse: (e: React.MouseEvent) => void;
  onDelete: (e: React.MouseEvent) => void;
}) {
  const draft = isDraftMeeting(meeting);
  const displayStatus: MeetingStatus = draft ? 'pending' : (meeting.status as MeetingStatus);
  const statusConf = STATUS_CONFIG[displayStatus] ?? STATUS_CONFIG.pending;
  const tags = Array.isArray(meeting.metadata?.tags) ? (meeting.metadata!.tags as string[]) : [];
  const messageCount = meeting.messageCount ?? meeting.message_count;

  return (
    <li
      className="group grid cursor-pointer grid-cols-[minmax(0,1fr)_88px_100px_112px] items-center gap-3 px-4 py-2.5 transition-colors hover:bg-bg-secondary/60"
      onClick={onClick}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === 'Enter') onClick();
      }}
      aria-label={`进入讨论：${meeting.title}`}
    >
      {/* 议题：标题 + 内联标签 + 元信息 */}
      <div className="min-w-0">
        <div className="flex min-w-0 items-center gap-2">
          <span className="truncate text-sm text-text-primary">{meeting.title}</span>
          {tags.map((t) => (
            <span key={t} className="flex-shrink-0 rounded bg-bg-tertiary px-1.5 py-0.5 text-[10px] text-text-tertiary">
              {t}
            </span>
          ))}
        </div>
        <div className="mt-0.5 flex items-center gap-3 text-[11px] text-text-tertiary">
          {meeting.status === 'running' && !draft && (
            <span className="text-brand-500">{STAGE_LABELS[meeting.stage] || meeting.stage}</span>
          )}
          {draft && <span>已创建，尚未启动</span>}
          {messageCount !== undefined && (
            <span className="flex items-center gap-1">
              <MessageSquareIcon size={11} />
              {messageCount}
            </span>
          )}
          {meeting.agents?.length > 0 && (
            <span className="flex items-center gap-1">
              <UsersIcon size={11} />
              {meeting.agents.length}
            </span>
          )}
        </div>
      </div>

      {/* 状态 */}
      <div>
        <Badge variant={statusConf.variant} className={cn('text-[10px]', statusConf.color)}>
          {statusConf.label}
        </Badge>
      </div>

      {/* 创建时间 */}
      <span className="flex items-center gap-1 text-[11px] text-text-tertiary">
        <ClockIcon size={11} />
        {formatRelativeTime(meeting.createdAt ?? meeting.created_at ?? Date.now())}
      </span>

      {/* 操作：悬停显示（各按钮 handler 内部已 stopPropagation，包裹层不再挂 onClick，
          避免非交互元素绑定点击触发 jsx-a11y 告警） */}
      <div className="flex items-center justify-end gap-0.5 opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
        {draft && (
          <button
            type="button"
            onClick={onStart}
            disabled={isStarting}
            className="rounded p-1.5 text-text-tertiary transition-colors hover:bg-brand-soft hover:text-brand-600 disabled:opacity-50"
            title="启动"
            aria-label="启动讨论"
          >
            {isStarting ? <SpinnerIcon size={13} className="animate-spin" /> : <PlayIcon size={13} />}
          </button>
        )}
        <button
          type="button"
          onClick={onReuse}
          className="rounded p-1.5 text-text-tertiary transition-colors hover:bg-bg-tertiary hover:text-text-primary"
          title="复用议题"
          aria-label="复用议题"
        >
          <CopyIcon size={13} />
        </button>
        <button
          type="button"
          onClick={onDelete}
          className="rounded p-1.5 text-text-tertiary transition-colors hover:bg-danger-bg hover:text-danger"
          title="删除"
          aria-label="删除讨论"
        >
          <TrashIcon size={13} />
        </button>
      </div>
    </li>
  );
}
