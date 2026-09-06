import * as React from 'react';
import { NavLink } from 'react-router';
import {
  LayoutDashboardIcon,
  LayersIcon,
  FolderIcon,
  NetworkIcon,
  FileTextIcon,
  BotIcon,
  CpuIcon,
  SettingsIcon,
  ShieldIcon,
  ActivityIcon,
  BuildingIcon,
  MonitorIcon,
} from '@/components/ui/svg-icons';
import { cn } from '@/lib/utils';
import { useAuthStore } from '@/stores/auth-slice';

interface NavItem {
  to: string;
  icon: React.ComponentType<{ size?: number; className?: string }>;
  label: string;
  badge?: string;
  adminOnly?: boolean;
}

const navItems: NavItem[] = [
  { to: '/board', icon: LayoutDashboardIcon, label: '看板' },
  { to: '/projects', icon: LayersIcon, label: '项目' },
  { to: '/workspace', icon: FolderIcon, label: '工作区' },
  { to: '/teams', icon: BuildingIcon, label: '团队' },
  { to: '/graph', icon: NetworkIcon, label: '图谱' },
  { to: '/reports', icon: FileTextIcon, label: '报告' },
  { to: '/agents', icon: BotIcon, label: 'Agent' },
  { to: '/models', icon: CpuIcon, label: '模型' },
];

export function NavRail() {
  const user = useAuthStore((s) => s.user);
  const isAdmin =
    user?.system_role === 'system_owner' ||
    user?.system_role === 'system_admin' ||
    user?.role === 'admin' ||
    user?.role === 'owner' ||
    user?.role === 'system_admin' ||
    user?.role === 'system_owner';

  return (
    <nav className="flex h-full w-14 flex-col items-center border-r border-border-soft bg-bg-primary py-3">
      <div className="mb-3 flex h-8 w-8 items-center justify-center rounded-lg bg-brand-500 text-xs font-semibold text-white shadow-sm">
        C
      </div>
      <div className="flex flex-1 flex-col items-center gap-1">
        {navItems.map((item) => (
          <NavItemButton key={item.to} item={item} />
        ))}
        {isAdmin && (
          <>
            <NavItemButton item={{ to: '/operations', icon: ActivityIcon, label: '运维' }} />
            <NavItemButton item={{ to: '/monitoring', icon: MonitorIcon, label: '监控' }} />
            <NavItemButton item={{ to: '/admin', icon: ShieldIcon, label: '管理' }} />
          </>
        )}
      </div>
      <div className="flex flex-col items-center gap-1">
        <NavItemButton item={{ to: '/settings', icon: SettingsIcon, label: '设置' }} />
      </div>
    </nav>
  );
}

function NavItemButton({ item }: { item: NavItem }) {
  const Icon = item.icon;
  return (
    <NavLink
      to={item.to}
      aria-label={item.label}
      className={({ isActive }) =>
        cn(
          'group relative flex h-10 w-10 items-center justify-center rounded-lg transition-all duration-(--duration-hover) ease-(--ease-standard)',
          isActive
            ? 'bg-brand-soft text-brand-500'
            : 'text-text-tertiary hover:bg-bg-tertiary hover:text-text-secondary'
        )
      }
    >
      <Icon size={18} />
      {item.badge && (
        <span className="absolute right-1 top-1 flex h-1.5 w-1.5 rounded-full bg-danger" />
      )}
      <span className="pointer-events-none absolute left-full z-[var(--z-tooltip)] ml-2 rounded-md border border-border-default bg-bg-elevated px-2 py-1 text-xs text-text-secondary opacity-0 shadow-md transition-opacity group-hover:opacity-100 whitespace-nowrap">
        {item.label}
      </span>
    </NavLink>
  );
}
