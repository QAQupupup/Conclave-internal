/**
 * 项目详情页（/projects/:id，ADR-017 Phase 2 前端接线）。
 *
 * 设计要点：
 * - 页头：返回 + 项目信息 + 编辑入口（复用 ProjectFormDialog）
 * - 状态过滤 pills：全部 + 六状态，带计数（来自项目详情 issue_stats）
 * - 议题行：状态徽章、优先级、来源标签、行内状态流转（只暴露合法流转目标）
 * - 闭环红线：流转到 resolved 必须填闭环凭证（弹 Dialog 输入产物 ID）
 * - 发起会议：仅 open/scheduled/conflict 可绑定，跳转 /board/new?issue=<id>
 * - 合入 main（ADR-017 D11）：in_progress/conflict 可发起，两阶段确认
 *   （MergeDialog 先干跑预览，用户确认后正式合并推送）
 */
import * as React from 'react';
import { useNavigate, useParams } from 'react-router';
import { useQueryClient } from '@tanstack/react-query';
import { cn, formatRelativeTime } from '@/lib/utils';
import { toast } from '@/hooks/use-toast';
import {
  useProject,
  useProjectIssues,
  useDeleteProject,
  useCreateIssue,
  useUpdateIssue,
  useDeleteIssue,
  useMergeIssue,
  allowedTransitions,
  isBindable,
  isMergeable,
  projectKeys,
  ISSUE_STATUSES,
  ISSUE_STATUS_LABELS,
} from '@/hooks/use-projects';
import { api } from '@/lib/api';
import type { Issue, IssueStatus, MergePreviewResponse } from '@/types';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Card } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { FieldError } from '@/components/ui/form-feedback';
import { ConfirmDialog } from '@/components/ui/confirm-dialog';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import {
  ChevronLeftIcon,
  PlusIcon,
  GitBranchIcon,
  GitMergeIcon,
  MoreHorizontalIcon,
  EditIcon,
  TrashIcon,
  PlayIcon,
  CheckCircleIcon,
  LinkIcon,
  SpinnerIcon,
} from '@/components/ui/svg-icons';
import { ProjectFormDialog } from './project-form-dialog';
import { extractMergeConflicts } from './merge-utils';

// ===== 状态徽章 =====

const STATUS_BADGE_VARIANT: Record<IssueStatus, 'outline' | 'secondary' | 'default' | 'success' | 'warning' | 'destructive'> = {
  open: 'outline',
  scheduled: 'warning',
  in_progress: 'default',
  conflict: 'destructive',
  resolved: 'success',
  wontfix: 'secondary',
};

function StatusBadge({ status }: { status: string }) {
  const key = (ISSUE_STATUSES.includes(status as IssueStatus) ? status : 'open') as IssueStatus;
  return <Badge variant={STATUS_BADGE_VARIANT[key]}>{ISSUE_STATUS_LABELS[key]}</Badge>;
}

// ===== 创建议题 Dialog =====

interface IssueFormDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  projectId: string;
}

function IssueFormDialog({ open, onOpenChange, projectId }: IssueFormDialogProps) {
  const [title, setTitle] = React.useState('');
  const [body, setBody] = React.useState('');
  const [priority, setPriority] = React.useState('50');
  const [errors, setErrors] = React.useState<{ title?: string; priority?: string }>({});
  const createIssue = useCreateIssue();

  // 打开时重置表单
  React.useEffect(() => {
    if (open) {
      setTitle('');
      setBody('');
      setPriority('50');
      setErrors({});
    }
  }, [open]);

  const validate = (): boolean => {
    const next: { title?: string; priority?: string } = {};
    if (!title.trim()) next.title = '请输入议题标题';
    const p = Number(priority);
    if (!Number.isInteger(p) || p < 0 || p > 100) next.priority = '优先级须为 0-100 的整数';
    setErrors(next);
    return Object.keys(next).length === 0;
  };

  const handleSubmit = async () => {
    if (createIssue.isPending || !validate()) return;
    try {
      await createIssue.mutateAsync({
        projectId,
        data: {
          title: title.trim(),
          body: body.trim() || null,
          source: 'user',
          priority: Number(priority),
        },
      });
      toast({ title: '议题已入池', description: title.trim() });
      onOpenChange(false);
    } catch (err: unknown) {
      toast({
        title: '创建议题失败',
        description: err instanceof Error ? err.message : '请稍后重试',
        variant: 'error',
      });
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md" showClose>
        <DialogHeader className="pb-2">
          <DialogTitle>新建议题</DialogTitle>
          <DialogDescription>议题入池后可排期、发起会议，会议闭环自动回填凭证</DialogDescription>
        </DialogHeader>

        <div className="space-y-3 px-6 pb-2">
          <div>
            <label htmlFor="issue-title" className="mb-1 block text-xs font-medium text-text-secondary">
              标题 <span className="text-danger">*</span>
            </label>
            <Input
              id="issue-title"
              value={title}
              onChange={(e) => {
                setTitle(e.target.value);
                if (errors.title) setErrors((prev) => ({ ...prev, title: undefined }));
              }}
              placeholder="一句话描述议题"
              aria-invalid={!!errors.title}
            />
            <FieldError>{errors.title}</FieldError>
          </div>
          <div>
            <label htmlFor="issue-body" className="mb-1 block text-xs font-medium text-text-secondary">
              详细描述
            </label>
            <Textarea
              id="issue-body"
              value={body}
              onChange={(e) => setBody(e.target.value)}
              placeholder="背景、目标、验收标准（可选）"
              rows={3}
              className="resize-none"
            />
          </div>
          <div>
            <label htmlFor="issue-priority" className="mb-1 block text-xs font-medium text-text-secondary">
              优先级（0-100，默认 50）
            </label>
            <Input
              id="issue-priority"
              type="number"
              min={0}
              max={100}
              value={priority}
              onChange={(e) => {
                setPriority(e.target.value);
                if (errors.priority) setErrors((prev) => ({ ...prev, priority: undefined }));
              }}
              aria-invalid={!!errors.priority}
            />
            <FieldError>{errors.priority}</FieldError>
          </div>
        </div>

        <DialogFooter className="px-6 pb-5">
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={createIssue.isPending}>
            取消
          </Button>
          <Button onClick={handleSubmit} disabled={createIssue.isPending}>
            创建
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ===== 闭环凭证 Dialog（resolved 红线） =====

interface ResolveDialogProps {
  issue: Issue | null;
  onClose: () => void;
}

function ResolveDialog({ issue, onClose }: ResolveDialogProps) {
  const [artifactId, setArtifactId] = React.useState('');
  const [error, setError] = React.useState('');
  const updateIssue = useUpdateIssue();

  React.useEffect(() => {
    if (issue) {
      setArtifactId(issue.resolution_artifact_id ?? '');
      setError('');
    }
  }, [issue]);

  const handleSubmit = async () => {
    if (!issue || updateIssue.isPending) return;
    if (!artifactId.trim()) {
      setError('闭环必须挂凭证：请输入产物 ID');
      return;
    }
    try {
      await updateIssue.mutateAsync({
        id: issue.id,
        data: { status: 'resolved', resolution_artifact_id: artifactId.trim() },
      });
      toast({ title: '议题已闭环', description: issue.title });
      onClose();
    } catch (err: unknown) {
      toast({
        title: '闭环失败',
        description: err instanceof Error ? err.message : '请稍后重试',
        variant: 'error',
      });
    }
  };

  return (
    <Dialog open={issue !== null} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-w-sm" showClose>
        <DialogHeader className="pb-2">
          <DialogTitle>闭环议题</DialogTitle>
          <DialogDescription>
            「{issue?.title ?? ''}」将流转到已闭环，必须挂闭环凭证（产物 ID）
          </DialogDescription>
        </DialogHeader>
        <div className="px-6 pb-2">
          <label htmlFor="resolve-artifact" className="mb-1 block text-xs font-medium text-text-secondary">
            闭环凭证（产物 ID） <span className="text-danger">*</span>
          </label>
          <Input
            id="resolve-artifact"
            value={artifactId}
            onChange={(e) => {
              setArtifactId(e.target.value);
              if (error) setError('');
            }}
            placeholder="例如会议产出的报告/文档 ID"
            aria-invalid={!!error}
          />
          <FieldError>{error}</FieldError>
        </div>
        <DialogFooter className="px-6 pb-5">
          <Button variant="outline" onClick={onClose} disabled={updateIssue.isPending}>
            取消
          </Button>
          <Button onClick={handleSubmit} disabled={updateIssue.isPending}>
            确认闭环
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ===== 合入 main Dialog（ADR-017 D11 两阶段确认） =====

interface MergeDialogProps {
  /** 非 null 即打开；仅 in_progress/conflict 态议题可传入 */
  issue: Issue | null;
  onClose: () => void;
}

/**
 * 合入两阶段确认弹窗：
 * 1. 打开即自动干跑预览（confirm=false，不落状态）——展示目标分支/变更清单；
 * 2. 用户确认后正式合入（confirm=true）——合并 + push + 议题闭环；
 * 3. 预览有冲突 → 禁用确认；执行遇冲突 → 议题已被后端置 conflict 态，
 *    展示冲突清单并失效缓存刷新列表。
 */
export function MergeDialog({ issue, onClose }: MergeDialogProps) {
  const qc = useQueryClient();
  const [preview, setPreview] = React.useState<MergePreviewResponse | null>(null);
  const [previewError, setPreviewError] = React.useState('');
  const [executing, setExecuting] = React.useState(false);
  const merge = useMergeIssue();

  // 第一阶段：打开即干跑预览（议题切换时重置现场）
  React.useEffect(() => {
    if (!issue) return;
    let cancelled = false;
    setPreview(null);
    setPreviewError('');
    setExecuting(false);
    api.issues
      .merge(issue.id, false)
      .then((res) => {
        if (!cancelled) setPreview(res as MergePreviewResponse);
      })
      .catch((err: unknown) => {
        if (!cancelled) setPreviewError(err instanceof Error ? err.message : '预览失败，请稍后重试');
      });
    return () => {
      cancelled = true;
    };
  }, [issue]);

  // 第二阶段：用户确认后正式合入
  const handleConfirm = async () => {
    if (!issue || !preview?.mergeable || executing) return;
    setExecuting(true);
    try {
      const res = await merge.mutateAsync({ id: issue.id, confirm: true });
      if (res.mode === 'execute') {
        toast({
          title: '已合入 main',
          description: `${issue.title} → ${res.pushed_to}（${res.merge_commit_sha}）`,
        });
      }
      onClose();
    } catch (err: unknown) {
      const conflicts = extractMergeConflicts(err);
      if (conflicts.length > 0 && preview) {
        // 合入冲突：议题已被后端置 conflict 态，展示清单并刷新列表
        setPreview({ ...preview, mergeable: false, conflicts });
        qc.invalidateQueries({ queryKey: projectKeys.detail(issue.project_id) });
        qc.invalidateQueries({ queryKey: projectKeys.lists() });
      } else {
        setPreviewError(err instanceof Error ? err.message : '合入失败，请稍后重试');
      }
      setExecuting(false);
    }
  };

  const mergeable = preview?.mergeable === true;

  return (
    <Dialog open={issue !== null} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-w-lg" showClose>
        <DialogHeader className="pb-2">
          <DialogTitle>合入 main</DialogTitle>
          <DialogDescription>
            「{issue?.title ?? ''}」将合入项目仓库 {preview?.branch ?? 'main'} 分支并推送远端
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3 px-6 pb-2">
          {!preview && !previewError && (
            <div className="flex items-center gap-2 py-6 text-xs text-text-tertiary">
              <SpinnerIcon size={14} className="animate-spin" />
              正在干跑合入预览…
            </div>
          )}

          {previewError && (
            <div className="rounded-md bg-danger/10 px-3 py-2 text-xs text-danger">{previewError}</div>
          )}

          {preview && (
            <>
              {/* 预览摘要 */}
              <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-text-tertiary">
                <span>目标分支：{preview.branch}</span>
                <span>变更文件：{preview.changed_files.length}</span>
                {preview.source_committed && <span>会议仓库未提交变更已自动提交</span>}
              </div>

              {mergeable ? (
                <div className="max-h-48 overflow-y-auto rounded-md border border-border-soft bg-bg-secondary/40 px-3 py-2">
                  {preview.changed_files.length === 0 ? (
                    <p className="text-xs text-text-tertiary">无文件变更（空合并）</p>
                  ) : (
                    preview.changed_files.map((line) => (
                      <p key={line} className="font-mono text-[11px] leading-5 text-text-secondary">
                        {line}
                      </p>
                    ))
                  )}
                </div>
              ) : (
                <div className="max-h-48 overflow-y-auto rounded-md border border-danger/30 bg-danger/5 px-3 py-2">
                  <p className="mb-1 text-xs font-medium text-danger">
                    合并冲突（{preview.conflicts.length} 个文件），议题已置「合入冲突」态
                  </p>
                  {preview.conflicts.map((f) => (
                    <p key={f} className="font-mono text-[11px] leading-5 text-text-secondary">
                      {f}
                    </p>
                  ))}
                  <p className="mt-1.5 text-[11px] text-text-tertiary">
                    请先解决冲突：可重新发起会议重做，或在仓库中手动解决后重试合入
                  </p>
                </div>
              )}
            </>
          )}
        </div>

        <DialogFooter className="px-6 pb-5">
          <Button variant="outline" onClick={onClose} disabled={executing}>
            {mergeable ? '取消' : '关闭'}
          </Button>
          {mergeable && (
            <Button onClick={handleConfirm} disabled={executing || !preview}>
              {executing ? '合入中…' : '确认合入'}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ===== 议题行 =====

interface IssueRowProps {
  issue: Issue;
  onTransition: (target: IssueStatus) => void;
  onStartMeeting: () => void;
  onMerge: () => void;
  onDelete: () => void;
}

function IssueRow({ issue, onTransition, onStartMeeting, onMerge, onDelete }: IssueRowProps) {
  const navigate = useNavigate();
  const transitions = allowedTransitions(issue.status);
  const bindable = isBindable(issue.status);
  const mergeable = isMergeable(issue.status);
  // resolved 走凭证 Dialog，其余直接流转
  const directTargets = transitions.filter((t) => t !== 'resolved');
  const canResolve = transitions.includes('resolved');

  return (
    <div className="flex items-center gap-4 px-4 py-3 transition-colors hover:bg-bg-secondary">
      {/* 标题 + 摘要 */}
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="truncate text-sm font-medium text-text-primary">{issue.title}</span>
          {issue.assigned_meeting_id && (
            <button
              type="button"
              onClick={() => navigate(`/meeting/${issue.assigned_meeting_id}`)}
              className="flex flex-shrink-0 items-center gap-1 rounded-full border border-border-soft px-1.5 py-0 text-[10px] text-text-tertiary transition-colors hover:border-brand-500/40 hover:text-brand-600"
              title="查看绑定会议"
            >
              <LinkIcon size={10} />
              会议中
            </button>
          )}
        </div>
        {issue.body && <p className="mt-0.5 truncate text-xs text-text-tertiary">{issue.body}</p>}
      </div>

      {/* 状态 */}
      <div className="w-16 flex-shrink-0">
        <StatusBadge status={issue.status} />
      </div>

      {/* 优先级 */}
      <div className="hidden w-12 flex-shrink-0 text-center text-xs text-text-tertiary md:block">
        {issue.priority}
      </div>

      {/* 来源 */}
      <div className="hidden w-14 flex-shrink-0 lg:block">
        <Badge variant="secondary" className="font-normal">
          {issue.source === 'meeting' ? '会议' : '手动'}
        </Badge>
      </div>

      {/* 创建时间 */}
      <div className="hidden w-24 flex-shrink-0 text-xs text-text-tertiary lg:block">
        {issue.created_at ? formatRelativeTime(Date.parse(issue.created_at)) : '—'}
      </div>

      {/* 行操作 */}
      <div className="flex w-[176px] flex-shrink-0 items-center justify-end gap-1">
        {bindable && (
          <Button
            variant="outline"
            size="sm"
            className="h-7 gap-1 px-2 text-xs"
            onClick={onStartMeeting}
            title="从该议题发起会议（自动绑定并流转到进行中）"
          >
            <PlayIcon size={11} />
            发起会议
          </Button>
        )}
        {mergeable && (
          <Button
            variant="outline"
            size="sm"
            className="h-7 gap-1 px-2 text-xs"
            onClick={onMerge}
            title="合入项目仓库主分支（两阶段确认：先预览变更，确认后合并推送）"
          >
            <GitMergeIcon size={11} />
            合入
          </Button>
        )}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="sm" className="h-7 w-7 p-0" aria-label="议题操作">
              <MoreHorizontalIcon size={14} />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-36">
            {directTargets.map((target) => (
              <DropdownMenuItem
                key={target}
                onClick={() => onTransition(target)}
                className="cursor-pointer gap-2 text-xs"
              >
                <CheckCircleIcon size={13} />
                流转：{ISSUE_STATUS_LABELS[target]}
              </DropdownMenuItem>
            ))}
            {canResolve && (
              <DropdownMenuItem
                onClick={() => onTransition('resolved')}
                className="cursor-pointer gap-2 text-xs"
              >
                <CheckCircleIcon size={13} />
                闭环（需凭证）
              </DropdownMenuItem>
            )}
            {(directTargets.length > 0 || canResolve) && <DropdownMenuSeparator />}
            <DropdownMenuItem
              onClick={onDelete}
              className="cursor-pointer gap-2 text-xs text-danger focus:text-danger"
            >
              <TrashIcon size={13} />
              删除
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </div>
  );
}

// ===== 主页面 =====

export default function ProjectDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();

  const { data: project, isLoading: projectLoading } = useProject(id);
  const [statusFilter, setStatusFilter] = React.useState('');
  const { data: issuesData, isLoading: issuesLoading } = useProjectIssues(id, {
    status: statusFilter || undefined,
  });

  const deleteProject = useDeleteProject();
  const updateIssue = useUpdateIssue();
  const deleteIssue = useDeleteIssue();

  const [editOpen, setEditOpen] = React.useState(false);
  const [issueFormOpen, setIssueFormOpen] = React.useState(false);
  const [resolvingIssue, setResolvingIssue] = React.useState<Issue | null>(null);
  const [mergingIssue, setMergingIssue] = React.useState<Issue | null>(null);
  const [deletingIssue, setDeletingIssue] = React.useState<Issue | null>(null);
  const [confirmDeleteProject, setConfirmDeleteProject] = React.useState(false);

  const issues = issuesData?.items ?? [];
  const stats = project?.issue_stats ?? {};

  const handleTransition = async (issue: Issue, target: IssueStatus) => {
    // resolved 需要凭证 → 打开凭证 Dialog；其余直接流转
    if (target === 'resolved') {
      setResolvingIssue(issue);
      return;
    }
    try {
      await updateIssue.mutateAsync({ id: issue.id, data: { status: target } });
      toast({ title: '状态已更新', description: `${issue.title} → ${ISSUE_STATUS_LABELS[target]}` });
    } catch (err: unknown) {
      toast({
        title: '流转失败',
        description: err instanceof Error ? err.message : '请稍后重试',
        variant: 'error',
      });
    }
  };

  const handleDeleteIssue = async () => {
    if (!deletingIssue || !id) return;
    const target = deletingIssue;
    setDeletingIssue(null);
    try {
      await deleteIssue.mutateAsync({ id: target.id, projectId: id });
      toast({ title: '议题已删除', description: target.title });
    } catch (err: unknown) {
      toast({
        title: '删除失败',
        description: err instanceof Error ? err.message : '请稍后重试',
        variant: 'error',
      });
    }
  };

  const handleDeleteProject = async () => {
    if (!id) return;
    setConfirmDeleteProject(false);
    try {
      await deleteProject.mutateAsync(id);
      toast({ title: '项目已删除', description: project?.name ?? '' });
      navigate('/projects');
    } catch (err: unknown) {
      toast({
        title: '删除失败',
        description: err instanceof Error ? err.message : '请稍后重试',
        variant: 'error',
      });
    }
  };

  // 过滤 pills：全部 + 六状态（计数来自 issue_stats）
  const filterPills: Array<{ value: string; label: string; count: number }> = [
    { value: '', label: '全部', count: stats.total ?? 0 },
    ...ISSUE_STATUSES.map((s) => ({ value: s, label: ISSUE_STATUS_LABELS[s], count: stats[s] ?? 0 })),
  ];

  return (
    <div className="mx-auto max-w-5xl px-8 pb-8 pt-6">
      {/* 页头 */}
      <div className="mb-5 flex items-start gap-2">
        <button
          type="button"
          onClick={() => navigate('/projects')}
          className="mt-0.5 rounded-md p-1.5 text-text-tertiary transition-colors hover:bg-bg-tertiary hover:text-text-secondary"
          aria-label="返回项目列表"
        >
          <ChevronLeftIcon size={16} />
        </button>
        <div className="min-w-0 flex-1">
          {projectLoading ? (
            <div className="space-y-1.5 py-0.5">
              <Skeleton className="h-5 w-48 rounded" />
              <Skeleton className="h-3.5 w-64 rounded" />
            </div>
          ) : project ? (
            <>
              <div className="flex items-center gap-2">
                <h1 className="truncate text-xl font-semibold text-text-primary">{project.name}</h1>
                <Badge variant="outline" className="flex-shrink-0 px-1.5 py-0 text-[10px] font-normal text-text-tertiary">
                  {project.slug}
                </Badge>
              </div>
              <div className="mt-1 flex items-center gap-3 text-xs text-text-tertiary">
                {project.repo_url ? (
                  <span className="flex items-center gap-1">
                    <GitBranchIcon size={12} />
                    {project.repo_url.replace(/^https?:\/\//, '')}
                    <span>({project.default_branch})</span>
                  </span>
                ) : (
                  <span>未绑定仓库</span>
                )}
                {project.description && <span className="truncate">{project.description}</span>}
              </div>
            </>
          ) : (
            <p className="text-sm text-text-tertiary">项目不存在或已删除</p>
          )}
        </div>
        {project && (
          <div className="flex flex-shrink-0 items-center gap-2">
            <Button variant="outline" size="sm" onClick={() => setEditOpen(true)}>
              <EditIcon size={12} className="mr-1" />
              编辑
            </Button>
            <Button variant="ghost" size="sm" className="text-danger hover:text-danger" onClick={() => setConfirmDeleteProject(true)}>
              <TrashIcon size={12} className="mr-1" />
              删除
            </Button>
          </div>
        )}
      </div>

      {/* 状态过滤 + 新建 */}
      <div className="mb-4 flex items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-1.5">
          {filterPills.map((pill) => (
            <button
              key={pill.value}
              type="button"
              onClick={() => setStatusFilter(pill.value)}
              className={cn(
                'rounded-full border px-2.5 py-1 text-xs transition-colors',
                statusFilter === pill.value
                  ? 'border-brand-500/50 bg-brand-soft text-brand-600'
                  : 'border-border-default bg-bg-primary text-text-secondary hover:border-brand-500/30',
              )}
            >
              {pill.label}
              <span className="ml-1 text-[10px] text-text-tertiary">{pill.count}</span>
            </button>
          ))}
        </div>
        <Button size="sm" onClick={() => setIssueFormOpen(true)} disabled={!project} className="gap-1">
          <PlusIcon size={13} />
          新建议题
        </Button>
      </div>

      {/* 议题列表 */}
      <Card className="overflow-hidden">
        {/* 表头（中性灰） */}
        <div className="flex items-center gap-4 border-b border-border-soft bg-bg-secondary/60 px-4 py-2 text-[11px] font-medium text-text-tertiary">
          <span className="flex-1">议题</span>
          <span className="w-16">状态</span>
          <span className="hidden w-12 text-center md:block">优先级</span>
          <span className="hidden w-14 lg:block">来源</span>
          <span className="hidden w-24 lg:block">创建时间</span>
          <span className="w-[176px]" />
        </div>

        {issuesLoading ? (
          <div className="divide-y divide-border-soft">
            {Array.from({ length: 3 }).map((_, i) => (
              <div key={i} className="flex items-center gap-4 px-4 py-3.5">
                <div className="flex-1 space-y-1.5">
                  <Skeleton className="h-4 w-2/5 rounded" />
                  <Skeleton className="h-3 w-3/5 rounded" />
                </div>
                <Skeleton className="h-4 w-14 rounded-full" />
              </div>
            ))}
          </div>
        ) : issues.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 text-center">
            <p className="mb-1 text-sm font-medium text-text-secondary">
              {statusFilter ? `没有「${ISSUE_STATUS_LABELS[statusFilter as IssueStatus]}」状态的议题` : '议题池为空'}
            </p>
            <p className="mb-4 text-xs text-text-tertiary">
              {statusFilter ? '换个状态过滤看看，或新建一条' : '新建议题入池，排期后可发起会议'}
            </p>
            {!statusFilter && (
              <Button variant="outline" size="sm" onClick={() => setIssueFormOpen(true)} disabled={!project}>
                新建议题
              </Button>
            )}
          </div>
        ) : (
          <div className="divide-y divide-border-soft">
            {issues.map((issue) => (
              <IssueRow
                key={issue.id}
                issue={issue}
                onTransition={(target) => handleTransition(issue, target)}
                onStartMeeting={() => navigate(`/board/new?issue=${issue.id}`)}
                onMerge={() => setMergingIssue(issue)}
                onDelete={() => setDeletingIssue(issue)}
              />
            ))}
          </div>
        )}
      </Card>

      <p className={cn('mt-3 text-[11px] text-text-tertiary', issues.length === 0 && 'hidden')}>
        共 {issuesData?.total ?? 0} 条议题 · 发起会议将自动绑定议题并流转到进行中
      </p>

      {/* Dialogs */}
      <ProjectFormDialog open={editOpen} onOpenChange={setEditOpen} project={project ?? null} />
      {id && <IssueFormDialog open={issueFormOpen} onOpenChange={setIssueFormOpen} projectId={id} />}
      <ResolveDialog issue={resolvingIssue} onClose={() => setResolvingIssue(null)} />
      <MergeDialog issue={mergingIssue} onClose={() => setMergingIssue(null)} />

      {/* 议题删除确认 */}
      <ConfirmDialog
        open={deletingIssue !== null}
        title="删除议题"
        description={`「${deletingIssue?.title ?? ''}」将被删除，会议侧关联将解除。此操作不可恢复。`}
        confirmText="删除"
        destructive
        onConfirm={handleDeleteIssue}
        onCancel={() => setDeletingIssue(null)}
      />

      {/* 项目删除确认 */}
      <ConfirmDialog
        open={confirmDeleteProject}
        title="删除项目"
        description={`「${project?.name ?? ''}」下的所有议题将一并删除，会议与产物的项目关联将解除。此操作不可恢复。`}
        confirmText="删除"
        destructive
        onConfirm={handleDeleteProject}
        onCancel={() => setConfirmDeleteProject(false)}
      />
    </div>
  );
}
