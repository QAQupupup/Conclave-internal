import * as React from 'react';
import {
  Command as CommandPrimitive,
} from 'cmdk';
import { useNavigate } from 'react-router';
import { useUIStore } from '@/stores/ui-slice';
import { Dialog, DialogContent } from '@/components/ui/dialog';
import {
  LayoutDashboard,
  Layers,
  FolderKanban,
  Network,
  FileText,
  Bot,
  Settings,
  Sun,
  Moon,
  Monitor,
  Plus,
  Shield,
} from 'lucide-react';
import { useTheme } from '@/providers/theme-context';
import { cn } from '@/lib/utils';
import { useStartMeeting } from '@/hooks/use-meetings';
import { toast } from '@/hooks/use-toast';
import { useAuthStore } from '@/stores/auth-slice';

export function CommandPalette() {
  const open = useUIStore((s) => s.commandPaletteOpen);
  const close = useUIStore((s) => s.closeCommandPalette);
  const navigate = useNavigate();
  const { setTheme } = useTheme();
  const user = useAuthStore((s) => s.user);
  const isAdmin = user?.role === 'admin' || user?.role === 'owner';
  const [query, setQuery] = React.useState('');
  const startMeeting = useStartMeeting();

  const runCommand = React.useCallback(
    (fn: () => void) => {
      fn();
      close();
      setQuery('');
    },
    [close]
  );

  React.useEffect(() => {
    if (!open) setQuery('');
  }, [open]);

  const handleNewMeeting = async () => {
    const topic = query.trim() || '新讨论';
    try {
      const res = await startMeeting.mutateAsync({ topic });
      toast({ title: '已启动讨论', description: topic });
      navigate(`/meeting/${res.meeting_id}`);
    } catch (e: unknown) {
      toast({ title: '启动失败', description: (e as Error).message, variant: 'error' });
    }
  };

  return (
    <Dialog open={open} onOpenChange={(v) => !v && close()}>
      <DialogContent className="overflow-hidden p-0 shadow-sm sm:max-w-[520px]" closeClassName="top-3 right-3">
        <CommandPrimitive
          className={cn(
            'flex h-[420px] w-full flex-col overflow-hidden rounded-lg bg-popover text-popover-foreground'
          )}
          shouldFilter={true}
          loop
        >
          <div className="flex items-center border-b border-border-soft px-3">
            <CommandPrimitive.Input
              placeholder="输入命令或搜索..."
              value={query}
              onValueChange={setQuery}
              className="flex h-11 w-full rounded-md bg-transparent py-3 text-sm outline-none placeholder:text-text-tertiary disabled:cursor-not-allowed disabled:opacity-50"
            />
          </div>
          <CommandPrimitive.List className="max-h-[340px] overflow-y-auto p-2">
            <CommandPrimitive.Empty className="py-6 text-center text-sm text-text-tertiary">
              没有找到结果
            </CommandPrimitive.Empty>

            {query.length > 0 && (
              <CommandPrimitive.Group heading="操作">
                <CommandItem
                  onSelect={() => runCommand(handleNewMeeting)}
                  icon={<Plus className="h-4 w-4" />}
                  shortcut="↵"
                >
                  启动讨论: {query}
                </CommandItem>
              </CommandPrimitive.Group>
            )}

            <CommandPrimitive.Group heading="导航">
              <CommandItem onSelect={() => runCommand(() => navigate('/board'))} icon={<LayoutDashboard className="h-4 w-4" />}>
                看板
              </CommandItem>
              <CommandItem onSelect={() => runCommand(() => navigate('/board/new'))} icon={<Plus className="h-4 w-4" />}>
                新建议题
              </CommandItem>
              <CommandItem onSelect={() => runCommand(() => navigate('/projects'))} icon={<Layers className="h-4 w-4" />}>
                项目与议题池
              </CommandItem>
              <CommandItem onSelect={() => runCommand(() => navigate('/workspace'))} icon={<FolderKanban className="h-4 w-4" />}>
                工作区
              </CommandItem>
              <CommandItem onSelect={() => runCommand(() => navigate('/graph'))} icon={<Network className="h-4 w-4" />}>
                知识图谱
              </CommandItem>
              <CommandItem onSelect={() => runCommand(() => navigate('/reports'))} icon={<FileText className="h-4 w-4" />}>
                报告库
              </CommandItem>
              <CommandItem onSelect={() => runCommand(() => navigate('/agents'))} icon={<Bot className="h-4 w-4" />}>
                Agent 管理
              </CommandItem>
              <CommandItem onSelect={() => runCommand(() => navigate('/settings'))} icon={<Settings className="h-4 w-4" />}>
                设置
              </CommandItem>
              {isAdmin && (
                <CommandItem onSelect={() => runCommand(() => navigate('/admin'))} icon={<Shield className="h-4 w-4" />}>
                  系统管理
                </CommandItem>
              )}
            </CommandPrimitive.Group>

            <CommandPrimitive.Group heading="主题">
              <CommandItem onSelect={() => runCommand(() => setTheme('light'))} icon={<Sun className="h-4 w-4" />}>
                浅色主题
              </CommandItem>
              <CommandItem onSelect={() => runCommand(() => setTheme('dark'))} icon={<Moon className="h-4 w-4" />}>
                深色主题
              </CommandItem>
              <CommandItem onSelect={() => runCommand(() => setTheme('system'))} icon={<Monitor className="h-4 w-4" />}>
                跟随系统
              </CommandItem>
            </CommandPrimitive.Group>
          </CommandPrimitive.List>
          <div className="flex items-center justify-between border-t border-border-soft px-3 py-1.5 text-[10px] text-text-tertiary">
            <div className="flex items-center gap-3">
              <span><kbd className="rounded border px-1">↑↓</kbd> 选择</span>
              <span><kbd className="rounded border px-1">↵</kbd> 执行</span>
              <span><kbd className="rounded border px-1">Esc</kbd> 关闭</span>
            </div>
            <span>Conclave Command</span>
          </div>
        </CommandPrimitive>
      </DialogContent>
    </Dialog>
  );
}

function CommandItem({
  children,
  icon,
  shortcut,
  onSelect,
}: {
  children: React.ReactNode;
  icon?: React.ReactNode;
  shortcut?: string;
  onSelect: () => void;
}) {
  return (
    <CommandPrimitive.Item
      onSelect={onSelect}
      className="relative flex cursor-pointer select-none items-center gap-2.5 rounded-md px-2.5 py-1.5 text-sm text-text-primary outline-none data-[disabled=true]:pointer-events-none data-[selected=true]:bg-bg-tertiary"
    >
      {icon && <span className="text-text-tertiary">{icon}</span>}
      <span className="flex-1">{children}</span>
      {shortcut && (
        <span className="ml-auto rounded border border-border-default bg-bg-secondary px-1.5 py-0.5 text-[10px] text-text-tertiary">
          {shortcut}
        </span>
      )}
    </CommandPrimitive.Item>
  );
}
