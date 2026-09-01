import * as React from 'react';
import { useNavigate, useLocation } from 'react-router';
import { useQueryClient } from '@tanstack/react-query';
import { useAuthStore } from '@/stores/auth-slice';
import { useMeetingStore } from '@/stores/meeting-slice';
import { useUIStore } from '@/stores/ui-slice';
import { useTheme } from '@/providers/theme-context';
import { Button } from '@/components/ui/button';
import { ConfirmDialog } from '@/components/ui/confirm-dialog';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { wsClient } from '@/lib/ws';
import { STAGE_LABELS } from '@/lib/constants';
import { useDeleteMeeting } from '@/hooks/use-meetings';
import {
  Logo,
  SearchIcon,
  CommandIcon,
  SunIcon,
  MoonIcon,
  MonitorIcon,
  ChevronLeftIcon,
  PauseIcon,
  PlayIcon,
  SkipForwardIcon,
  StopCircleIcon,
  CheckIcon,
  SettingsIcon,
  LogOutIcon,
  BuildingIcon,
  ChevronRightIcon,
  ShieldIcon,
  TrashIcon,
} from '@/components/ui/svg-icons';
import type { TenantInfo } from '@/types';
import { useToast } from '@/hooks/use-toast';

function RoleBadge({ role }: { role?: string }) {
  if (!role || role === 'member') return null;
  const label = role === 'owner' ? '所有者' : role === 'admin' ? '管理员' : role;
  const colorClass = role === 'owner' ? 'bg-accent-purple/15 text-accent-purple' : 'bg-brand-soft text-brand-600';
  return (
    <span className={`ml-1.5 rounded px-1 py-0 text-[9px] font-medium ${colorClass}`}>{label}</span>
  );
}

function UserInitialsAvatar({ name, size = 28 }: { name: string; size?: number }) {
  const initial = name.charAt(0).toUpperCase();
  return (
    <div
      className="flex items-center justify-center rounded-full bg-brand-500 text-xs font-semibold text-white"
      style={{ width: size, height: size, fontSize: size * 0.42 }}
    >
      {initial}
    </div>
  );
}

function TenantSwitcher() {
  const user = useAuthStore((s) => s.user);
  const switchTenant = useAuthStore((s) => s.switchTenant);
  const navigate = useNavigate();
  const [switching, setSwitching] = React.useState(false);
  const { toast } = useToast();

  if (!user || !Array.isArray(user.tenants) || user.tenants.length <= 1) return null;

  const currentTenant = user.tenants?.find((t) => t.id === user.tenant_id);

  const handleSwitch = async (tenant: TenantInfo) => {
    if (tenant.id === user.tenant_id) return;
    setSwitching(true);
    try {
      await switchTenant(tenant.id);
      toast({ title: '已切换', description: `当前组织：${tenant.name}` });
      // 导航到看板刷新视图状态
      navigate('/board');
    } catch (err) {
      toast({ title: '切换失败', description: err instanceof Error ? err.message : '未知错误', variant: 'destructive' });
    } finally {
      setSwitching(false);
    }
  };

  return (
    <DropdownMenuSub>
      <DropdownMenuSubTrigger disabled={switching}>
        <BuildingIcon size={14} className="mr-2" />
        <span className="flex-1 truncate text-left">{currentTenant?.name || '切换租户'}</span>
        <ChevronRightIcon size={12} className="ml-auto text-text-tertiary" />
      </DropdownMenuSubTrigger>
      <DropdownMenuSubContent>
        {user.tenants.map((t) => (
          <DropdownMenuItem key={t.id} onClick={() => handleSwitch(t)} disabled={switching}>
            <span className="flex-1 truncate">{t.name}</span>
            {t.id === user.tenant_id && <CheckIcon size={14} className="ml-2 text-brand-500" />}
            {t.role === 'owner' && <span className="ml-2 rounded bg-bg-tertiary px-1 text-[9px] text-text-tertiary">Owner</span>}
          </DropdownMenuItem>
        ))}
      </DropdownMenuSubContent>
    </DropdownMenuSub>
  );
}

// Safe toast hook that doesn't crash if Toaster isn't mounted yet

export function TopBar() {
  const openCommandPalette = useUIStore((s) => s.openCommandPalette);
  const navigate = useNavigate();
  const location = useLocation();
  const isInMeeting = location.pathname.startsWith('/meeting/');
  const { theme, setTheme } = useTheme();
  const meeting = useMeetingStore();
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const qc = useQueryClient();
  const { toast } = useToast();
  const deleteMeeting = useDeleteMeeting();
  const [deleteDialogOpen, setDeleteDialogOpen] = React.useState(false);

  // 控制按钮仅在运行中/暂停中显示；删除按钮始终显示（不再互斥）
  const isRunningOrPaused = isInMeeting && ['running', 'paused'].includes(meeting.status);

  // 全局快捷键：Cmd/Ctrl+K 打开命令面板
  React.useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        openCommandPalette();
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [openCommandPalette]);

  const handlePauseResume = () => {
    if (meeting.status === 'running') {
      wsClient.sendControl('pause');
    } else if (meeting.status === 'paused') {
      wsClient.sendControl('resume');
    }
  };

  const handleSkip = () => wsClient.sendControl('skip_stage');

  const handleDelete = async () => {
    if (!meeting.currentMeetingId) return;
    try {
      await deleteMeeting.mutateAsync(meeting.currentMeetingId);
      toast({ title: '已删除', description: '讨论已删除' });
      qc.invalidateQueries({ queryKey: ['meetings'] });
      navigate('/board');
    } catch (err: unknown) {
      toast({
        title: '删除失败',
        description: err instanceof Error ? err.message : '未知错误',
        variant: 'error',
      });
    } finally {
      setDeleteDialogOpen(false);
    }
  };

  const displayName = user?.display_name || user?.username || '用户';

  return (
    <header className="flex h-11 flex-shrink-0 items-center gap-3 border-b border-border-soft bg-bg-primary px-4">
      {isInMeeting ? (
        <React.Fragment>
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            onClick={() => navigate('/board')}
            aria-label="返回看板"
          >
            <ChevronLeftIcon size={16} />
          </Button>
          <div className="flex min-w-0 flex-1 items-center gap-3">
            <h1 className="truncate text-sm font-medium text-text-primary">{meeting.title || '探索中...'}</h1>
            <div className="flex items-center gap-1.5 text-xs text-text-tertiary">
              <span className={`inline-flex h-1.5 w-1.5 rounded-full ${['running', 'paused'].includes(meeting.status) ? 'bg-stage-running animate-pulse' : meeting.status === 'done' ? 'bg-stage-done' : meeting.status === 'error' ? 'bg-danger' : 'bg-text-tertiary'}`} />
              <span>{STAGE_LABELS[meeting.stage] || meeting.status}</span>
            </div>
          </div>
          <div className="flex items-center gap-1">
            {isRunningOrPaused && (
              <>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-7 w-7"
                  onClick={handlePauseResume}
                  title={meeting.status === 'paused' ? '继续' : '暂停'}
                  aria-label={meeting.status === 'paused' ? '继续' : '暂停'}
                >
                  {meeting.status === 'paused' ? <PlayIcon size={14} /> : <PauseIcon size={14} />}
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-7 w-7"
                  onClick={handleSkip}
                  title="跳过当前阶段"
                  aria-label="跳过当前阶段"
                >
                  <SkipForwardIcon size={14} />
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-7 w-7 text-danger"
                  onClick={() => wsClient.sendControl('stop')}
                  title="终止会议"
                  aria-label="终止会议"
                >
                  <StopCircleIcon size={14} />
                </Button>
              </>
            )}
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7 text-danger hover:bg-danger/10"
              onClick={() => setDeleteDialogOpen(true)}
              title="删除讨论"
              aria-label="删除讨论"
            >
              <TrashIcon size={14} />
            </Button>
          </div>
        </React.Fragment>
      ) : (
        <React.Fragment>
          <div className="flex items-center gap-2">
            <Logo size={18} />
            <span className="text-sm font-semibold text-text-primary">Conclave</span>
            <span className="rounded bg-bg-tertiary px-1.5 py-0.5 text-[10px] font-medium text-text-tertiary">
              v3
            </span>
          </div>
          <div className="flex flex-1 justify-center">
            <button
              onClick={openCommandPalette}
              className="flex h-7 w-72 items-center gap-2 rounded-md border border-border-soft bg-bg-secondary px-3 text-left text-xs text-text-tertiary transition-colors hover:border-border-default hover:bg-bg-tertiary"
            >
              <SearchIcon size={14} />
              <span className="flex-1">搜索会议、报告、Agent...</span>
              <kbd className="flex items-center gap-0.5 text-[10px] text-text-tertiary">
                <CommandIcon size={12} /> K
              </kbd>
            </button>
          </div>
        </React.Fragment>
      )}

      <div className="flex items-center gap-1">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon" className="h-7 w-7" aria-label="切换主题">
              {theme === 'dark' ? <MoonIcon size={14} /> : theme === 'light' ? <SunIcon size={14} /> : <MonitorIcon size={14} />}
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-36">
            <DropdownMenuLabel>主题</DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuItem onClick={() => setTheme('light')}>
              <SunIcon size={14} className="mr-2" />
              浅色
              {theme === 'light' && <CheckIcon size={14} className="ml-auto text-brand-500" />}
            </DropdownMenuItem>
            <DropdownMenuItem onClick={() => setTheme('dark')}>
              <MoonIcon size={14} className="mr-2" />
              深色
              {theme === 'dark' && <CheckIcon size={14} className="ml-auto text-brand-500" />}
            </DropdownMenuItem>
            <DropdownMenuItem onClick={() => setTheme('system')}>
              <MonitorIcon size={14} className="mr-2" />
              跟随系统
              {theme === 'system' && <CheckIcon size={14} className="ml-auto text-brand-500" />}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon" className="h-7 w-7 rounded-full" title={displayName} aria-label="用户菜单">
              <UserInitialsAvatar name={displayName} size={24} />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-56">
            <DropdownMenuLabel className="flex flex-col gap-0.5 py-2.5">
              <div className="flex items-center gap-2">
                <UserInitialsAvatar name={displayName} size={28} />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center text-sm font-medium text-text-primary">
                    <span className="truncate">{displayName}</span>
                    <RoleBadge role={user?.role} />
                  </div>
                  <span className="text-[11px] font-normal text-text-tertiary truncate block">@{user?.username}</span>
                </div>
              </div>
              {user?.email && (
                <span className="text-[11px] text-text-tertiary truncate pl-[36px]">{user.email}</span>
              )}
              {(() => {
                const ct = user?.tenants?.find((t) => t.id === user.tenant_id);
                if (!ct) return null;
                return (
                  <div className="mt-1 flex items-center gap-1 rounded bg-bg-secondary px-2 py-1 text-[10px] text-text-secondary">
                    <BuildingIcon size={10} />
                    <span className="truncate">{ct.name}</span>
                    {ct.role && ct.role !== 'member' && (
                      <span className={`ml-auto rounded px-1 text-[9px] ${ct.role === 'owner' ? 'text-accent-purple' : 'text-brand-600'}`}>
                        {ct.role === 'owner' ? '所有者' : '管理员'}
                      </span>
                    )}
                  </div>
                );
              })()}
            </DropdownMenuLabel>
            <DropdownMenuSeparator />
            <TenantSwitcher />
            <DropdownMenuItem onClick={() => navigate('/settings')}>
              <SettingsIcon size={14} className="mr-2" />
              个人设置
            </DropdownMenuItem>
            {(user?.role === 'admin' || user?.role === 'owner') && (
              <DropdownMenuItem onClick={() => navigate('/admin')}>
                <ShieldIcon size={14} className="mr-2" />
                系统管理
              </DropdownMenuItem>
            )}
            <DropdownMenuSeparator />
            <DropdownMenuItem onClick={logout} className="text-danger focus:bg-danger-bg focus:text-danger">
              <LogOutIcon size={14} className="mr-2" />
              退出登录
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
      <ConfirmDialog
        open={deleteDialogOpen}
        title="删除讨论"
        description={
          isRunningOrPaused
            ? `「${meeting.title || '该讨论'}」正在运行中，删除将终止会议并移除相关文件和记录，该操作不可撤销。`
            : `确定要删除「${meeting.title || '该讨论'}」吗？该操作不可撤销，相关文件和记录将被移除。`
        }
        destructive={true}
        confirmText="删除"
        onConfirm={handleDelete}
        onCancel={() => setDeleteDialogOpen(false)}
      />
    </header>
  );
}
