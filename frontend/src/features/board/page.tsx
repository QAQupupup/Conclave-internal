import * as React from 'react';
import { useNavigate } from 'react-router';
import { useMeetings, useStartMeeting, useDeleteMeeting } from '@/hooks/use-meetings';
import { useQueryClient } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { ConfirmDialog } from '@/components/ui/confirm-dialog';
import { cn, formatRelativeTime, truncate } from '@/lib/utils';
import type { MeetingStatus } from '@/types';
import { STAGE_LABELS } from '@/lib/constants';
import { toast } from '@/hooks/use-toast';
import { api } from '@/lib/api';
import {
  Logo,
  PlusIcon,
  PlayIcon,
  ClockIcon,
  UsersIcon,
  MessageSquareIcon,
  SpinnerIcon,
  ArrowRightIcon,
  TrashIcon,
  WandIcon,
  UndoIcon,
} from '@/components/ui/svg-icons';

const STATUS_CONFIG: Record<MeetingStatus, { label: string; variant: 'default' | 'secondary' | 'outline' | 'destructive'; color: string }> = {
  pending: { label: '待开始', variant: 'outline', color: 'text-text-tertiary' },
  running: { label: '运行中', variant: 'default', color: 'text-brand-500' },
  paused: { label: '已暂停', variant: 'secondary', color: 'text-warning' },
  done: { label: '已完成', variant: 'secondary', color: 'text-success' },
  error: { label: '出错', variant: 'destructive', color: 'text-danger' },
  aborted: { label: '已终止', variant: 'secondary', color: 'text-text-tertiary' },
};

export default function BoardPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [topic, setTopic] = React.useState('');
  const [topicHistory, setTopicHistory] = React.useState<string[]>([]);
  const [isPolishing, setIsPolishing] = React.useState(false);
  const [showNewForm, setShowNewForm] = React.useState(false);
  const textareaRef = React.useRef<HTMLTextAreaElement>(null);
  const { data: meetingsData, isLoading } = useMeetings({ pageSize: 50 });
  const startMeeting = useStartMeeting();
  const deleteMeeting = useDeleteMeeting();
  const [deleteTarget, setDeleteTarget] = React.useState<{ id: string; title: string } | null>(null);

  const meetings = Array.isArray(meetingsData?.items) ? meetingsData.items : [];
  const activeMeetings = meetings.filter((m) => m.status === 'running' || m.status === 'paused');
  const pastMeetings = meetings.filter((m) => m.status === 'done' || m.status === 'error' || m.status === 'aborted' || m.status === 'pending');

  // Auto-resize textarea
  React.useEffect(() => {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.style.height = 'auto';
    ta.style.height = Math.min(ta.scrollHeight, 200) + 'px';
  }, [topic, showNewForm]);

  const handlePolish = async () => {
    if (!topic.trim() || isPolishing) return;
    setIsPolishing(true);
    try {
      const res = await api.post<{ polished: string }>('/meetings/polish-topic', { text: topic });
      if (res.polished && res.polished !== topic) {
        setTopicHistory((prev) => [...prev, topic]);
        setTopic(res.polished);
        toast({ title: '已润色', description: '议题描述已优化' });
      }
    } catch (e: any) {
      toast({ title: '润色失败', description: e.message, variant: 'error' });
    } finally {
      setIsPolishing(false);
    }
  };

  const handleUndo = () => {
    if (topicHistory.length === 0) return;
    const prev = topicHistory[topicHistory.length - 1];
    setTopic(prev);
    setTopicHistory((h) => h.slice(0, -1));
  };

  const handleStart = async (e?: React.FormEvent) => {
    e?.preventDefault();
    if (!topic.trim()) return;
    try {
      const res = await startMeeting.mutateAsync({ topic: topic.trim() });
      toast({ title: '讨论已启动', description: truncate(topic, 50) });
      setTopic('');
      setTopicHistory([]);
      setShowNewForm(false);
      navigate(`/explore/${res.meeting_id}`);
    } catch (e: any) {
      toast({ title: '启动失败', description: e.message, variant: 'error' });
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
    } catch (err: any) {
      toast({ title: '删除失败', description: err.message, variant: 'error' });
    } finally {
      setDeleteTarget(null);
    }
  };

  return (
    <div className="mx-auto max-w-5xl pt-6 px-8 pb-8">
      {/* Hero / New meeting */}
      <section className="mb-8">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center">
            <Logo size={36} />
          </div>
          <div>
            <h1 className="text-xl font-semibold text-text-primary">Conclave 智库</h1>
            <p className="text-sm text-text-tertiary">让多 Agent 团队协同探索复杂议题</p>
          </div>
        </div>

        <div className="mt-5">
          {showNewForm ? (
            <form onSubmit={handleStart} className="rounded-lg border border-border-default bg-bg-primary p-4 shadow-sm">
              <Textarea
                ref={textareaRef}
                value={topic}
                onChange={(e) => setTopic(e.target.value)}
                placeholder="描述你想讨论的议题或问题...&#10;例如：分析微服务架构中服务间通信的最佳实践，对比 gRPC 和 REST 的适用场景"
                className="min-h-[96px] text-[15px] leading-relaxed"
                autoFocus
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
                    e.preventDefault();
                    handleStart();
                  }
                }}
              />
              <div className="mt-3 flex items-center justify-between">
                <div className="flex items-center gap-1">
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={handlePolish}
                    disabled={!topic.trim() || isPolishing}
                    className="h-7 gap-1 text-xs"
                  >
                    {isPolishing ? (
                      <SpinnerIcon size={12} className="animate-spin" />
                    ) : (
                      <WandIcon size={12} />
                    )}
                    AI 润色
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={handleUndo}
                    disabled={topicHistory.length === 0}
                    className="h-7 gap-1 text-xs"
                  >
                    <UndoIcon size={12} />
                    撤回
                  </Button>
                  <span className="ml-2 text-[11px] text-text-tertiary">
                    {topic.length} 字
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-[11px] text-text-tertiary hidden sm:inline">Ctrl+Enter 启动</span>
                  <Button type="button" variant="ghost" size="sm" onClick={() => { setShowNewForm(false); setTopic(''); setTopicHistory([]); }}>
                    取消
                  </Button>
                  <Button type="submit" size="sm" disabled={!topic.trim() || startMeeting.isPending}>
                    {startMeeting.isPending ? (
                      <SpinnerIcon size={12} className="mr-1 animate-spin" />
                    ) : (
                      <PlayIcon size={12} className="mr-1" />
                    )}
                    开始讨论
                  </Button>
                </div>
              </div>
            </form>
          ) : (
            <button
              onClick={() => setShowNewForm(true)}
              className="group flex w-full items-center gap-3 rounded-lg border border-dashed border-border-default bg-bg-primary/50 px-4 py-3 text-left text-sm text-text-tertiary transition-all hover:border-brand-500/40 hover:bg-brand-soft hover:text-text-secondary"
            >
              <PlusIcon size={16} />
              <span className="flex-1">启动一个新的探索讨论...</span>
              <span className="text-xs text-text-tertiary/60 group-hover:text-brand-500">Ctrl+K 快捷启动</span>
            </button>
          )}
        </div>
      </section>

      {/* Active meetings */}
      {activeMeetings.length > 0 && (
        <section className="mb-8">
          <h2 className="mb-3 flex items-center gap-2 text-sm font-medium text-text-primary">
            <span className="relative flex h-2 w-2 items-center justify-center">
              <span className="absolute h-2 w-2 animate-ping rounded-full bg-brand-500/50" />
              <span className="relative h-1.5 w-1.5 rounded-full bg-brand-500" />
            </span>
            进行中的讨论
          </h2>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {activeMeetings.map((m) => (
              <MeetingCard key={m.id} meeting={m} onClick={() => navigate(`/explore/${m.id}`)} />
            ))}
          </div>
        </section>
      )}

      {/* Past meetings */}
      <section>
        <h2 className="mb-3 text-sm font-medium text-text-primary">历史讨论</h2>
        {isLoading ? (
          <div className="flex items-center justify-center py-12">
            <SpinnerIcon size={20} className="animate-spin text-text-tertiary" />
          </div>
        ) : pastMeetings.length === 0 ? (
          <div className="rounded-lg border border-dashed border-border-soft py-12 text-center text-sm text-text-tertiary">
            暂无历史讨论，启动一个新讨论开始吧
          </div>
        ) : (
          <div className="space-y-1">
            {pastMeetings.map((m) => (
              <MeetingRow
                key={m.id}
                meeting={m}
                onClick={() => navigate(`/explore/${m.id}`)}
                onDelete={(e) => handleDelete(e, m.id, m.title)}
              />
            ))}
          </div>
        )}
      </section>

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

function MeetingCard({ meeting, onClick }: { meeting: any; onClick: () => void }) {
  const statusConf = STATUS_CONFIG[meeting.status as MeetingStatus];
  return (
    <Card
      className="cursor-pointer transition-all hover:border-brand-500/30 hover:shadow-md"
      onClick={onClick}
    >
      <CardHeader className="pb-2">
        <div className="flex items-start justify-between gap-2">
          <CardTitle className="line-clamp-2 text-sm font-medium leading-snug">{meeting.title}</CardTitle>
          <Badge variant={statusConf.variant} className={cn('flex-shrink-0 text-[10px]', statusConf.color)}>
            {statusConf.label}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="pb-3">
        <div className="flex items-center gap-3 text-[11px] text-text-tertiary">
          <span className="flex items-center gap-1">
            <ClockIcon size={12} />
            {formatRelativeTime(meeting.createdAt || meeting.created_at)}
          </span>
          {(meeting.messageCount ?? meeting.message_count) !== undefined && (
            <span className="flex items-center gap-1">
              <MessageSquareIcon size={12} />
              {meeting.messageCount ?? meeting.message_count}
            </span>
          )}
          {meeting.agents?.length > 0 && (
            <span className="flex items-center gap-1">
              <UsersIcon size={12} />
              {meeting.agents.length}
            </span>
          )}
        </div>
        {meeting.status === 'running' && (
          <div className="mt-2 text-[11px] text-brand-500">
            {STAGE_LABELS[meeting.stage] || meeting.stage}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function MeetingRow({ meeting, onClick, onDelete }: { meeting: any; onClick: () => void; onDelete: (e: React.MouseEvent) => void }) {
  const statusConf = STATUS_CONFIG[meeting.status as MeetingStatus];
  return (
    <div className="group flex w-full items-center gap-3 rounded-lg border border-transparent bg-bg-primary px-4 py-2.5 transition-all hover:border-border-default hover:shadow-sm">
      <button onClick={onClick} className="flex min-w-0 flex-1 items-center gap-3 text-left">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="truncate text-sm text-text-primary">{meeting.title}</span>
            <Badge variant={statusConf.variant} className={cn('flex-shrink-0 text-[10px]', statusConf.color)}>
              {statusConf.label}
            </Badge>
          </div>
          <div className="mt-0.5 flex items-center gap-3 text-[11px] text-text-tertiary">
            <span>{formatRelativeTime(meeting.createdAt || meeting.created_at)}</span>
            {(meeting.messageCount ?? meeting.message_count) !== undefined && (
              <span>{meeting.messageCount ?? meeting.message_count} 条消息</span>
            )}
          </div>
        </div>
        <ArrowRightIcon size={16} className="flex-shrink-0 text-text-tertiary opacity-0 transition-opacity group-hover:opacity-100" />
      </button>
      <button
        onClick={onDelete}
        className="rounded p-1 text-text-tertiary opacity-0 transition-all hover:bg-danger-bg hover:text-danger group-hover:opacity-100"
        title="删除"
        aria-label="删除"
      >
        <TrashIcon size={14} />
      </button>
    </div>
  );
}
