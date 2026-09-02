/**
 * Team（工作空间）管理页面。
 * 左侧 Team 列表，右侧成员管理/设置。
 */
import * as React from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useForm } from 'react-hook-form';
import {
  Users, Plus, Search, Shield, Ban, UserCheck, UserX,
  ChevronLeft, ChevronRight, MoreHorizontal, Building2, Crown,
  Settings as SettingsIcon, Loader2,
} from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { FieldError } from '@/components/ui/form-feedback';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel,
  DropdownMenuSeparator, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { Label } from '@/components/ui/label';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { useToast } from '@/hooks/use-toast';
import { useAuthStore } from '@/stores/auth-slice';
import { useRbac } from '@/hooks/use-rbac';
import { teamsApi } from '@/lib/teams-api';
import { TEAM_ROLE_META, type TeamDetail, type TeamMember, type TeamRole } from '@/types';

const PAGE_SIZE = 10;

function TeamListItem({ team, isActive, onClick }: { team: TeamDetail; isActive: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={
        'flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left transition ' +
        (isActive
          ? 'bg-brand-500/10 text-brand-600 dark:bg-brand-500/15 dark:text-brand-400'
          : 'text-text-secondary hover:bg-bg-tertiary hover:text-text-primary')
      }
    >
      <div className={'flex h-8 w-8 shrink-0 items-center justify-center rounded-md ' + (isActive ? 'bg-brand-500/20' : 'bg-bg-tertiary')}>
        <Building2 size={16} />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5">
          <span className="truncate text-sm font-medium">{team.name}</span>
          {team.my_role === 'owner' && <Crown size={12} className="shrink-0 text-amber-500" />}
        </div>
        <div className="truncate text-xs text-text-tertiary">
          {team.my_role ? TEAM_ROLE_META[team.my_role as TeamRole]?.label : ''}
        </div>
      </div>
    </button>
  );
}

function CreateTeamDialog({ open, onOpenChange, onCreated }: {
  open: boolean; onOpenChange: (o: boolean) => void; onCreated: (t: TeamDetail) => void;
}) {
  const form = useForm<{ name: string; slug: string; description: string }>({
    defaultValues: { name: '', slug: '', description: '' },
  });
  const { errors } = form.formState;
  const [submitting, setSubmitting] = React.useState(false);
  const { toast } = useToast();
  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const valid = await form.trigger();
    if (!valid) return;
    const { name, slug, description } = form.getValues();
    setSubmitting(true);
    try {
      const team = await teamsApi.createTeam({ name: name.trim(), slug: slug.trim() || undefined, description: description.trim() || undefined });
      toast({ title: 'Team 创建成功', variant: 'success' });
      onCreated(team); onOpenChange(false); form.reset();
    } catch (err) {
      toast({ title: '创建失败', description: (err as Error).message, variant: 'error' });
    } finally { setSubmitting(false); }
  };
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>创建新工作空间</DialogTitle>
          <DialogDescription>创建一个新的 Team，你将自动成为所有者。</DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} noValidate className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="t-name">名称</Label>
            <Input id="t-name" placeholder="例如：产品团队" maxLength={64}
              aria-invalid={!!errors.name}
              aria-describedby={errors.name ? 't-name-error' : undefined}
              {...form.register('name', {
                validate: (v) => v.trim().length > 0 || '请输入 Team 名称',
                onChange: (e) => {
                  // 输入后即时清除错误（与 reValidateMode: onChange 保持一致）
                  if (errors.name && e.target.value.trim()) form.clearErrors('name');
                },
              })} />
            <FieldError id="t-name-error">{errors.name?.message}</FieldError>
          </div>
          <div className="space-y-2">
            <Label htmlFor="t-slug">标识（可选）</Label>
            <Input id="t-slug" placeholder="留空自动生成" maxLength={64}
              {...form.register('slug', {
                onChange: (e) => {
                  // 仅允许小写字母/数字/连字符，非法字符即时替换
                  const v = e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, '-');
                  if (v !== e.target.value) form.setValue('slug', v);
                },
              })} />
          </div>
          <div className="space-y-2">
            <Label htmlFor="t-desc">描述（可选）</Label>
            <Input id="t-desc" placeholder="简单描述这个 Team" maxLength={200}
              {...form.register('description')} />
          </div>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>取消</Button>
            <Button type="submit" disabled={submitting}>
              {submitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}创建
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function InviteMemberDialog({ open, teamId, onOpenChange, onInvited }: {
  open: boolean; teamId: number; onOpenChange: (o: boolean) => void; onInvited: () => void;
}) {
  const [keyword, setKeyword] = React.useState('');
  const [selectedUser, setSelectedUser] = React.useState<{ user_id: number; username: string; display_name?: string } | null>(null);
  const [selectionError, setSelectionError] = React.useState('');
  const [role, setRole] = React.useState<TeamRole>('member');
  const [submitting, setSubmitting] = React.useState(false);
  const { toast } = useToast();
  const { assignableRoles } = useRbac();
  const { data: searchResults = [], isFetching } = useQuery({
    queryKey: ['users', 'search', keyword],
    queryFn: () => teamsApi.searchUsers(keyword, teamId, true, 8),
    enabled: keyword.trim().length >= 1,
    staleTime: 15_000,
  });
  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedUser) { setSelectionError('请先搜索并选择要添加的用户'); return; }
    setSelectionError('');
    setSubmitting(true);
    try {
      await teamsApi.addMember(teamId, { username: selectedUser.username, role });
      toast({ title: `已添加 ${selectedUser.username}`, variant: 'success' });
      onInvited(); onOpenChange(false);
      setKeyword(''); setSelectedUser(null); setRole('member');
    } catch (err) {
      toast({ title: '添加失败', description: (err as Error).message, variant: 'error' });
    } finally { setSubmitting(false); }
  };
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>添加成员</DialogTitle>
          <DialogDescription>通过用户名搜索并添加到当前 Team。</DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label>搜索用户</Label>
            <Input placeholder="输入用户名或昵称" value={keyword}
              onChange={(e) => { setKeyword(e.target.value); setSelectedUser(null); }} />
            {keyword.trim().length >= 1 && (
              <div className="max-h-48 overflow-y-auto rounded-md border border-border-default bg-bg-primary">
                {isFetching ? (
                  <div className="flex items-center justify-center py-6 text-sm text-text-tertiary">
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />搜索中...
                  </div>
                ) : searchResults.length === 0 ? (
                  <div className="py-6 text-center text-sm text-text-tertiary">未找到匹配的用户</div>
                ) : searchResults.map((u) => (
                  <button key={u.user_id} type="button" onClick={() => { setSelectedUser(u); setSelectionError(''); }}
                    className={'flex w-full items-center gap-3 px-3 py-2 text-left text-sm transition ' +
                      (selectedUser?.user_id === u.user_id ? 'bg-brand-500/10 text-brand-600' : 'hover:bg-bg-tertiary')}>
                    <div className="flex h-7 w-7 items-center justify-center rounded-full bg-bg-tertiary text-xs font-medium">
                      {(u.display_name || u.username).slice(0, 1).toUpperCase()}
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="truncate font-medium">{u.display_name || u.username}</div>
                      <div className="truncate text-xs text-text-tertiary">@{u.username}</div>
                    </div>
                  </button>
                ))}
              </div>
            )}
            <FieldError>{selectionError}</FieldError>
          </div>
          <div className="space-y-2">
            <Label>角色</Label>
            <Select value={role} onValueChange={(v) => setRole(v as TeamRole)}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                {assignableRoles.map((r) => (
                  <SelectItem key={r} value={r}>{TEAM_ROLE_META[r].label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>取消</Button>
            <Button type="submit" disabled={submitting || !selectedUser}>
              {submitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}添加
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function MemberRowActions({ member, teamId, onChanged, myRole: _myRole }: {
  member: TeamMember; teamId: number; onChanged: () => void; myRole: TeamRole | '';
}) {
  const { canManage, assignableRoles } = useRbac();
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const currentUid = useAuthStore((s) => s.user?.id);
  const isSelf = String(member.user_id) === String(currentUid);
  const isOwner = member.role === 'owner';
  const canAct = !isSelf && !isOwner && canManage(member.role);

  const changeRoleMutation = useMutation({
    mutationFn: (newRole: TeamRole) => teamsApi.updateMemberRole(teamId, member.user_id, newRole),
    onSuccess: () => {
      toast({ title: '角色已更新', variant: 'success' });
      queryClient.invalidateQueries({ queryKey: ['team-members', teamId] });
      onChanged();
    },
    onError: (err: Error) => toast({ title: '操作失败', description: err.message, variant: 'error' }),
  });
  const banMutation = useMutation({
    mutationFn: () => teamsApi.banMember(teamId, member.user_id),
    onSuccess: () => {
      toast({ title: `已封禁 ${member.username}`, variant: 'success' });
      queryClient.invalidateQueries({ queryKey: ['team-members', teamId] });
      onChanged();
    },
    onError: (err: Error) => toast({ title: '封禁失败', description: err.message, variant: 'error' }),
  });
  const unbanMutation = useMutation({
    mutationFn: () => teamsApi.unbanMember(teamId, member.user_id, 'member'),
    onSuccess: () => {
      toast({ title: `已解封 ${member.username}`, variant: 'success' });
      queryClient.invalidateQueries({ queryKey: ['team-members', teamId] });
      onChanged();
    },
    onError: (err: Error) => toast({ title: '解封失败', description: err.message, variant: 'error' }),
  });
  const removeMutation = useMutation({
    mutationFn: () => teamsApi.removeMember(teamId, member.user_id),
    onSuccess: () => {
      toast({ title: `已移除 ${member.username}`, variant: 'success' });
      queryClient.invalidateQueries({ queryKey: ['team-members', teamId] });
      queryClient.invalidateQueries({ queryKey: ['my-teams'] });
      onChanged();
    },
    onError: (err: Error) => toast({ title: '移除失败', description: err.message, variant: 'error' }),
  });

  if (!canAct && !isSelf) return null;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" className="h-8 w-8 text-text-tertiary hover:text-text-primary">
          <MoreHorizontal size={16} />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-48">
        {member.is_banned ? (
          <DropdownMenuItem disabled={unbanMutation.isPending} onClick={() => unbanMutation.mutate()}
            className="text-green-600 dark:text-green-400">
            <UserCheck size={14} className="mr-2" />解封为成员
          </DropdownMenuItem>
        ) : (
          <>
            {canAct && assignableRoles.length > 0 && (
              <>
                <DropdownMenuLabel>更改角色</DropdownMenuLabel>
                {assignableRoles.map((r) => (
                  <DropdownMenuItem key={r} disabled={changeRoleMutation.isPending}
                    onClick={() => changeRoleMutation.mutate(r)}>
                    <Shield size={14} className="mr-2" />设为 {TEAM_ROLE_META[r].label}
                  </DropdownMenuItem>
                ))}
                <DropdownMenuSeparator />
                <DropdownMenuItem disabled={banMutation.isPending} onClick={() => banMutation.mutate()}
                  className="text-amber-600 dark:text-amber-400">
                  <Ban size={14} className="mr-2" />封禁
                </DropdownMenuItem>
              </>
            )}
          </>
        )}
        {canAct && (
          <DropdownMenuItem disabled={removeMutation.isPending}
            onClick={() => { if (confirm(`确定要移除 ${member.username} 吗？`)) removeMutation.mutate(); }}
            className="text-red-600 dark:text-red-400">
            <UserX size={14} className="mr-2" />移出团队
          </DropdownMenuItem>
        )}
        {isSelf && !isOwner && (
          <DropdownMenuItem disabled={removeMutation.isPending}
            onClick={() => { if (confirm('确定要离开这个团队吗？')) removeMutation.mutate(); }}
            className="text-red-600 dark:text-red-400">
            <UserX size={14} className="mr-2" />离开团队
          </DropdownMenuItem>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function MembersTable({ teamId, myRole }: { teamId: number; myRole: TeamRole | '' }) {
  const [page, setPage] = React.useState(1);
  const [search, setSearch] = React.useState('');
  const [searchInput, setSearchInput] = React.useState('');
  const [roleFilter, setRoleFilter] = React.useState<TeamRole | 'all' | 'banned'>('all');
  const [includeBanned, setIncludeBanned] = React.useState(false);
  const [inviteOpen, setInviteOpen] = React.useState(false);
  const { canManageMembers } = useRbac();

  const { data, isFetching } = useQuery({
    queryKey: ['team-members', teamId, page, search, roleFilter, includeBanned],
    queryFn: () => teamsApi.listMembers(teamId, {
      page, page_size: PAGE_SIZE, search: search || undefined,
      role: roleFilter !== 'all' && roleFilter !== 'banned' ? (roleFilter as TeamRole) : undefined,
      include_banned: includeBanned || roleFilter === 'banned',
    }),
    staleTime: 10_000,
  });

  const members = data?.items ?? [];
  const total = data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const handleSearch = (e: React.FormEvent) => { e.preventDefault(); setSearch(searchInput.trim()); setPage(1); };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <form onSubmit={handleSearch} className="relative flex-1 min-w-[200px] max-w-sm">
          <Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-text-tertiary" />
          <Input placeholder="搜索用户名、昵称或邮箱" value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)} className="pl-9" />
        </form>
        <div className="flex items-center gap-2">
          <Select value={roleFilter} onValueChange={(v) => {
            setRoleFilter(v as TeamRole | 'all' | 'banned'); setPage(1);
            setIncludeBanned(v === 'banned');
          }}>
            <SelectTrigger className="w-32"><SelectValue placeholder="所有角色" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">所有角色</SelectItem>
              <SelectItem value="owner">所有者</SelectItem>
              <SelectItem value="maintainer">维护者</SelectItem>
              <SelectItem value="member">成员</SelectItem>
              <SelectItem value="reporter">记者</SelectItem>
              <SelectItem value="banned">已封禁</SelectItem>
            </SelectContent>
          </Select>
          <label className="flex items-center gap-1.5 text-sm text-text-secondary">
            <input type="checkbox" checked={includeBanned}
              onChange={(e) => { setIncludeBanned(e.target.checked); setPage(1); }}
              className="rounded border-border-default" />
            包含封禁
          </label>
          {canManageMembers && (
            <Button size="sm" onClick={() => setInviteOpen(true)}>
              <Plus size={14} className="mr-1" />添加成员
            </Button>
          )}
        </div>
      </div>

      <Card>
        <div className="divide-y divide-border-default">
          {isFetching && members.length === 0 ? (
            <div className="flex items-center justify-center py-12 text-text-tertiary">
              <Loader2 className="mr-2 h-5 w-5 animate-spin" />加载中...
            </div>
          ) : members.length === 0 ? (
            <div className="py-12 text-center text-text-tertiary">
              <Users size={32} className="mx-auto mb-2 opacity-30" />
              <p className="text-sm">{search ? '未找到匹配的成员' : '暂无成员'}</p>
            </div>
          ) : members.map((m) => {
            const roleMeta = TEAM_ROLE_META[m.role];
            return (
              <div key={m.user_id} className="flex items-center gap-3 px-4 py-3">
                <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-bg-tertiary text-sm font-medium text-text-secondary">
                  {(m.display_name || m.username).slice(0, 1).toUpperCase()}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="truncate text-sm font-medium text-text-primary">{m.display_name || m.username}</span>
                    {m.is_banned && <Badge variant="destructive" className="text-[10px]">已封禁</Badge>}
                  </div>
                  <div className="truncate text-xs text-text-tertiary">
                    @{m.username}{m.email ? ` · ${m.email}` : ''}
                    {m.joined_at ? ` · 加入于 ${new Date(m.joined_at).toLocaleDateString()}` : ''}
                  </div>
                </div>
                <Badge className={roleMeta.badgeClass + ' text-xs'}>
                  {m.role === 'owner' && <Crown size={10} className="mr-1" />}
                  {roleMeta.label}
                </Badge>
                <MemberRowActions member={m} teamId={teamId} myRole={myRole} onChanged={() => {}} />
              </div>
            );
          })}
        </div>
      </Card>

      {total > 0 && (
        <div className="flex items-center justify-between text-sm text-text-secondary">
          <span>共 {total} 人 · 第 {page} / {totalPages} 页</span>
          <div className="flex items-center gap-1">
            <Button variant="ghost" size="icon" disabled={page <= 1 || isFetching}
              onClick={() => setPage((p) => Math.max(1, p - 1))}><ChevronLeft size={16} /></Button>
            <Button variant="ghost" size="icon" disabled={page >= totalPages || isFetching}
              onClick={() => setPage((p) => p + 1)}><ChevronRight size={16} /></Button>
          </div>
        </div>
      )}

      <InviteMemberDialog open={inviteOpen} teamId={teamId}
        onOpenChange={setInviteOpen} onInvited={() => setPage(1)} />
    </div>
  );
}

function TeamDetailPanel({ team }: { team: TeamDetail }) {
  const { teamRole, canEditSettings, isTeamOwner } = useRbac();
  const myRole = (team.my_role || teamRole) as TeamRole | '';
  return (
    <div className="flex-1 space-y-6">
      <Card>
        <CardHeader className="pb-4">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0 flex-1">
              <div className="mb-1 flex items-center gap-2">
                <CardTitle className="truncate text-xl">{team.name}</CardTitle>
                {team.my_role && (
                  <Badge className={TEAM_ROLE_META[team.my_role as TeamRole]?.badgeClass}>
                    {TEAM_ROLE_META[team.my_role as TeamRole]?.label}
                  </Badge>
                )}
              </div>
              <CardDescription className="truncate">
                {team.description || '暂无描述'} · @{team.slug} · {team.plan} 计划
              </CardDescription>
            </div>
          </div>
        </CardHeader>
      </Card>

      <Tabs defaultValue="members" className="w-full">
        <TabsList className="mb-4 w-full justify-start bg-bg-tertiary p-1">
          <TabsTrigger value="members" className="flex items-center gap-1.5"><Users size={14} />成员</TabsTrigger>
          {(canEditSettings || isTeamOwner) && (
            <TabsTrigger value="settings" className="flex items-center gap-1.5"><SettingsIcon size={14} />设置</TabsTrigger>
          )}
        </TabsList>
        <TabsContent value="members"><MembersTable teamId={team.id} myRole={myRole} /></TabsContent>
        {(canEditSettings || isTeamOwner) && (
          <TabsContent value="settings">
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Team 设置</CardTitle>
                <CardDescription>配置该 Team 的默认模型、会议权限、功能开关等。</CardDescription>
              </CardHeader>
              <CardContent>
                <p className="text-sm text-text-tertiary">Team 级配置面板在后续版本中提供，包括是否允许普通成员发起会议、默认 AI 模型、API Key 管理等。</p>
              </CardContent>
            </Card>
          </TabsContent>
        )}
      </Tabs>
    </div>
  );
}

export default function TeamsPage() {
  const user = useAuthStore((s) => s.user);
  const [selectedTeamId, setSelectedTeamId] = React.useState<number | null>(null);
  const [createOpen, setCreateOpen] = React.useState(false);
  const queryClient = useQueryClient();

  const { data: teamsData, isLoading } = useQuery({
    queryKey: ['my-teams'],
    queryFn: () => teamsApi.listMyTeams(),
    staleTime: 30_000,
  });
  const teams = React.useMemo(() => teamsData?.items ?? [], [teamsData?.items]);

  React.useEffect(() => {
    if (selectedTeamId === null && teams.length > 0) {
      const currentTid = user?.tenant_id ? parseInt(user.tenant_id, 10) : null;
      const match = currentTid ? teams.find((t) => t.id === currentTid) : null;
      setSelectedTeamId(match ? match.id : teams[0].id);
    }
  }, [teams, selectedTeamId, user?.tenant_id]);

  const selectedTeam = teams.find((t) => t.id === selectedTeamId) || null;

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center text-text-tertiary">
        <Loader2 className="mr-2 h-6 w-6 animate-spin" />加载中...
      </div>
    );
  }

  return (
    <div className="flex h-full gap-6 p-6">
      <div className="flex w-64 shrink-0 flex-col gap-2">
        <div className="mb-1 flex items-center justify-between px-1">
          <h2 className="text-sm font-semibold text-text-primary">工作空间</h2>
          <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => setCreateOpen(true)}><Plus size={16} /></Button>
        </div>
        {teams.length === 0 ? (
          <div className="rounded-lg border border-dashed border-border-default p-6 text-center">
            <Building2 size={24} className="mx-auto mb-2 text-text-tertiary opacity-40" />
            <p className="text-sm text-text-tertiary">还没有工作空间</p>
            <Button size="sm" variant="outline" className="mt-3" onClick={() => setCreateOpen(true)}>
              <Plus size={14} className="mr-1" />创建
            </Button>
          </div>
        ) : (
          <div className="space-y-0.5">
            {teams.map((t) => (
              <TeamListItem key={t.id} team={t} isActive={t.id === selectedTeamId} onClick={() => setSelectedTeamId(t.id)} />
            ))}
          </div>
        )}
        <Separator className="my-2" />
        <Button variant="ghost" size="sm" className="justify-start text-text-secondary" onClick={() => setCreateOpen(true)}>
          <Plus size={14} className="mr-2" />创建新工作空间
        </Button>
      </div>

      <div className="flex min-w-0 flex-1">
        {selectedTeam ? <TeamDetailPanel team={selectedTeam} /> : (
          <div className="flex flex-1 items-center justify-center text-text-tertiary">
            <div className="text-center">
              <Building2 size={48} className="mx-auto mb-3 opacity-20" />
              <p>选择或创建一个工作空间开始管理</p>
            </div>
          </div>
        )}
      </div>

      <CreateTeamDialog open={createOpen} onOpenChange={setCreateOpen}
        onCreated={(team) => { queryClient.invalidateQueries({ queryKey: ['my-teams'] }); setSelectedTeamId(team.id); }} />
    </div>
  );
}
