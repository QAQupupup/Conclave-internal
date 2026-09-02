import * as React from 'react';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router';
import { api } from '@/lib/api';
import { formatRelativeTime, cn } from '@/lib/utils';
import { toast } from '@/hooks/use-toast';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  DropdownMenuLabel,
  DropdownMenuSeparator,
} from '@/components/ui/dropdown-menu';
import {
  AgentAvatar,
  SearchIcon,
  DownloadIcon,
  FileIcon,
  TagIcon,
  DocIcon,
} from '@/components/ui/svg-icons';
import { Markdown } from '@/components/ui/markdown';
import { ReportLayoutRenderer, type LayoutSpec } from '@/components/report/report-block-renderer';

// ===== 类型定义 =====

interface AgentLite {
  id: string;
  name: string;
  role?: string;
}

interface MeetingReport {
  id: string;
  title: string;
  status: string;
  createdAt: number;
  startedAt?: number;
  completedAt?: number;
  summary?: string;
  tags?: string[];
  agents?: AgentLite[];
  stage?: string;
  deliverableType?: string;
}

interface Attachment {
  filename: string;
  size: number;
  created_at: number | string;
}

// ===== 响应归一化工具 =====

function toTimestamp(v: unknown): number {
  if (typeof v === 'number') return v;
  if (typeof v === 'string') {
    const parsed = Date.parse(v);
    if (!Number.isNaN(parsed)) return parsed;
  }
  return Date.now();
}

function normalizeMeeting(raw: Record<string, unknown>): MeetingReport {
  return {
    id: String(raw.id ?? ''),
    title: String(raw.title ?? '未命名讨论'),
    status: String(raw.status ?? ''),
    createdAt: toTimestamp(raw.created_at ?? raw.createdAt ?? raw.created),
    startedAt: raw.started_at != null || raw.startedAt != null
      ? toTimestamp(raw.started_at ?? raw.startedAt)
      : undefined,
    completedAt: raw.completed_at != null || raw.completedAt != null || raw.ended_at != null || raw.endedAt != null
      ? toTimestamp(raw.completed_at ?? raw.completedAt ?? raw.ended_at ?? raw.endedAt)
      : undefined,
    summary: raw.summary != null ? String(raw.summary) : undefined,
    tags: Array.isArray(raw.tags) ? (raw.tags as string[]) : undefined,
    agents: Array.isArray(raw.agents)
      ? (raw.agents as Record<string, unknown>[]).map((a) => ({
          id: String(a.id ?? ''),
          name: String(a.name ?? 'Agent'),
          role: a.role != null ? String(a.role) : undefined,
        }))
      : undefined,
    stage: raw.stage != null ? String(raw.stage) : undefined,
    deliverableType: raw.deliverable_type != null
      ? String(raw.deliverable_type)
      : raw.deliverableType != null
        ? String(raw.deliverableType)
        : undefined,
  };
}

function extractMeetings(data: unknown): MeetingReport[] {
  if (Array.isArray(data)) return data.map((m) => normalizeMeeting(m as Record<string, unknown>));
  if (data && typeof data === 'object') {
    const obj = data as Record<string, unknown>;
    if (Array.isArray(obj.meetings)) return obj.meetings.map((m) => normalizeMeeting(m as Record<string, unknown>));
    if (Array.isArray(obj.items)) return obj.items.map((m) => normalizeMeeting(m as Record<string, unknown>));
  }
  return [];
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

// ===== 查询键 =====

const reportKeys = {
  all: ['reports'] as const,
  list: () => [...reportKeys.all, 'list'] as const,
  summary: (id: string) => [...reportKeys.all, 'summary', id] as const,
  attachments: (id: string) => [...reportKeys.all, 'attachments', id] as const,
  layout: (id: string) => [...reportKeys.all, 'layout', id] as const,
};

// ===== Skeleton 组件 =====

function MeetingCardSkeleton() {
  return (
    <div className="flex items-start gap-3 px-4 py-4">
      <Skeleton className="h-7 w-7 rounded-full" />
      <div className="min-w-0 flex-1 space-y-2">
        <Skeleton className="h-4 w-3/5 rounded" />
        <Skeleton className="h-3 w-2/5 rounded" />
        <Skeleton className="h-3 w-4/5 rounded" />
      </div>
      <Skeleton className="h-7 w-16 rounded-md" />
    </div>
  );
}

// ===== Agent 头像组 =====

function AgentAvatarGroup({ agents }: { agents?: AgentLite[] }) {
  if (!agents || agents.length === 0) return null;
  const visible = agents.slice(0, 5);
  const remaining = agents.length - visible.length;

  return (
    <div className="flex items-center -space-x-1.5">
      {visible.map((agent) => (
        <AgentAvatar
          key={agent.id}
          agentId={agent.id}
          agentName={agent.name}
          role={agent.role}
          size={22}
          className="ring-2 ring-bg-primary"
        />
      ))}
      {remaining > 0 && (
        <div className="flex h-[22px] w-[22px] items-center justify-center rounded-full bg-bg-tertiary ring-2 ring-bg-primary text-[9px] font-medium text-text-tertiary">
          +{remaining}
        </div>
      )}
    </div>
  );
}

// ===== 报告布局渲染器已迁出至 components/report/report-block-renderer.tsx =====
// （块类型与后端 SUPPORTED_BLOCK_TYPES 对齐，补齐 10 种缺失块；单测见同目录 __tests__）

// ===== 空状态 =====

function EmptyState() {
  const navigate = useNavigate();
  return (
    <div className="flex flex-col items-center justify-center py-20 text-center">
      <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-bg-tertiary text-text-tertiary">
        <DocIcon size={22} />
      </div>
      <p className="mb-1 text-sm font-medium text-text-secondary">暂无已完成的讨论</p>
      <p className="mb-4 text-xs text-text-tertiary">去启动一个新讨论吧</p>
      <Button variant="outline" size="sm" onClick={() => navigate('/board')}>
        启动新讨论
      </Button>
    </div>
  );
}

// ===== 报告查看 Dialog =====

interface ReportDialogProps {
  meeting: MeetingReport | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

function ReportDialog({ meeting, open, onOpenChange }: ReportDialogProps) {
  const { data: summaryData, isLoading: summaryLoading } = useQuery({
    queryKey: reportKeys.summary(meeting?.id ?? ''),
    queryFn: () =>
      api.get<{ summary?: string } | string>(`/meetings/${meeting!.id}/summary`),
    enabled: !!meeting && open,
  });

  const { data: layoutData, isLoading: layoutLoading } = useQuery({
    queryKey: reportKeys.layout(meeting?.id ?? ''),
    queryFn: () => api.get(`/meetings/${meeting!.id}/report-layout`),
    enabled: !!meeting && open,
  });

  const summaryText = React.useMemo(() => {
    if (!summaryData) return meeting?.summary ?? '';
    if (typeof summaryData === 'string') return summaryData;
    if (typeof summaryData === 'object' && summaryData !== null) {
      return (summaryData as Record<string, unknown>).summary as string ?? '';
    }
    return meeting?.summary ?? '';
  }, [summaryData, meeting?.summary]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl" showClose>
        <DialogHeader className="pb-2">
          <DialogTitle className="truncate pr-8">{meeting?.title}</DialogTitle>
          <DialogDescription>
            {meeting?.completedAt != null
              ? formatRelativeTime(meeting.completedAt)
              : meeting?.createdAt != null
                ? formatRelativeTime(meeting.createdAt)
                : ''}
            {meeting?.deliverableType && (
              <Badge variant="secondary" className="ml-2 px-1.5 py-0 text-[10px]">
                {meeting.deliverableType}
              </Badge>
            )}
          </DialogDescription>
        </DialogHeader>

        <ScrollArea className="max-h-[65vh] px-6 pb-5">
          {/* Agent 信息 */}
          {meeting?.agents && meeting.agents.length > 0 && (
            <div className="mb-4 flex items-center gap-2">
              <span className="text-xs text-text-tertiary">参与 Agent:</span>
              <AgentAvatarGroup agents={meeting.agents} />
              <span className="text-xs text-text-tertiary">
                {meeting.agents.map((a) => a.name).join(', ')}
              </span>
            </div>
          )}

          <Separator className="mb-4" />

          {/* 摘要 */}
          <div className="mb-6">
            <h3 className="mb-2 text-sm font-semibold text-text-primary">讨论摘要</h3>
            {summaryLoading ? (
              <div className="space-y-2">
                <Skeleton className="h-3 w-full rounded" />
                <Skeleton className="h-3 w-4/5 rounded" />
                <Skeleton className="h-3 w-3/5 rounded" />
              </div>
            ) : summaryText ? (
              <div className="rounded-md bg-bg-secondary/50 p-4">
                <Markdown content={summaryText} className="prose-report" />
              </div>
            ) : (
              <p className="text-sm text-text-tertiary">暂无摘要</p>
            )}
          </div>

          {/* 完整报告 */}
          <div>
            <h3 className="mb-2 text-sm font-semibold text-text-primary">完整报告</h3>
            {layoutLoading ? (
              <div className="space-y-2">
                <Skeleton className="h-3 w-full rounded" />
                <Skeleton className="h-3 w-full rounded" />
                <Skeleton className="h-3 w-2/3 rounded" />
              </div>
            ) : layoutData ? (
              <ReportLayoutRenderer layout={layoutData as LayoutSpec} meetingId={meeting?.id} />
            ) : (
              <div className="rounded-md border border-dashed border-border-default p-4 text-center text-xs text-text-tertiary">
                报告数据未就绪
              </div>
            )}
          </div>
        </ScrollArea>
      </DialogContent>
    </Dialog>
  );
}

// ===== 附件下载 Dropdown =====

function AttachmentDropdown({ meetingId }: { meetingId: string }) {
  const [open, setOpen] = React.useState(false);

  const { data: attachmentsData, isLoading } = useQuery({
    queryKey: reportKeys.attachments(meetingId),
    queryFn: () =>
      api.get<Attachment[] | { attachments: Attachment[] }>(`/meetings/${meetingId}/attachments`),
    enabled: open, // dropdown 打开时才加载
  });

  const attachments = React.useMemo(() => {
    if (!attachmentsData) return [];
    if (Array.isArray(attachmentsData)) return attachmentsData;
    if (typeof attachmentsData === 'object' && Array.isArray((attachmentsData as Record<string, unknown>).attachments)) {
      return (attachmentsData as { attachments: Attachment[] }).attachments;
    }
    return [];
  }, [attachmentsData]);

  const handleDownload = async (filename: string) => {
    try {
      await api.download(`/meetings/${meetingId}/attachments/${encodeURIComponent(filename)}`, filename);
      toast({ title: '下载完成', description: filename });
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : '下载失败';
      toast({ title: '下载失败', description: message, variant: 'destructive' });
    }
  };

  return (
    <DropdownMenu open={open} onOpenChange={setOpen}>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="sm" className="gap-1 text-xs" onClick={(e) => e.stopPropagation()}>
          <DownloadIcon size={13} />
          下载附件
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-64">
        <DropdownMenuLabel>附件列表</DropdownMenuLabel>
        <DropdownMenuSeparator />
        {isLoading ? (
          <div className="px-2 py-3 text-center text-xs text-text-tertiary">加载中...</div>
        ) : attachments.length === 0 ? (
          <div className="px-2 py-3 text-center text-xs text-text-tertiary">暂无附件</div>
        ) : (
          attachments.map((att) => (
            <DropdownMenuItem
              key={att.filename}
              onClick={() => handleDownload(att.filename)}
              className="flex items-center gap-2 cursor-pointer"
            >
              <FileIcon size={14} className="flex-shrink-0 text-text-tertiary" />
              <span className="flex-1 truncate text-xs">{att.filename}</span>
              <span className="text-[10px] text-text-tertiary">{formatFileSize(att.size)}</span>
            </DropdownMenuItem>
          ))
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

// ===== 标签筛选 Dropdown =====

function TagFilterDropdown({
  tags,
  selectedTag,
  onSelect,
}: {
  tags: string[];
  selectedTag: string | null;
  onSelect: (tag: string | null) => void;
}) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" size="sm" className="gap-1.5 text-xs">
          <TagIcon size={13} />
          {selectedTag ?? '全部标签'}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-48">
        <DropdownMenuItem
          onClick={() => onSelect(null)}
          className={cn('cursor-pointer text-xs', !selectedTag && 'bg-bg-tertiary font-medium')}
        >
          全部标签
        </DropdownMenuItem>
        {tags.length > 0 && <DropdownMenuSeparator />}
        {tags.map((tag) => (
          <DropdownMenuItem
            key={tag}
            onClick={() => onSelect(tag)}
            className={cn('cursor-pointer text-xs', selectedTag === tag && 'bg-bg-tertiary font-medium')}
          >
            {tag}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

// ===== 主页面 =====

export default function ReportsPage() {
  const [searchQuery, setSearchQuery] = React.useState('');
  const [selectedTag, setSelectedTag] = React.useState<string | null>(null);
  const [selectedMeeting, setSelectedMeeting] = React.useState<MeetingReport | null>(null);
  const [dialogOpen, setDialogOpen] = React.useState(false);

  // 获取已完成的会议列表
  const { data, isLoading, isError, error } = useQuery({
    queryKey: reportKeys.list(),
    queryFn: () => api.get(`/meetings?status=done&limit=50`),
  });

  const meetings = React.useMemo(() => extractMeetings(data), [data]);

  // 收集所有标签
  const allTags = React.useMemo(() => {
    const tagSet = new Set<string>();
    meetings.forEach((m) => {
      m.tags?.forEach((t) => tagSet.add(t));
    });
    return Array.from(tagSet).sort();
  }, [meetings]);

  // 客户端过滤
  const filteredMeetings = React.useMemo(() => {
    let result = meetings;
    if (searchQuery.trim()) {
      const q = searchQuery.trim().toLowerCase();
      result = result.filter(
        (m) =>
          m.title.toLowerCase().includes(q) ||
          m.summary?.toLowerCase().includes(q)
      );
    }
    if (selectedTag) {
      result = result.filter((m) => m.tags?.includes(selectedTag));
    }
    // 按完成时间倒序（无完成时间则用创建时间）
    return [...result].sort((a, b) => {
      const ta = b.completedAt ?? b.createdAt;
      const tb = a.completedAt ?? a.createdAt;
      return ta - tb;
    });
  }, [meetings, searchQuery, selectedTag]);

  const handleViewReport = (meeting: MeetingReport) => {
    setSelectedMeeting(meeting);
    setDialogOpen(true);
  };

  // 错误提示
  React.useEffect(() => {
    if (isError && error) {
      toast({
        title: '加载报告列表失败',
        description: error instanceof Error ? error.message : '请稍后重试',
        variant: 'error',
      });
    }
  }, [isError, error]);

  return (
    <div className="mx-auto max-w-5xl pt-6 px-8 pb-8">
      {/* 页头 */}
      <div className="mb-6">
        <h1 className="text-xl font-semibold text-text-primary">报告库</h1>
        <p className="mt-1 text-sm text-text-tertiary">讨论产出的报告、方案和文档</p>
      </div>

      {/* 搜索和筛选栏 */}
      <div className="mb-4 flex items-center gap-2">
        <div className="relative flex-1 max-w-sm">
          <SearchIcon
            size={14}
            className="absolute left-2.5 top-1/2 -translate-y-1/2 text-text-tertiary"
          />
          <Input
            placeholder="搜索报告标题..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="pl-8 h-8 text-xs"
          />
        </div>
        {allTags.length > 0 && (
          <TagFilterDropdown
            tags={allTags}
            selectedTag={selectedTag}
            onSelect={setSelectedTag}
          />
        )}
      </div>

      {/* 列表 */}
      <Card className="overflow-hidden">
        {isLoading ? (
          <div className="divide-y divide-border-soft">
            {Array.from({ length: 5 }).map((_, i) => (
              <MeetingCardSkeleton key={i} />
            ))}
          </div>
        ) : filteredMeetings.length === 0 ? (
          <EmptyState />
        ) : (
          <div>
            {filteredMeetings.map((meeting, idx) => {
              const displayTime = meeting.completedAt ?? meeting.createdAt;
              return (
                <div
                  key={meeting.id}
                  role="button"
                  tabIndex={0}
                  className={cn(
                    'flex items-start gap-3 px-4 py-4 transition-colors hover:bg-bg-secondary cursor-pointer',
                    idx > 0 && 'border-t border-border-soft'
                  )}
                  onClick={() => handleViewReport(meeting)}
                  onKeyDown={(e) => {
                    if (e.target !== e.currentTarget) return;
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault();
                      handleViewReport(meeting);
                    }
                  }}
                >
                  {/* Agent 头像组 */}
                  <div className="flex-shrink-0 pt-0.5">
                    <AgentAvatarGroup agents={meeting.agents} />
                  </div>

                  {/* 主内容区 */}
                  <div className="min-w-0 flex-1">
                    {/* 标题行 */}
                    <div className="flex items-center gap-2">
                      <span className="truncate text-sm font-medium text-text-primary hover:text-brand-500">
                        {meeting.title}
                      </span>
                      {meeting.deliverableType && (
                        <Badge variant="secondary" className="flex-shrink-0 px-1.5 py-0 text-[10px]">
                          {meeting.deliverableType}
                        </Badge>
                      )}
                    </div>

                    {/* 元信息行 */}
                    <div className="mt-0.5 flex items-center gap-3 text-[11px] text-text-tertiary">
                      <span>{formatRelativeTime(displayTime)}</span>
                      {meeting.stage && (
                        <>
                          <span className="text-border-soft">·</span>
                          <span>{meeting.stage}</span>
                        </>
                      )}
                    </div>

                    {/* 摘要预览 */}
                    {meeting.summary && (
                      <p
                        className="mt-1.5 text-xs leading-relaxed text-text-tertiary overflow-hidden"
                        style={{
                          display: '-webkit-box',
                          WebkitLineClamp: 2,
                          WebkitBoxOrient: 'vertical',
                        }}
                      >
                        {meeting.summary}
                      </p>
                    )}

                    {/* 标签 */}
                    {meeting.tags && meeting.tags.length > 0 && (
                      <div className="mt-1.5 flex flex-wrap gap-1">
                        {meeting.tags.map((tag) => (
                          <Badge
                            key={tag}
                            variant="outline"
                            className="px-1.5 py-0 text-[10px] font-normal"
                          >
                            {tag}
                          </Badge>
                        ))}
                      </div>
                    )}
                  </div>

                  {/* 操作按钮区 */}
                  <div className="flex flex-shrink-0 items-center gap-1 pt-0.5">
                    <Button
                      variant="ghost"
                      size="sm"
                      className="gap-1 text-xs"
                      onClick={(e) => {
                        e.stopPropagation();
                        handleViewReport(meeting);
                      }}
                    >
                      <FileIcon size={13} />
                      查看报告
                    </Button>
                    <AttachmentDropdown meetingId={meeting.id} />
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </Card>

      {/* 报告查看 Dialog */}
      <ReportDialog
        meeting={selectedMeeting}
        open={dialogOpen}
        onOpenChange={(open) => {
          setDialogOpen(open);
          if (!open) setSelectedMeeting(null);
        }}
      />
    </div>
  );
}
