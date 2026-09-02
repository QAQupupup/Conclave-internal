import * as React from 'react';
import { useNavigate } from 'react-router';
import {
  useMeetings,
  useStartMeeting,
  useRunMeeting,
  useDeleteMeeting,
  useUploadMeetingDocument,
  useAgentRoles,
} from '@/hooks/use-meetings';
import { useQueryClient } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Textarea } from '@/components/ui/textarea';
import { FieldError } from '@/components/ui/form-feedback';
import { ConfirmDialog } from '@/components/ui/confirm-dialog';
import { cn, formatRelativeTime, truncate } from '@/lib/utils';
import type { Meeting, MeetingStatus } from '@/types';
import {
  STAGE_LABELS,
  DELIVERABLE_TYPES,
  FLOW_PLANS,
  DEBATE_DEPTHS,
  UPLOAD_ACCEPT,
  UPLOAD_MAX_SIZE_MB,
  UPLOAD_ALLOWED_EXTENSIONS,
} from '@/lib/constants';
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
  UploadIcon,
  FileIcon,
  XIcon,
  LinkIcon,
  CheckCircleIcon,
  SearchIcon,
} from '@/components/ui/svg-icons';

const STATUS_CONFIG: Record<MeetingStatus, { label: string; variant: 'default' | 'secondary' | 'outline' | 'destructive'; color: string }> = {
  pending: { label: '待开始', variant: 'outline', color: 'text-text-tertiary' },
  running: { label: '运行中', variant: 'default', color: 'text-brand-500' },
  paused: { label: '已暂停', variant: 'secondary', color: 'text-warning' },
  done: { label: '已完成', variant: 'secondary', color: 'text-success' },
  error: { label: '出错', variant: 'destructive', color: 'text-danger' },
  aborted: { label: '已终止', variant: 'secondary', color: 'text-text-tertiary' },
};

/** 启动流程的阶段提示（创建→上传→运行） */
type LaunchPhase = 'idle' | 'creating' | 'uploading' | 'running';

export default function BoardPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [topic, setTopic] = React.useState('');
  const [topicError, setTopicError] = React.useState('');
  const [topicHistory, setTopicHistory] = React.useState<string[]>([]);
  const [isPolishing, setIsPolishing] = React.useState(false);
  const [showNewForm, setShowNewForm] = React.useState(false);
  const textareaRef = React.useRef<HTMLTextAreaElement>(null);
  const { data: meetingsData, isLoading } = useMeetings({ pageSize: 50 });
  const startMeeting = useStartMeeting();
  const runMeeting = useRunMeeting();
  const uploadDoc = useUploadMeetingDocument();
  const deleteMeeting = useDeleteMeeting();
  const [deleteTarget, setDeleteTarget] = React.useState<{ id: string; title: string } | null>(null);

  // 创建配置
  const [deliverableType, setDeliverableType] = React.useState('prd_openapi');
  const [flowPlan, setFlowPlan] = React.useState('standard');
  const [debateDepth, setDebateDepth] = React.useState('standard');
  const [selectedRoleIds, setSelectedRoleIds] = React.useState<string[]>([]);
  const [files, setFiles] = React.useState<File[]>([]);
  const [launchPhase, setLaunchPhase] = React.useState<LaunchPhase>('idle');
  const [uploadProgress, setUploadProgress] = React.useState<{ name: string; percent: number } | null>(null);
  const fileInputRef = React.useRef<HTMLInputElement>(null);
  const { data: roles } = useAgentRoles();

  // 临近话题推荐：创建会议时按议题文本检索相似历史会议
  const [relatedIds, setRelatedIds] = React.useState<string[]>([]);
  const [relatedSuggestions, setRelatedSuggestions] = React.useState<
    Array<{ meeting_id: string; topic: string; status: string; deliverable_type?: string; score?: number }>
  >([]);
  const [relatedLoading, setRelatedLoading] = React.useState(false);
  const [showRelatedPopover, setShowRelatedPopover] = React.useState(false);
  const relatedQueryToken = React.useRef(0);
  const relatedContainerRef = React.useRef<HTMLDivElement>(null);
  const relatedTopicMap = React.useRef<Record<string, string>>({});

  const toggleRelated = (id: string) => {
    setRelatedIds((prev) => (prev.includes(id) ? prev.filter((r) => r !== id) : [...prev, id]));
  };

  // 议题输入防抖（500ms）-> 检索相似历史会议；推荐为非关键路径，失败静默
  React.useEffect(() => {
    const q = topic.trim();
    if (!showNewForm || q.length < 4) {
      setRelatedSuggestions([]);
      setShowRelatedPopover(false);
      return;
    }
    setRelatedLoading(true);
    const token = ++relatedQueryToken.current;
    const t = window.setTimeout(async () => {
      try {
        const res = await api.relatedMeetings(q, 5);
        if (token !== relatedQueryToken.current) return;
        const items = Array.isArray(res?.meetings) ? res.meetings : [];
        items.forEach((i) => {
          relatedTopicMap.current[i.meeting_id] = i.topic;
        });
        setRelatedSuggestions(items);
        setShowRelatedPopover(items.length > 0);
      } catch {
        // 推荐为非关键路径，失败静默
      } finally {
        if (token === relatedQueryToken.current) setRelatedLoading(false);
      }
    }, 500);
    return () => window.clearTimeout(t);
  }, [topic, showNewForm]);

  const meetings = Array.isArray(meetingsData?.items) ? meetingsData.items : [];
  const activeMeetings = meetings.filter((m) => m.status === 'running' || m.status === 'paused');
  const pastMeetings = meetings.filter((m) => m.status === 'done' || m.status === 'error' || m.status === 'aborted' || m.status === 'pending');
  const isLaunching = launchPhase !== 'idle';

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
    } catch (e: unknown) {
      toast({ title: '润色失败', description: (e as Error).message, variant: 'error' });
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

  const toggleRole = (id: string) => {
    setSelectedRoleIds((prev) => (prev.includes(id) ? prev.filter((r) => r !== id) : [...prev, id]));
  };

  const handleFilesSelected = (selected: FileList | null) => {
    if (!selected) return;
    const next: File[] = [];
    for (const f of Array.from(selected)) {
      const ext = f.name.slice(f.name.lastIndexOf('.')).toLowerCase();
      if (!UPLOAD_ALLOWED_EXTENSIONS.includes(ext)) {
        toast({ title: '不支持的文件类型', description: `${f.name}：当前仅支持 ${UPLOAD_ALLOWED_EXTENSIONS.join(' ')}`, variant: 'error' });
        continue;
      }
      if (f.size > UPLOAD_MAX_SIZE_MB * 1024 * 1024) {
        toast({ title: '文件过大', description: `${f.name} 超过 ${UPLOAD_MAX_SIZE_MB}MB 上限`, variant: 'error' });
        continue;
      }
      next.push(f);
    }
    setFiles((prev) => [...prev, ...next]);
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  const resetForm = () => {
    setTopic('');
    setTopicError('');
    setTopicHistory([]);
    setFiles([]);
    setSelectedRoleIds([]);
    setRelatedIds([]);
    setRelatedSuggestions([]);
    setShowRelatedPopover(false);
    setDeliverableType('prd_openapi');
    setFlowPlan('standard');
    setDebateDepth('standard');
    setShowNewForm(false);
  };

  const handleStart = async (e?: React.FormEvent) => {
    e?.preventDefault();
    if (isLaunching) return;
    if (!topic.trim()) {
      setTopicError('请先输入议题内容');
      textareaRef.current?.focus();
      return;
    }
    setTopicError('');
    try {
      // 1. 创建会议（POST /meetings 只创建不运行）
      setLaunchPhase('creating');
      const res = await startMeeting.mutateAsync({
        topic: topic.trim(),
        deliverable_type: deliverableType,
        flow_plan: flowPlan,
        debate_depth: debateDepth,
        role_ids: selectedRoleIds,
        reference_meeting_ids: relatedIds,
      });
      const meetingId = res.meeting_id;

      // 2. 上传参考文档（逐个，带进度）
      if (files.length > 0) {
        setLaunchPhase('uploading');
        for (const f of files) {
          setUploadProgress({ name: f.name, percent: 0 });
          try {
            await uploadDoc.mutateAsync({
              meetingId,
              file: f,
              onProgress: (percent) => setUploadProgress({ name: f.name, percent }),
            });
          } catch (err: unknown) {
            toast({ title: '附件上传失败', description: `${f.name}：${(err as Error).message}`, variant: 'error' });
          }
        }
        setUploadProgress(null);
      }

      // 3. 启动运行
      setLaunchPhase('running');
      await runMeeting.mutateAsync(meetingId);

      toast({ title: '讨论已启动', description: truncate(topic, 50) });
      resetForm();
      navigate(`/meeting/${meetingId}`);
    } catch (e: unknown) {
      toast({ title: '启动失败', description: (e as Error).message, variant: 'error' });
    } finally {
      setLaunchPhase('idle');
      setUploadProgress(null);
    }
  };

  const launchButtonText =
    launchPhase === 'creating'
      ? '创建会议...'
      : launchPhase === 'uploading'
        ? `上传附件 ${uploadProgress?.percent ?? 0}%`
        : launchPhase === 'running'
          ? '启动运行...'
          : '开始讨论';

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
              {/* 议题输入 + 临近话题推荐 */}
              <div className="relative" ref={relatedContainerRef}>
                <Textarea
                  ref={textareaRef}
                  value={topic}
                  onChange={(e) => {
                    setTopic(e.target.value);
                    if (topicError && e.target.value.trim()) setTopicError('');
                  }}
                  placeholder="描述你想讨论的议题或问题...&#10;例如：分析微服务架构中服务间通信的最佳实践，对比 gRPC 和 REST 的适用场景"
                  className="min-h-[96px] text-[15px] leading-relaxed"
                  disabled={isLaunching}
                  aria-invalid={!!topicError}
                  aria-describedby={topicError ? 'topic-error' : undefined}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
                      e.preventDefault();
                      handleStart();
                    }
                  }}
                />

                {/* 近似历史会议推荐（非关键路径，失败静默） */}
                {showRelatedPopover && (
                  <div
                    className="absolute left-0 right-0 top-full z-20 mt-1 overflow-hidden rounded-md border border-border-default bg-bg-primary shadow-md"
                    onPointerDown={(e) => e.preventDefault()}
                  >
                    <div className="flex items-center justify-between border-b border-border-soft px-2.5 py-1.5">
                      <span className="flex items-center gap-1 text-[11px] text-text-tertiary">
                        <SearchIcon size={12} />
                        相似历史会议（点击关联）
                      </span>
                      <button
                        type="button"
                        onClick={() => setShowRelatedPopover(false)}
                        className="rounded p-0.5 text-text-tertiary hover:text-text-secondary"
                        aria-label="关闭推荐"
                      >
                        <XIcon size={12} />
                      </button>
                    </div>
                    <ul className="max-h-56 overflow-y-auto py-1">
                      {relatedSuggestions.map((m) => {
                        const checked = relatedIds.includes(m.meeting_id);
                        return (
                          <li key={m.meeting_id}>
                            <button
                              type="button"
                              onClick={() => toggleRelated(m.meeting_id)}
                              className={cn(
                                'flex w-full items-center gap-2 px-2.5 py-1.5 text-left transition-colors',
                                checked ? 'bg-brand-soft' : 'hover:bg-bg-secondary',
                              )}
                            >
                              <span
                                className={cn(
                                  'flex h-4 w-4 flex-shrink-0 items-center justify-center rounded border',
                                  checked ? 'border-brand-500 bg-brand-500' : 'border-border-default',
                                )}
                              >
                                {checked && <CheckCircleIcon size={12} className="text-white" />}
                              </span>
                              <span className="min-w-0 flex-1 truncate text-xs text-text-primary">{m.topic}</span>
                              {typeof m.score === 'number' && (
                                <span className="flex-shrink-0 rounded bg-brand-soft px-1 text-[10px] text-brand-600">
                                  {(m.score * 100).toFixed(0)}%
                                </span>
                              )}
                            </button>
                          </li>
                        );
                      })}
                    </ul>
                    {relatedLoading && (
                      <div className="flex items-center gap-1.5 border-t border-border-soft px-2.5 py-1.5 text-[11px] text-text-tertiary">
                        <SpinnerIcon size={11} className="animate-spin" />
                        检索相似会议中...
                      </div>
                    )}
                  </div>
                )}
              </div>
              <FieldError id="topic-error" className="mt-1.5">{topicError}</FieldError>

              {/* 已关联的相似会议 */}
              {relatedIds.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {relatedIds.map((id) => {
                    const label = relatedTopicMap.current[id] ?? '关联会议';
                    return (
                      <span
                        key={id}
                        className="flex items-center gap-1 rounded-full border border-brand-500/40 bg-brand-soft px-2 py-0.5 text-[11px] text-brand-600"
                      >
                        <LinkIcon size={11} />
                        <span className="max-w-[200px] truncate">{label}</span>
                        <button
                          type="button"
                          onClick={() => toggleRelated(id)}
                          className="rounded-full p-0.5 hover:text-brand-500"
                          aria-label="取消关联"
                        >
                          <XIcon size={10} />
                        </button>
                      </span>
                    );
                  })}
                </div>
              )}

              {/* 会议配置 */}
              <div className="mt-3 grid gap-3 border-t border-border-soft pt-3 sm:grid-cols-3">
                <OptionSelect
                  label="产出类型"
                  value={deliverableType}
                  onChange={setDeliverableType}
                  options={DELIVERABLE_TYPES}
                  disabled={isLaunching}
                />
                <OptionSelect
                  label="执行模式"
                  value={flowPlan}
                  onChange={setFlowPlan}
                  options={FLOW_PLANS}
                  disabled={isLaunching}
                />
                <OptionSelect
                  label="辩论深度"
                  value={debateDepth}
                  onChange={setDebateDepth}
                  options={DEBATE_DEPTHS}
                  disabled={isLaunching}
                />
              </div>

              {/* 角色选择 */}
              <div className="mt-3 border-t border-border-soft pt-3">
                <div className="mb-1.5 flex items-center justify-between">
                  <span className="text-xs font-medium text-text-secondary">参与角色</span>
                  <span className="text-[11px] text-text-tertiary">
                    {selectedRoleIds.length === 0 ? '不选择则自动配置全部活跃角色' : `已选 ${selectedRoleIds.length} 个`}
                  </span>
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {(roles ?? []).map((r) => {
                    const active = selectedRoleIds.includes(r.id);
                    return (
                      <button
                        key={r.id}
                        type="button"
                        disabled={isLaunching}
                        onClick={() => toggleRole(r.id)}
                        title={r.perspective}
                        className={cn(
                          'rounded-full border px-2.5 py-1 text-xs transition-colors',
                          active
                            ? 'border-brand-500/50 bg-brand-soft text-brand-600'
                            : 'border-border-default bg-bg-secondary text-text-secondary hover:border-brand-500/30',
                        )}
                      >
                        {r.display_name}
                      </button>
                    );
                  })}
                </div>
              </div>

              {/* 附件 */}
              <div className="mt-3 border-t border-border-soft pt-3">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-medium text-text-secondary">参考文档</span>
                  <span className="text-[11px] text-text-tertiary">
                    支持 {UPLOAD_ALLOWED_EXTENSIONS.join(' ')}，单个 ≤ {UPLOAD_MAX_SIZE_MB}MB
                  </span>
                </div>
                {files.length > 0 && (
                  <ul className="mt-2 space-y-1">
                    {files.map((f, i) => (
                      <li
                        key={`${f.name}-${i}`}
                        className="flex items-center gap-2 rounded-md border border-border-soft bg-bg-secondary px-2.5 py-1.5 text-xs"
                      >
                        <FileIcon size={12} className="flex-shrink-0 text-text-tertiary" />
                        <span className="min-w-0 flex-1 truncate text-text-primary">{f.name}</span>
                        <span className="flex-shrink-0 text-text-tertiary">{(f.size / 1024).toFixed(0)}KB</span>
                        <button
                          type="button"
                          disabled={isLaunching}
                          onClick={() => setFiles((prev) => prev.filter((_, idx) => idx !== i))}
                          className="flex-shrink-0 rounded p-0.5 text-text-tertiary hover:text-danger"
                          aria-label={`移除 ${f.name}`}
                        >
                          <XIcon size={12} />
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
                <input
                  ref={fileInputRef}
                  type="file"
                  multiple
                  accept={UPLOAD_ACCEPT}
                  className="hidden"
                  onChange={(e) => handleFilesSelected(e.target.files)}
                />
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  disabled={isLaunching}
                  onClick={() => fileInputRef.current?.click()}
                  className="mt-2 h-7 gap-1 text-xs"
                >
                  <UploadIcon size={12} />
                  添加文档
                </Button>
                {uploadProgress && (
                  <div className="mt-2">
                    <div className="mb-1 flex justify-between text-[11px] text-text-tertiary">
                      <span className="truncate">{uploadProgress.name}</span>
                      <span>{uploadProgress.percent}%</span>
                    </div>
                    <div className="h-1 overflow-hidden rounded-full bg-bg-tertiary">
                      <div
                        className="h-full rounded-full bg-brand-500 transition-all"
                        style={{ width: `${uploadProgress.percent}%` }}
                      />
                    </div>
                  </div>
                )}
              </div>

              <div className="mt-3 flex items-center justify-between border-t border-border-soft pt-3">
                <div className="flex items-center gap-1">
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={handlePolish}
                    disabled={!topic.trim() || isPolishing || isLaunching}
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
                    disabled={topicHistory.length === 0 || isLaunching}
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
                  <Button type="button" variant="ghost" size="sm" disabled={isLaunching} onClick={resetForm}>
                    取消
                  </Button>
                  <Button type="submit" size="sm" disabled={!topic.trim() || isLaunching}>
                    {isLaunching ? (
                      <SpinnerIcon size={12} className="mr-1 animate-spin" />
                    ) : (
                      <PlayIcon size={12} className="mr-1" />
                    )}
                    {launchButtonText}
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
              <MeetingCard key={m.id} meeting={m} onClick={() => navigate(`/meeting/${m.id}`)} onDelete={(e) => handleDelete(e, m.id, m.title)} />
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
                onClick={() => navigate(`/meeting/${m.id}`)}
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

/** 紧凑下拉选择（创建会议配置项） */
function OptionSelect({
  label,
  value,
  onChange,
  options,
  disabled,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string; description: string }[];
  disabled?: boolean;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-text-secondary">{label}</span>
      <select
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-md border border-border-default bg-bg-secondary px-2 py-1.5 text-xs text-text-primary outline-none transition-colors focus:border-brand-500/40 disabled:opacity-50"
      >
        {options.map((o) => (
          <option key={o.value} value={o.value} title={o.description}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  );
}

function MeetingCard({ meeting, onClick, onDelete }: { meeting: Meeting; onClick: () => void; onDelete: (e: React.MouseEvent) => void }) {
  const statusConf = STATUS_CONFIG[meeting.status as MeetingStatus];
  return (
    <Card
      className="cursor-pointer transition-all hover:border-brand-500/30 hover:shadow-md"
      onClick={onClick}
    >
      <CardHeader className="pb-2">
        <div className="flex items-start justify-between gap-2">
          <CardTitle className="line-clamp-2 text-sm font-medium leading-snug">{meeting.title}</CardTitle>
          <div className="flex flex-shrink-0 items-center gap-1">
            <Badge variant={statusConf.variant} className={cn('text-[10px]', statusConf.color)}>
              {statusConf.label}
            </Badge>
            <button
              onClick={onDelete}
              className="rounded p-1 text-text-tertiary transition-colors hover:bg-danger-bg hover:text-danger"
              title="删除"
              aria-label="删除"
            >
              <TrashIcon size={12} />
            </button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="pb-3">
        <div className="flex items-center gap-3 text-[11px] text-text-tertiary">
          <span className="flex items-center gap-1">
            <ClockIcon size={12} />
            {formatRelativeTime(meeting.createdAt ?? meeting.created_at ?? Date.now())}
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

function MeetingRow({ meeting, onClick, onDelete }: { meeting: Meeting; onClick: () => void; onDelete: (e: React.MouseEvent) => void }) {
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
            <span>{formatRelativeTime(meeting.createdAt ?? meeting.created_at ?? Date.now())}</span>
            {(meeting.messageCount ?? meeting.message_count) !== undefined && (
              <span>{meeting.messageCount ?? meeting.message_count} 条消息</span>
            )}
          </div>
        </div>
        <ArrowRightIcon size={16} className="flex-shrink-0 text-text-tertiary opacity-0 transition-opacity group-hover:opacity-100" />
      </button>
      <button
        onClick={onDelete}
        className="rounded p-1 text-text-tertiary transition-all hover:bg-danger-bg hover:text-danger"
        title="删除"
        aria-label="删除"
      >
        <TrashIcon size={14} />
      </button>
    </div>
  );
}
