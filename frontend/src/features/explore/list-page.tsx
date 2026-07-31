import * as React from 'react';
import { useNavigate } from 'react-router';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { ScrollArea } from '@/components/ui/scroll-area';
import {
  SparklesIcon,
  SearchIcon,
  PlusIcon,
  ClockIcon,
  CheckCircleIcon,
  PlayCircleIcon,
  MessageSquareIcon,
  UsersIcon,
} from '@/components/ui/svg-icons';
import { STAGE_LABELS } from '@/lib/constants';
import type { Meeting } from '@/types';

const STATUS_CONFIG: Record<string, { label: string; className: string; icon: React.ComponentType<{ size?: number; className?: string }> }> = {
  running: { label: '进行中', className: 'bg-stage-running/15 text-stage-running', icon: PlayCircleIcon },
  paused: { label: '已暂停', className: 'bg-warning/15 text-warning', icon: ClockIcon },
  done: { label: '已完成', className: 'bg-success/15 text-success', icon: CheckCircleIcon },
  error: { label: '已失败', className: 'bg-danger/15 text-danger', icon: ClockIcon },
  aborted: { label: '已终止', className: 'bg-danger/15 text-danger', icon: ClockIcon },
  pending: { label: '等待中', className: 'bg-bg-tertiary text-text-secondary', icon: ClockIcon },
};

export default function ExploreListPage() {
  const navigate = useNavigate();
  const [searchQuery, setSearchQuery] = React.useState('');
  const [statusFilter, setStatusFilter] = React.useState<string>('all');

  const { data, isLoading } = useQuery({
    queryKey: ['meetings', 'explore'],
    queryFn: () => api.get<{ items: Meeting[]; meetings?: Meeting[] }>('/meetings?limit=50'),
    retry: false,
  });

  const meetings = React.useMemo(() => {
    const items = data?.meetings || data?.items || [];
    let filtered = items;
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      filtered = filtered.filter(
        (m: Meeting) =>
          m.title.toLowerCase().includes(q) ||
          (m.description || '').toLowerCase().includes(q)
      );
    }
    if (statusFilter !== 'all') {
      filtered = filtered.filter((m: Meeting) => m.status === statusFilter);
    }
    return filtered.sort((a: Meeting, b: Meeting) =>
      (b.createdAt || 0) - (a.createdAt || 0)
    );
  }, [data, searchQuery, statusFilter]);

  const formatTime = (timestamp?: number) => {
    if (!timestamp) return '--';
    const d = new Date(timestamp);
    const now = new Date();
    const diff = now.getTime() - d.getTime();
    const hours = Math.floor(diff / 3600000);
    if (hours < 1) return '刚刚';
    if (hours < 24) return `${hours} 小时前`;
    const days = Math.floor(hours / 24);
    if (days < 7) return `${days} 天前`;
    return d.toLocaleDateString('zh-CN');
  };

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex-shrink-0 border-b border-border-soft bg-bg-primary p-4">
        <div className="mb-3 flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold text-text-primary flex items-center gap-2">
              <SparklesIcon size={20} className="text-brand-500" />
              探索
            </h2>
            <p className="text-xs text-text-tertiary mt-0.5">浏览所有会议探索记录和讨论脉络</p>
          </div>
          <Button size="sm" onClick={() => navigate('/board')}>
            <PlusIcon size={14} />
            新会议
          </Button>
        </div>
        <div className="flex items-center gap-2">
          <div className="relative flex-1 max-w-md">
            <SearchIcon size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-text-tertiary" />
            <Input
              placeholder="搜索会议主题..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="pl-8 h-8 text-xs"
            />
          </div>
          <div className="flex gap-1">
            {[
              { key: 'all', label: '全部' },
              { key: 'running', label: '进行中' },
              { key: 'done', label: '已完成' },
            ].map((f) => (
              <button
                key={f.key}
                onClick={() => setStatusFilter(f.key)}
                className={`px-2.5 py-1 rounded text-xs transition-colors ${
                  statusFilter === f.key
                    ? 'bg-brand-soft text-brand-600 font-medium'
                    : 'text-text-tertiary hover:bg-bg-tertiary hover:text-text-secondary'
                }`}
              >
                {f.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Timeline */}
      <ScrollArea className="flex-1">
        <div className="p-4">
          {isLoading ? (
            <div className="flex flex-col items-center justify-center py-20 gap-2 text-text-tertiary">
              <div className="h-6 w-6 animate-spin rounded-full border-2 border-border-default border-t-brand-500" />
              <span className="text-xs">加载中...</span>
            </div>
          ) : meetings.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-20 gap-3 text-text-tertiary">
              <SparklesIcon size={40} className="opacity-30" />
              <p className="text-sm">暂无探索记录</p>
              <Button size="sm" variant="outline" onClick={() => navigate('/board')}>
                开始第一个会议
              </Button>
            </div>
          ) : (
            <div className="relative max-w-3xl mx-auto">
              {/* Timeline line */}
              <div className="absolute left-6 top-0 bottom-0 w-px bg-border-soft" />

              <div className="space-y-3">
                {meetings.map((meeting: Meeting) => {
                  const statusCfg = STATUS_CONFIG[meeting.status] || STATUS_CONFIG.pending;
                  const StatusIcon = statusCfg.icon;
                  return (
                    <Card
                      key={meeting.id}
                      className="relative ml-10 cursor-pointer hover:border-border-default hover:shadow-sm transition-all group"
                      onClick={() => navigate(`/explore/${meeting.id}`)}
                    >
                      {/* Timeline dot */}
                      <div className="absolute -left-10 top-4 flex h-5 w-5 items-center justify-center rounded-full bg-bg-primary border-2 border-border-soft group-hover:border-brand-400 transition-colors">
                        <div className={`h-2 w-2 rounded-full ${
                          meeting.status === 'running' ? 'bg-stage-running animate-pulse' :
                          meeting.status === 'done' ? 'bg-success' :
                          meeting.status === 'paused' ? 'bg-warning' :
                          meeting.status === 'error' || meeting.status === 'aborted' ? 'bg-danger' : 'bg-text-tertiary'
                        }`} />
                      </div>

                      <CardContent className="p-3.5">
                        <div className="flex items-start justify-between gap-3 mb-2">
                          <div className="flex-1 min-w-0">
                            <h3 className="text-sm font-medium text-text-primary group-hover:text-brand-600 transition-colors truncate">
                              {meeting.title}
                            </h3>
                            {meeting.description && (
                              <p className="text-xs text-text-tertiary mt-0.5 line-clamp-1">{meeting.description}</p>
                            )}
                          </div>
                          <Badge className={`${statusCfg.className} flex-shrink-0 text-[10px] px-1.5 py-0.5`}>
                            <StatusIcon size={10} className="mr-0.5" />
                            {statusCfg.label}
                          </Badge>
                        </div>

                        <div className="flex items-center gap-3 text-[11px] text-text-tertiary">
                          <span className="flex items-center gap-1">
                            <ClockIcon size={10} />
                            {formatTime(meeting.createdAt)}
                          </span>
                          {meeting.stage && (
                            <span className="flex items-center gap-1">
                              <PlayCircleIcon size={10} />
                              {STAGE_LABELS[meeting.stage] || meeting.stage}
                            </span>
                          )}
                          <span className="flex items-center gap-1">
                            <MessageSquareIcon size={10} />
                            {meeting.messageCount ?? '—'}
                          </span>
                          <span className="flex items-center gap-1">
                            <UsersIcon size={10} />
                            {meeting.agents?.length ?? '—'} Agent
                          </span>
                        </div>
                      </CardContent>
                    </Card>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      </ScrollArea>
    </div>
  );
}
