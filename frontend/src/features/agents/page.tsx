import * as React from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { FieldError } from '@/components/ui/form-feedback';
import { Skeleton } from '@/components/ui/skeleton';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { ScrollArea } from '@/components/ui/scroll-area';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog';
import {
  AgentAvatar,
  PlusIcon,
  EditIcon,
  TrashIcon,
  BrainIcon,
  XIcon,
  CheckIcon,
  SpinnerIcon,
  SparklesIcon,
} from '@/components/ui/svg-icons';
import { api } from '@/lib/api';
import { toast } from '@/hooks/use-toast';
import { cn } from '@/lib/utils';

// ============================================================
// Types — 与后端 AgentRole 模型对齐
// ============================================================

interface AgentRole {
  id: string;
  display_name: string;
  perspective: string;
  expertise_domains: string[];
  risk_appetite: string;
  default_stance: string;
  evidence_preference: string;
  model_override: string;
  background_brief: string;
  prompt_template: string;
  is_builtin: boolean;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

interface AgentRoleListResponse {
  roles: AgentRole[];
  total: number;
}

interface GenerateRolesResponse {
  roles: AgentRole[];
  generated_at: string;
}

interface UpsertRoleResponse {
  role: AgentRole;
}

// Skill —— 与后端 GET /skills/list 返回结构对齐
interface Skill {
  name: string;
  description: string;
  triggers: string[];
  scopes: string[];
}

interface SkillListResponse {
  skills: Skill[];
}

// ============================================================
// 常量
// ============================================================

const ROLE_OPTIONS = [
  { value: 'moderator', label: '主持人' },
  { value: 'product_architect', label: '产品架构师' },
  { value: 'engineer', label: '工程师' },
  { value: 'security_expert', label: '安全专家' },
  { value: 'ux_designer', label: 'UX设计师' },
  { value: 'data_engineer', label: '数据工程师' },
  { value: 'custom', label: '自定义' },
] as const;

type RoleType = (typeof ROLE_OPTIONS)[number]['value'];

const ROLE_LABEL_MAP: Record<string, string> = ROLE_OPTIONS.reduce(
  (acc, r) => ({ ...acc, [r.value]: r.label }),
  {} as Record<string, string>
);

const COLOR_PRESETS = [
  { value: '#5b6cff', name: 'blue' },
  { value: '#6b4fa0', name: 'purple' },
  { value: '#3a8a5c', name: 'green' },
  { value: '#b05050', name: 'red' },
  { value: '#9b6bb5', name: 'pink' },
  { value: '#6b5b95', name: 'indigo' },
  { value: '#b87d2b', name: 'orange' },
  { value: '#335c8e', name: 'brand' },
];

// 根据 role id 稳定映射颜色（内置角色使用品牌色板，自定义角色 hash）
function getRoleColor(id: string): string {
  const builtinColors: Record<string, string> = {
    moderator: '#335c8e',
    product_architect: '#5b6cff',
    engineer: '#3a8a5c',
    security_expert: '#b05050',
    ux_designer: '#9b6bb5',
    data_engineer: '#b87d2b',
  };
  if (builtinColors[id]) return builtinColors[id];
  // 自定义角色 hash 到 8 个预设色之一
  let hash = 0;
  for (let i = 0; i < id.length; i++) {
    hash = id.charCodeAt(i) + ((hash << 5) - hash);
  }
  return COLOR_PRESETS[Math.abs(hash) % COLOR_PRESETS.length].value;
}

// 判断角色类型（内置 or 自定义）
const BUILTIN_ROLE_IDS: RoleType[] = ['moderator', 'product_architect', 'engineer', 'security_expert', 'ux_designer', 'data_engineer'];

function getRoleType(id: string): RoleType {
  return (BUILTIN_ROLE_IDS as string[]).includes(id) ? (id as RoleType) : 'custom';
}

// 生成角色简短描述（优先 perspective，其次 background_brief）
function getRoleDescription(role: AgentRole): string {
  if (role.perspective) return role.perspective;
  if (role.background_brief) return role.background_brief;
  return '暂无描述';
}

// 从中文名生成英文 id（slug）
function slugify(name: string): string {
  const map: Record<string, string> = {
    '主持人': 'moderator', '产品': 'product', '架构': 'architect', '工程': 'engineer',
    '安全': 'security', '设计': 'designer', '数据': 'data', '分析': 'analyst',
    '测试': 'qa', '运维': 'devops', '前端': 'frontend', '后端': 'backend',
    '全栈': 'fullstack', 'AI': 'ai', '算法': 'algo',
  };
  for (const [cn, en] of Object.entries(map)) {
    if (name.includes(cn)) return en;
  }
  // fallback: pinyin-like ascii slug
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .slice(0, 30) || `custom_${Date.now().toString(36)}`;
}

// ============================================================
// Query Keys
// ============================================================

const roleKeys = {
  all: ['agent-roles'] as const,
  list: () => [...roleKeys.all, 'list'] as const,
};

// ============================================================
// Toggle Switch 组件（内联简单开关）
// ============================================================

function Toggle({
  checked,
  onChange,
  disabled,
  size = 'md',
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
  size?: 'sm' | 'md';
}) {
  const w = size === 'sm' ? 'w-8' : 'w-9';
  const h = size === 'sm' ? 'h-4' : 'h-5';
  const dot = size === 'sm' ? 'h-3 w-3' : 'h-4 w-4';
  const translate = size === 'sm' ? 'translate-x-4' : 'translate-x-4';
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cn(
        'relative inline-flex shrink-0 cursor-pointer items-center rounded-full transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500/30 disabled:cursor-not-allowed disabled:opacity-50',
        w,
        h,
        checked ? 'bg-brand-500' : 'bg-bg-tertiary'
      )}
    >
      <span
        className={cn(
          'inline-block rounded-full bg-white shadow-sm transition-transform duration-150',
          dot,
          checked ? translate : 'translate-x-0.5'
        )}
      />
    </button>
  );
}

// ============================================================
// 主页面组件
// ============================================================

export default function AgentsPage() {
  const qc = useQueryClient();

  // --- Dialog 状态 ---
  const [createOpen, setCreateOpen] = React.useState(false);
  const [editingRole, setEditingRole] = React.useState<AgentRole | null>(null);
  const [deleteRole, setDeleteRole] = React.useState<AgentRole | null>(null);
  const [generateOpen, setGenerateOpen] = React.useState(false);

  // --- 列表查询 ---
  const {
    data: rolesData,
    isLoading,
    isError,
  } = useQuery({
    queryKey: roleKeys.list(),
    queryFn: () => api.get<AgentRoleListResponse>('/agent-roles'),
  });

  const roles = Array.isArray(rolesData?.roles) ? rolesData.roles : [];

  // --- 创建 Mutation ---
  const createMutation = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api.post<UpsertRoleResponse>('/agent-roles', body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: roleKeys.all });
      toast({ title: '创建成功', description: '新角色已添加' });
      setCreateOpen(false);
    },
    onError: (err: Error) => {
      toast({ title: '创建失败', description: err.message, variant: 'error' });
    },
  });

  // --- 更新 Mutation ---
  const updateMutation = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Record<string, unknown> }) =>
      api.put<UpsertRoleResponse>(`/agent-roles/${id}`, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: roleKeys.all });
      toast({ title: '更新成功', description: '角色已更新' });
      setEditingRole(null);
    },
    onError: (err: Error) => {
      toast({ title: '更新失败', description: err.message, variant: 'error' });
    },
  });

  // --- 删除 Mutation ---
  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.delete(`/agent-roles/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: roleKeys.all });
      toast({ title: '删除成功', description: '角色已移除' });
      setDeleteRole(null);
    },
    onError: (err: Error) => {
      toast({ title: '删除失败', description: err.message, variant: 'error' });
    },
  });

  // --- 切换启用/停用 ---
  const toggleActive = (role: AgentRole) => {
    // 乐观更新
    qc.setQueryData<AgentRoleListResponse>(roleKeys.list(), (old) => {
      if (!old || !Array.isArray(old.roles)) return old;
      return {
        ...old,
        roles: old.roles.map((r) =>
          r.id === role.id ? { ...r, is_active: !r.is_active } : r
        ),
      };
    });
    // PUT 全量更新（后端目前不直接支持 is_active 变更，但发送完整 body 以兼容未来更新）
    updateMutation.mutate({
      id: role.id,
      body: {
        id: role.id,
        display_name: role.display_name,
        perspective: role.perspective,
        expertise_domains: role.expertise_domains,
        risk_appetite: role.risk_appetite,
        default_stance: role.default_stance,
        evidence_preference: role.evidence_preference,
        model_override: role.model_override,
        background_brief: role.background_brief,
        prompt_template: role.prompt_template,
      },
    });
  };

  // ============================================================
  // Render
  // ============================================================

  return (
    <div className="mx-auto max-w-6xl pt-6 px-8 pb-8">
      {/* ---- Header ---- */}
      <div className="mb-6 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-text-primary">Agent 角色管理</h1>
          <p className="mt-1 text-sm text-text-tertiary">
            配置参与会议讨论的 AI Agent 角色、人设和能力
          </p>
        </div>
      </div>

      {/* ---- Tabs ---- */}
      <Tabs defaultValue="roles" className="w-full">
        <TabsList className="mb-4">
          <TabsTrigger value="roles" className="gap-1.5">
            <BrainIcon size={14} />
            角色
          </TabsTrigger>
          <TabsTrigger value="skills" className="gap-1.5">
            <SparklesIcon size={14} />
            Skills
          </TabsTrigger>
        </TabsList>

        <TabsContent value="roles">
          <div className="mb-4 flex items-center justify-end gap-2">
            <Button variant="outline" onClick={() => setGenerateOpen(true)}>
              <BrainIcon size={14} />
              AI 生成
            </Button>
            <Button onClick={() => setCreateOpen(true)}>
              <PlusIcon size={14} />
              新建角色
            </Button>
          </div>

          {/* ---- Content ---- */}
          {isLoading ? (
        <LoadingGrid />
      ) : isError ? (
        <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-border-default py-16 text-center">
          <p className="text-sm text-danger">加载角色列表失败</p>
          <Button
            variant="outline"
            size="sm"
            className="mt-3"
            onClick={() => qc.invalidateQueries({ queryKey: roleKeys.all })}
          >
            重试
          </Button>
        </div>
      ) : roles.length === 0 ? (
        <EmptyState onCreate={() => setCreateOpen(true)} onGenerate={() => setGenerateOpen(true)} />
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
          {roles.map((role) => {
            const color = getRoleColor(role.id);
            const roleType = getRoleType(role.id);
            return (
              <Card
                key={role.id}
                className="group transition-all duration-150 hover:border-brand-500/30 hover:shadow-md"
              >
                <CardHeader className="pb-2">
                  <div className="flex items-start gap-3">
                    <AgentAvatar
                      agentId={role.id}
                      agentName={role.display_name}
                      role={roleType !== 'custom' ? roleType : undefined}
                      color={color}
                      size={40}
                      className="shrink-0"
                    />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <CardTitle className="truncate text-sm font-medium">
                          {role.display_name}
                        </CardTitle>
                        {role.is_builtin && (
                          <Badge variant="secondary" className="shrink-0">
                            内置
                          </Badge>
                        )}
                      </div>
                      <div className="mt-1">
                        <Badge
                          variant="outline"
                          className="text-[10px]"
                          style={{ borderColor: color + '40', color }}
                        >
                          {ROLE_LABEL_MAP[roleType] || roleType}
                        </Badge>
                      </div>
                    </div>
                  </div>
                </CardHeader>
                <CardContent className="pb-3">
                  <p className="line-clamp-2 text-xs leading-relaxed text-text-secondary">
                    {getRoleDescription(role)}
                  </p>
                  {Array.isArray(role.expertise_domains) && role.expertise_domains.length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1">
                      {role.expertise_domains.slice(0, 3).map((tag) => (
                        <span
                          key={tag}
                          className="rounded bg-bg-tertiary px-1.5 py-0.5 text-[10px] text-text-tertiary"
                        >
                          {tag}
                        </span>
                      ))}
                    </div>
                  )}
                  <div className="mt-3 flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <Toggle
                        checked={role.is_active}
                        onChange={() => toggleActive(role)}
                        disabled={updateMutation.isPending}
                        size="sm"
                      />
                      <span className="text-[11px] text-text-tertiary">
                        {role.is_active ? '启用' : '停用'}
                      </span>
                    </div>
                    <div className="flex items-center gap-0.5 opacity-0 transition-opacity group-hover:opacity-100">
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-7 w-7 p-0"
                        onClick={() => setEditingRole(role)}
                        title="编辑"
                      >
                        <EditIcon size={13} />
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        className={cn(
                          'h-7 w-7 p-0',
                          !role.is_builtin && 'hover:bg-danger/10 hover:text-danger'
                        )}
                        onClick={() => setDeleteRole(role)}
                        disabled={role.is_builtin}
                        title={role.is_builtin ? '内置角色不可删除' : '删除'}
                      >
                        <TrashIcon size={13} />
                      </Button>
                    </div>
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}
        </TabsContent>

        <TabsContent value="skills">
          <SkillsTab />
        </TabsContent>
      </Tabs>

      {/* ---- 创建 / 编辑 Dialog ---- */}
      <RoleFormDialog
        open={createOpen || editingRole !== null}
        role={editingRole}
        onOpenChange={(open) => {
          if (!open) {
            setCreateOpen(false);
            setEditingRole(null);
          }
        }}
        onSubmit={(form) => {
          const roleType = form.roleType;
          const roleId = editingRole
            ? editingRole.id
            : roleType !== 'custom'
              ? roleType
              : `${slugify(form.name)}_${Date.now().toString(36).slice(0, 4)}`;
          const body = {
            id: roleId,
            display_name: form.name,
            perspective: form.description,
            expertise_domains: form.expertise_domains,
            risk_appetite: 'balanced',
            default_stance: '',
            evidence_preference: 'balanced',
            model_override: '',
            background_brief: form.description,
            prompt_template: form.systemPrompt,
          };
          if (editingRole) {
            updateMutation.mutate({ id: editingRole.id, body });
          } else {
            createMutation.mutate(body);
          }
        }}
        isSubmitting={createMutation.isPending || updateMutation.isPending}
      />

      {/* ---- 删除确认 Dialog ---- */}
      <Dialog open={deleteRole !== null} onOpenChange={(o) => !o && setDeleteRole(null)}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>确认删除</DialogTitle>
            <DialogDescription>
              确定要删除角色 "{deleteRole?.display_name}" 吗？此操作不可撤销。
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteRole(null)}>
              取消
            </Button>
            <Button
              variant="destructive"
              onClick={() => deleteRole && deleteMutation.mutate(deleteRole.id)}
              disabled={deleteMutation.isPending}
            >
              {deleteMutation.isPending && <SpinnerIcon size={13} />}
              删除
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ---- AI 生成 Dialog ---- */}
      <GenerateDialog
        open={generateOpen}
        onOpenChange={setGenerateOpen}
        onCreated={() => qc.invalidateQueries({ queryKey: roleKeys.all })}
      />
    </div>
  );
}

// ============================================================
// Loading 骨架
// ============================================================

function LoadingGrid() {
  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
      {Array.from({ length: 6 }).map((_, i) => (
        <Card key={i}>
          <CardHeader className="pb-2">
            <div className="flex items-start gap-3">
              <Skeleton className="h-10 w-10 rounded-full" />
              <div className="flex-1 space-y-2">
                <Skeleton className="h-4 w-24" />
                <Skeleton className="h-3 w-16" />
              </div>
            </div>
          </CardHeader>
          <CardContent>
            <Skeleton className="h-3 w-full" />
            <Skeleton className="mt-1.5 h-3 w-4/5" />
            <div className="mt-3 flex items-center justify-between">
              <Skeleton className="h-4 w-14" />
              <Skeleton className="h-7 w-16" />
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

// ============================================================
// 空状态
// ============================================================

function EmptyState({ onCreate, onGenerate }: { onCreate: () => void; onGenerate: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-border-default py-20 text-center">
      <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-bg-tertiary">
        <AgentAvatar agentId="empty" agentName="空" size={36} color="#335c8e" />
      </div>
      <h3 className="text-sm font-medium text-text-primary">暂无角色</h3>
      <p className="mt-1 text-xs text-text-tertiary">手动创建角色，或使用 AI 根据议题自动生成</p>
      <div className="mt-4 flex gap-2">
        <Button variant="outline" size="sm" onClick={onGenerate}>
          <BrainIcon size={13} />
          AI 生成
        </Button>
        <Button size="sm" onClick={onCreate}>
          <PlusIcon size={13} />
          新建角色
        </Button>
      </div>
    </div>
  );
}

// ============================================================
// 创建/编辑表单 Dialog
// ============================================================

interface RoleFormData {
  name: string;
  roleType: RoleType;
  description: string;
  systemPrompt: string;
  color: string;
  expertise_domains: string[];
}

function RoleFormDialog({
  open,
  role,
  onOpenChange,
  onSubmit,
  isSubmitting,
}: {
  open: boolean;
  role: AgentRole | null;
  onOpenChange: (open: boolean) => void;
  onSubmit: (data: RoleFormData) => void;
  isSubmitting: boolean;
}) {
  const isEdit = !!role;
  const [name, setName] = React.useState('');
  const [nameError, setNameError] = React.useState('');
  const [roleType, setRoleType] = React.useState<RoleType>('custom');
  const [description, setDescription] = React.useState('');
  const [systemPrompt, setSystemPrompt] = React.useState('');
  const [color, setColor] = React.useState(COLOR_PRESETS[7].value); // brand default
  const [domainsText, setDomainsText] = React.useState('');

  // 编辑时回填
  React.useEffect(() => {
    if (open && role) {
      setName(role.display_name);
      setRoleType(getRoleType(role.id));
      setDescription(role.perspective || role.background_brief);
      setSystemPrompt(role.prompt_template);
      setColor(getRoleColor(role.id));
      setDomainsText(role.expertise_domains.join(', '));
    } else if (open && !role) {
      setName('');
      setRoleType('custom');
      setDescription('');
      setSystemPrompt('');
      setColor(COLOR_PRESETS[7].value);
      setDomainsText('');
    }
    if (open) setNameError('');
  }, [open, role]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) {
      setNameError('请填写角色名称');
      return;
    }
    setNameError('');
    const domains = domainsText
      .split(/[,，、\s]+/)
      .map((s) => s.trim())
      .filter(Boolean);
    onSubmit({
      name: name.trim(),
      roleType,
      description: description.trim(),
      systemPrompt: systemPrompt.trim(),
      color,
      expertise_domains: domains,
    });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>{isEdit ? '编辑角色' : '新建角色'}</DialogTitle>
          <DialogDescription>
            {isEdit ? '修改角色的人设和配置' : '创建一个新的 AI Agent 角色'}
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4 px-6 py-5">
          {/* 预览头像 */}
          <div className="flex items-center gap-3 rounded-lg bg-bg-tertiary/50 p-3">
            <AgentAvatar
              agentId={role?.id || name || 'new'}
              agentName={name || '新角色'}
              role={roleType !== 'custom' ? roleType : undefined}
              color={color}
              size={48}
            />
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium text-text-primary">
                {name || '新角色'}
              </p>
              <p className="text-xs text-text-tertiary">
                {ROLE_LABEL_MAP[roleType] || '自定义'}
              </p>
            </div>
          </div>

          {/* 名称 */}
          <div className="space-y-1.5">
            <label htmlFor="role-name" className="text-sm font-medium text-text-secondary">角色名称</label>
            <Input
              id="role-name"
              className="h-9 text-sm"
              value={name}
              onChange={(e) => {
                setName(e.target.value);
                if (nameError && e.target.value.trim()) setNameError('');
              }}
              placeholder="例如：安全审计员"
              maxLength={50}
              aria-invalid={!!nameError}
              aria-describedby={nameError ? 'role-name-error' : undefined}
            />
            <FieldError id="role-name-error">{nameError}</FieldError>
          </div>

          {/* 角色类型 */}
          <div className="space-y-1.5">
            <label htmlFor="role-type" className="text-sm font-medium text-text-secondary">角色类型</label>
            <select
              id="role-type"
              value={roleType}
              onChange={(e) => setRoleType(e.target.value as RoleType)}
              disabled={isEdit && role?.is_builtin}
              className="flex h-9 w-full rounded-md border border-border-default bg-bg-primary px-3 text-sm text-text-primary focus-visible:outline-none focus-visible:border-brand-500/50 focus-visible:ring-2 focus-visible:ring-brand-500/10 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {ROLE_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>

          {/* 颜色 */}
          <div className="space-y-1.5">
            <span id="role-color-label" className="text-sm font-medium text-text-secondary">标识颜色</span>
            <div role="group" aria-labelledby="role-color-label" className="flex items-center gap-2">
              {COLOR_PRESETS.map((c) => (
                <button
                  key={c.value}
                  type="button"
                  onClick={() => setColor(c.value)}
                  className={cn(
                    'h-7 w-7 rounded-full border-2 transition-all',
                    color === c.value
                      ? 'border-text-primary scale-110 shadow-sm'
                      : 'border-transparent hover:scale-105'
                  )}
                  style={{ backgroundColor: c.value }}
                  title={c.name}
                  aria-label={c.name}
                  aria-pressed={color === c.value}
                />
              ))}
            </div>
          </div>

          {/* 专业领域 */}
          <div className="space-y-1.5">
            <label htmlFor="role-domains" className="text-sm font-medium text-text-secondary">专业领域（逗号分隔）</label>
            <Input
              id="role-domains"
              className="h-9 text-sm"
              value={domainsText}
              onChange={(e) => setDomainsText(e.target.value)}
              placeholder="例如：安全审计, 渗透测试, 合规"
            />
          </div>

          {/* 描述 */}
          <div className="space-y-1.5">
            <label htmlFor="role-description" className="text-sm font-medium text-text-secondary">角色描述</label>
            <Textarea
              id="role-description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="描述这个角色的核心视角和职责..."
              rows={2}
              className="min-h-[60px] resize-y border-border-default bg-bg-primary text-sm focus-visible:border-brand-500/50 focus-visible:ring-2 focus-visible:ring-brand-500/10"
            />
          </div>

          {/* System Prompt */}
          <div className="space-y-1.5">
            <label htmlFor="role-system-prompt" className="text-sm font-medium text-text-secondary">系统提示词 (System Prompt)</label>
            <Textarea
              id="role-system-prompt"
              value={systemPrompt}
              onChange={(e) => setSystemPrompt(e.target.value)}
              placeholder="定义该角色的完整系统提示词..."
              rows={5}
              className="min-h-[100px] resize-y border-border-default bg-bg-primary text-sm focus-visible:border-brand-500/50 focus-visible:ring-2 focus-visible:ring-brand-500/10"
            />
          </div>
        </form>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isSubmitting}>
            取消
          </Button>
          <Button onClick={handleSubmit} disabled={isSubmitting}>
            {isSubmitting && <SpinnerIcon size={13} />}
            {isEdit ? '保存修改' : '创建角色'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ============================================================
// AI 生成 Dialog
// ============================================================

function GenerateDialog({
  open,
  onOpenChange,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: () => void;
}) {
  const qc = useQueryClient();
  const [topic, setTopic] = React.useState('');
  const [generatedRoles, setGeneratedRoles] = React.useState<AgentRole[]>([]);
  const [accepted, setAccepted] = React.useState<Set<string>>(new Set());

  const generateMutation = useMutation({
    mutationFn: (t: string) =>
      api.post<GenerateRolesResponse>('/agent-roles/generate', { topic: t }),
    onSuccess: (data) => {
      const roles = Array.isArray(data?.roles) ? data.roles : [];
      setGeneratedRoles(roles);
      setAccepted(new Set(roles.map((r) => r.id)));
    },
    onError: (err: Error) => {
      toast({ title: '生成失败', description: err.message, variant: 'error' });
    },
  });

  const createBulkMutation = useMutation({
    mutationFn: async (roles: AgentRole[]) => {
      const results: AgentRole[] = [];
      for (const r of roles) {
        try {
          const res = await api.post<UpsertRoleResponse>('/agent-roles', {
            id: r.id.startsWith('gen-') ? `${slugify(r.display_name)}_${Date.now().toString(36).slice(0, 4)}` : r.id,
            display_name: r.display_name,
            perspective: r.perspective,
            expertise_domains: r.expertise_domains,
            risk_appetite: r.risk_appetite || 'balanced',
            default_stance: r.default_stance,
            evidence_preference: r.evidence_preference || 'balanced',
            model_override: r.model_override || '',
            background_brief: r.background_brief,
            prompt_template: r.prompt_template,
          });
          results.push(res.role);
        } catch {
          // 跳过已存在的内置角色（409 冲突）
        }
      }
      return results;
    },
    onSuccess: (created) => {
      qc.invalidateQueries({ queryKey: roleKeys.all });
      toast({ title: '已添加角色', description: `成功添加 ${created.length} 个角色` });
      onOpenChange(false);
      setTopic('');
      setGeneratedRoles([]);
      setAccepted(new Set());
      onCreated();
    },
    onError: (err: Error) => {
      toast({ title: '创建失败', description: err.message, variant: 'error' });
    },
  });

  const toggleAccept = (id: string) => {
    setAccepted((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const [topicError, setTopicError] = React.useState('');

  const handleGenerate = () => {
    if (!topic.trim()) {
      setTopicError('请输入会议议题');
      return;
    }
    setTopicError('');
    setGeneratedRoles([]);
    setAccepted(new Set());
    generateMutation.mutate(topic.trim());
  };

  const handleAcceptAll = () => {
    const toCreate = generatedRoles.filter((r) => accepted.has(r.id));
    if (toCreate.length === 0) {
      toast({ title: '请至少选择一个角色', variant: 'error' });
      return;
    }
    createBulkMutation.mutate(toCreate);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <BrainIcon size={16} />
            AI 生成角色
          </DialogTitle>
          <DialogDescription>输入会议议题，AI 将自动推荐合适的角色阵容</DialogDescription>
        </DialogHeader>

        <div className="space-y-4 px-6 py-5">
          {/* 输入区 */}
          <div className="space-y-1.5">
            <div className="flex gap-2">
              <Input
                className="h-9 text-sm"
                value={topic}
                onChange={(e) => {
                  setTopic(e.target.value);
                  if (topicError && e.target.value.trim()) setTopicError('');
                }}
                placeholder="例如：讨论微服务架构下的分布式事务方案"
                onKeyDown={(e) => e.key === 'Enter' && !generateMutation.isPending && handleGenerate()}
                aria-invalid={!!topicError}
                aria-describedby={topicError ? 'generate-topic-error' : undefined}
              />
              <Button
                size="sm"
                onClick={handleGenerate}
                disabled={generateMutation.isPending || !topic.trim()}
                className="shrink-0 h-9"
              >
                {generateMutation.isPending ? <SpinnerIcon size={13} /> : <BrainIcon size={13} />}
                生成
              </Button>
            </div>
            <FieldError id="generate-topic-error">{topicError}</FieldError>
          </div>

          {/* 生成结果 */}
          {generateMutation.isPending && (
            <div className="space-y-3 py-4">
              <Skeleton className="h-20 w-full rounded-lg" />
              <Skeleton className="h-20 w-full rounded-lg" />
              <Skeleton className="h-20 w-full rounded-lg" />
            </div>
          )}

          {generatedRoles.length > 0 && !generateMutation.isPending && (
            <div className="max-h-[400px] space-y-2 overflow-y-auto pr-1">
              <p className="text-xs text-text-tertiary">
                AI 推荐了 {generatedRoles.length} 个角色，勾选需要添加的角色：
              </p>
              {generatedRoles.map((r) => {
                const isAccepted = accepted.has(r.id);
                const color = getRoleColor(r.id);
                return (
                  <div
                    key={r.id}
                    className={cn(
                      'flex items-start gap-3 rounded-lg border p-3 transition-all',
                      isAccepted
                        ? 'border-brand-500/40 bg-brand-500/5'
                        : 'border-border-default bg-bg-primary opacity-60'
                    )}
                  >
                    <AgentAvatar
                      agentId={r.id}
                      agentName={r.display_name}
                      color={color}
                      size={36}
                      className="shrink-0"
                    />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-medium text-text-primary">
                          {r.display_name}
                        </span>
                        <Badge variant="outline" className="text-[10px]" style={{ color, borderColor: color + '40' }}>
                          {ROLE_LABEL_MAP[r.id] || r.id}
                        </Badge>
                      </div>
                      <p className="mt-0.5 line-clamp-2 text-xs text-text-secondary">
                        {r.perspective || r.background_brief}
                      </p>
                    </div>
                    <Button
                      variant={isAccepted ? 'default' : 'outline'}
                      size="sm"
                      className="shrink-0"
                      onClick={() => toggleAccept(r.id)}
                    >
                      {isAccepted ? <CheckIcon size={12} /> : <XIcon size={12} />}
                      {isAccepted ? '采纳' : '跳过'}
                    </Button>
                  </div>
                );
              })}
            </div>
          )}

          {generatedRoles.length === 0 && !generateMutation.isPending && (
            <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-border-default py-10 text-center">
              <BrainIcon size={28} className="text-text-tertiary" />
              <p className="mt-2 text-xs text-text-tertiary">输入议题后点击「生成」按钮</p>
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          {generatedRoles.length > 0 && (
            <Button
              onClick={handleAcceptAll}
              disabled={createBulkMutation.isPending || accepted.size === 0}
            >
              {createBulkMutation.isPending && <SpinnerIcon size={13} />}
              添加已选角色 ({accepted.size})
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ============================================================
// Skills 标签页 —— 展示后端加载的 Agent Skills
// ============================================================

function SkillsTab() {
  const qc = useQueryClient();

  const { data, isLoading, isError } = useQuery({
    queryKey: ['agent-skills', 'list'],
    queryFn: () => api.get<SkillListResponse>('/skills/list'),
  });

  const skills = Array.isArray(data?.skills) ? data.skills : [];

  // 加载中
  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-20 text-text-tertiary">
        <SpinnerIcon size={20} />
        <span className="ml-2 text-sm">加载 Skills 中...</span>
      </div>
    );
  }

  // 加载失败
  if (isError) {
    return (
      <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-border-default py-16 text-center">
        <p className="text-sm text-danger">加载 Skills 列表失败</p>
        <Button
          variant="outline"
          size="sm"
          className="mt-3"
          onClick={() => qc.invalidateQueries({ queryKey: ['agent-skills', 'list'] })}
        >
          重试
        </Button>
      </div>
    );
  }

  // 空状态
  if (skills.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-border-default py-20 text-center">
        <SparklesIcon size={28} className="text-text-tertiary" />
        <h3 className="mt-3 text-sm font-medium text-text-primary">暂无可用 Skill</h3>
        <p className="mt-1 text-xs text-text-tertiary">后端尚未加载任何 Agent Skill</p>
      </div>
    );
  }

  return (
    <ScrollArea className="h-[calc(100vh-240px)] min-h-[320px]">
      <div className="grid grid-cols-1 gap-4 pb-4 md:grid-cols-2 lg:grid-cols-3">
        {skills.map((skill) => (
          <Card
            key={skill.name}
            className="transition-all duration-150 hover:border-brand-500/30 hover:shadow-md"
          >
            <CardHeader className="pb-2">
              <div className="flex items-start gap-2">
                <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-brand-500/10 text-brand-500">
                  <SparklesIcon size={15} />
                </div>
                <CardTitle className="truncate pt-1 text-sm font-medium">
                  {skill.name}
                </CardTitle>
              </div>
            </CardHeader>
            <CardContent className="pb-3">
              <p className="line-clamp-3 text-xs leading-relaxed text-text-secondary">
                {skill.description || '暂无描述'}
              </p>

              {Array.isArray(skill.triggers) && skill.triggers.length > 0 && (
                <div className="mt-3">
                  <p className="mb-1 text-[10px] font-medium uppercase tracking-wide text-text-tertiary">
                    触发词
                  </p>
                  <div className="flex flex-wrap gap-1">
                    {skill.triggers.map((t) => (
                      <Badge key={t} variant="secondary" className="text-[10px]">
                        {t}
                      </Badge>
                    ))}
                  </div>
                </div>
              )}

              {Array.isArray(skill.scopes) && skill.scopes.length > 0 && (
                <div className="mt-2">
                  <p className="mb-1 text-[10px] font-medium uppercase tracking-wide text-text-tertiary">
                    适用范围
                  </p>
                  <div className="flex flex-wrap gap-1">
                    {skill.scopes.map((s) => (
                      <Badge key={s} variant="outline" className="text-[10px]">
                        {s}
                      </Badge>
                    ))}
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        ))}
      </div>
    </ScrollArea>
  );
}
