/**
 * 议题创建页（/board/new）—— 从 board 列表页拆出的专注型输入页面（问题 5 方案 B）。
 *
 * 设计要点（可行性报告 5.4）：
 * - 大编辑区：min 320px、随内容伸展、60vh 上限后转内部滚动；行长约 72ch 居中
 * - 双栏布局：左主栏 = 编辑区 + 相近话题推荐；右侧栏 = 启动参数 / 参与角色 / 参考文档
 * - 底部操作条：取消（返回列表）/ 保存草稿（只创建不运行）/ 发起会议（主按钮）
 * - ?from=<meeting_id>：复用历史议题预填（列表页行操作入口）
 * - ?issue=<issue_id>：从议题池发起会议（ADR-017 Phase 2）——预填议题文本，
 *   创建时携带 issue_id，后端绑定议题（open/scheduled → in_progress）并回填项目归属
 */
import * as React from 'react';
import { useNavigate, useSearchParams } from 'react-router';
import { useQueryClient } from '@tanstack/react-query';
import {
  useStartMeeting,
  useRunMeeting,
  useUploadMeetingDocument,
  useAgentRoles,
  useMeeting,
} from '@/hooks/use-meetings';
import { useIssue, isBindable, projectKeys, issueKeys } from '@/hooks/use-projects';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { FieldError } from '@/components/ui/form-feedback';
import { cn, truncate } from '@/lib/utils';
import {
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
  ChevronLeftIcon,
  PlayIcon,
  SpinnerIcon,
  WandIcon,
  UndoIcon,
  UploadIcon,
  FileIcon,
  XIcon,
  LinkIcon,
  CheckCircleIcon,
  SearchIcon,
} from '@/components/ui/svg-icons';

/** 启动流程的阶段提示（创建→上传→运行） */
type LaunchPhase = 'idle' | 'creating' | 'uploading' | 'running';

export default function BoardNewPage() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [searchParams] = useSearchParams();
  const fromId = searchParams.get('from');
  const { data: fromMeeting } = useMeeting(fromId);
  // ADR-017 Phase 2：从议题池发起（项目详情页"发起会议"入口跳转而来）
  const issueId = searchParams.get('issue');
  const { data: issue } = useIssue(issueId);
  // 仅 open/scheduled 可绑定（与后端 bind_meeting 校验一致）；不可绑定时不携带 issue_id
  const issueBindable = !!issue && isBindable(issue.status);

  const [topic, setTopic] = React.useState('');
  const [topicError, setTopicError] = React.useState('');
  const [topicHistory, setTopicHistory] = React.useState<string[]>([]);
  const [isPolishing, setIsPolishing] = React.useState(false);
  const textareaRef = React.useRef<HTMLTextAreaElement>(null);
  const prefilledRef = React.useRef(false);

  const startMeeting = useStartMeeting();
  const runMeeting = useRunMeeting();
  const uploadDoc = useUploadMeetingDocument();

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

  // 临近话题推荐：按议题文本检索相似历史会议（非关键路径，失败静默）
  const [relatedIds, setRelatedIds] = React.useState<string[]>([]);
  const [relatedSuggestions, setRelatedSuggestions] = React.useState<
    Array<{ meeting_id: string; topic: string; status: string; deliverable_type?: string; score?: number }>
  >([]);
  const [relatedLoading, setRelatedLoading] = React.useState(false);
  const [showRelatedPopover, setShowRelatedPopover] = React.useState(false);
  const relatedQueryToken = React.useRef(0);
  const relatedTopicMap = React.useRef<Record<string, string>>({});

  // 复用议题预填：源会议加载完成后一次性带入（避免覆盖用户已编辑内容）
  React.useEffect(() => {
    if (fromMeeting?.topic && !prefilledRef.current) {
      prefilledRef.current = true;
      setTopic(fromMeeting.topic);
    }
  }, [fromMeeting]);

  // 议题池预填：标题 + 详情一次性带入（?issue= 入口，同样只预填一次）
  React.useEffect(() => {
    if (issue && !prefilledRef.current) {
      prefilledRef.current = true;
      setTopic(issue.body ? `${issue.title}\n\n${issue.body}` : issue.title);
    }
  }, [issue]);

  const toggleRelated = (id: string) => {
    setRelatedIds((prev) => (prev.includes(id) ? prev.filter((r) => r !== id) : [...prev, id]));
  };

  // 议题输入防抖（500ms）-> 检索相似历史会议
  React.useEffect(() => {
    const q = topic.trim();
    if (q.length < 4) {
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
  }, [topic]);

  const isLaunching = launchPhase !== 'idle';

  /** 返回目标：议题入口 → 项目详情页；其余 → 看板列表 */
  const backPath = issue ? `/projects/${issue.project_id}` : '/board';

  // Auto-resize textarea：min 320px，上限 60vh，超限转内部滚动（问题 5：编辑区解压）
  React.useEffect(() => {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.style.height = 'auto';
    const cap = Math.round(window.innerHeight * 0.6);
    ta.style.height = Math.min(Math.max(ta.scrollHeight, 320), cap) + 'px';
  }, [topic]);

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

  const validateTopic = (): boolean => {
    if (!topic.trim()) {
      setTopicError('请先输入议题内容');
      textareaRef.current?.focus();
      return false;
    }
    setTopicError('');
    return true;
  };

  /** 创建会议 + 上传附件（草稿与发起共用），返回 meeting_id */
  const createAndUpload = async (): Promise<string> => {
    setLaunchPhase('creating');
    const res = await startMeeting.mutateAsync({
      topic: topic.trim(),
      deliverable_type: deliverableType,
      flow_plan: flowPlan,
      debate_depth: debateDepth,
      role_ids: selectedRoleIds,
      reference_meeting_ids: relatedIds,
      // 议题绑定仅在可绑定状态下携带（后端对非 open/scheduled 返回 409）
      ...(issueBindable && issueId ? { issue_id: issueId } : {}),
    });
    const meetingId = res.meeting_id;
    // 绑定成功后议题状态已变（→ in_progress），刷新议题池相关缓存
    if (issueBindable) {
      qc.invalidateQueries({ queryKey: projectKeys.all });
      qc.invalidateQueries({ queryKey: issueKeys.all });
    }
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
    return meetingId;
  };

  /** 发起会议：创建 → 上传 → 运行 → 进入会议页 */
  const handleStart = async (e?: React.FormEvent) => {
    e?.preventDefault();
    if (isLaunching || !validateTopic()) return;
    try {
      const meetingId = await createAndUpload();
      setLaunchPhase('running');
      await runMeeting.mutateAsync(meetingId);
      toast({ title: '讨论已启动', description: truncate(topic, 50) });
      navigate(`/meeting/${meetingId}`);
    } catch (e: unknown) {
      toast({ title: '启动失败', description: (e as Error).message, variant: 'error' });
    } finally {
      setLaunchPhase('idle');
      setUploadProgress(null);
    }
  };

  /** 保存草稿：只创建不运行（POST /meetings 不触发 /run），回到列表页 */
  const handleSaveDraft = async () => {
    if (isLaunching || !validateTopic()) return;
    try {
      await createAndUpload();
      toast({ title: '草稿已保存', description: '议题已创建，可在列表中随时启动' });
      navigate(backPath);
    } catch (e: unknown) {
      toast({ title: '保存失败', description: (e as Error).message, variant: 'error' });
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
          : '发起会议';

  return (
    <div className="mx-auto flex min-h-full max-w-5xl flex-col px-8 pt-6">
      {/* 页头：返回 + 标题 */}
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => navigate(backPath)}
          className="rounded-md p-1.5 text-text-tertiary transition-colors hover:bg-bg-tertiary hover:text-text-secondary"
          aria-label="返回列表"
        >
          <ChevronLeftIcon size={16} />
        </button>
        <h1 className="text-lg font-semibold text-text-primary">
          {issueId ? '从议题发起' : fromId ? '复用议题' : '新建议题'}
        </h1>
      </div>

      {/* 复用来源提示条 */}
      {fromId && (
        <div className="mt-3 flex items-center gap-2 rounded-md border border-border-soft bg-bg-secondary/60 px-3 py-2 text-xs text-text-secondary">
          <LinkIcon size={12} className="flex-shrink-0 text-text-tertiary" />
          <span className="min-w-0 flex-1 truncate">
            正在复用：{fromMeeting ? truncate(fromMeeting.title, 60) : '加载中...'}
          </span>
        </div>
      )}

      {/* 议题池来源提示条（?issue= 入口）：可绑定 → 品牌色；不可绑定 → 警示色 */}
      {issueId && (
        <div
          className={cn(
            'mt-3 flex items-center gap-2 rounded-md border px-3 py-2 text-xs',
            issue && !issueBindable
              ? 'border-danger/30 bg-danger/5 text-danger'
              : 'border-brand-500/30 bg-brand-soft text-brand-600',
          )}
        >
          <LinkIcon size={12} className="flex-shrink-0 opacity-70" />
          <span className="min-w-0 flex-1 truncate">
            {!issue
              ? '议题加载中...'
              : issueBindable
                ? `从议题发起：${truncate(issue.title, 60)}（发起后议题将转为进行中）`
                : `议题「${truncate(issue.title, 40)}」当前状态不可绑定会议，将按普通会议创建`}
          </span>
        </div>
      )}

      {/* 双栏主体：左编辑区 + 右配置栏 */}
      <form onSubmit={handleStart} className="mt-4 grid flex-1 gap-6 pb-6 lg:grid-cols-[minmax(0,1fr)_300px]">
        {/* 左主栏：议题编辑 */}
        <div className="min-w-0">
          <label htmlFor="topic-input" className="mb-1.5 block text-xs font-medium text-text-secondary">
            议题描述
          </label>
          <div className="relative">
            <Textarea
              ref={textareaRef}
              id="topic-input"
              value={topic}
              onChange={(e) => {
                setTopic(e.target.value);
                if (topicError && e.target.value.trim()) setTopicError('');
              }}
              placeholder={'描述你想讨论的议题或问题...\n例如：分析微服务架构中服务间通信的最佳实践，对比 gRPC 和 REST 的适用场景'}
              className="min-h-[320px] max-w-[72ch] text-[15px] leading-relaxed"
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

          {/* 润色工具行 */}
          <div className="mt-2 flex items-center gap-1">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={handlePolish}
              disabled={!topic.trim() || isPolishing || isLaunching}
              className="h-7 gap-1 text-xs"
            >
              {isPolishing ? <SpinnerIcon size={12} className="animate-spin" /> : <WandIcon size={12} />}
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
            <span className="ml-2 text-[11px] text-text-tertiary">{topic.length} 字</span>
          </div>
        </div>

        {/* 右侧栏：启动参数 / 参与角色 / 参考文档 */}
        <aside className="space-y-4">
          <section className="rounded-lg border border-border-soft bg-bg-primary p-3">
            <h2 className="mb-2 text-xs font-medium text-text-secondary">启动参数</h2>
            <div className="space-y-2.5">
              <OptionSelect label="产出类型" value={deliverableType} onChange={setDeliverableType} options={DELIVERABLE_TYPES} disabled={isLaunching} />
              <OptionSelect label="执行模式" value={flowPlan} onChange={setFlowPlan} options={FLOW_PLANS} disabled={isLaunching} />
              <OptionSelect label="辩论深度" value={debateDepth} onChange={setDebateDepth} options={DEBATE_DEPTHS} disabled={isLaunching} />
            </div>
          </section>

          <section className="rounded-lg border border-border-soft bg-bg-primary p-3">
            <div className="mb-1.5 flex items-center justify-between">
              <h2 className="text-xs font-medium text-text-secondary">参与角色</h2>
              <span className="text-[11px] text-text-tertiary">
                {selectedRoleIds.length === 0 ? '默认全部活跃角色' : `已选 ${selectedRoleIds.length} 个`}
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
          </section>

          <section className="rounded-lg border border-border-soft bg-bg-primary p-3">
            <div className="flex items-center justify-between">
              <h2 className="text-xs font-medium text-text-secondary">参考文档</h2>
              <span className="text-[11px] text-text-tertiary">
                {UPLOAD_ALLOWED_EXTENSIONS.join(' ')} · 单个 ≤ {UPLOAD_MAX_SIZE_MB}MB
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
          </section>
        </aside>
      </form>

      {/* 底部操作条：吸底（main 为滚动容器，sticky 生效） */}
      <div className="sticky bottom-0 -mx-8 border-t border-border-default bg-bg-primary/95 px-8 py-3 backdrop-blur">
        <div className="mx-auto flex max-w-5xl items-center justify-between">
          <span className="text-[11px] text-text-tertiary">Ctrl+Enter 快速发起</span>
          <div className="flex items-center gap-2">
            <Button type="button" variant="ghost" size="sm" disabled={isLaunching} onClick={() => navigate(backPath)}>
              取消
            </Button>
            <Button type="button" variant="outline" size="sm" disabled={!topic.trim() || isLaunching} onClick={handleSaveDraft}>
              保存草稿
            </Button>
            {/* 主按钮空态不禁用：点击触发 validateTopic 行内错误提示（表单校验范式），
                禁用态无任何反馈渠道，不符合可访问性要求 */}
            <Button type="button" size="sm" disabled={isLaunching} onClick={() => handleStart()}>
              {isLaunching ? (
                <SpinnerIcon size={12} className="mr-1 animate-spin" />
              ) : (
                <PlayIcon size={12} className="mr-1" />
              )}
              {launchButtonText}
            </Button>
          </div>
        </div>
      </div>
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
