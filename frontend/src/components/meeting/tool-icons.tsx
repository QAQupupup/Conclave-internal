// 此文件保持向后兼容，所有基础图标已迁移至 @/components/ui/svg-icons
import * as React from 'react';
import {
  SearchIcon,
  LinkIcon,
  CursorIcon,
  GlobeIcon,
  ScrollIcon,
  CodeIcon,
  DocIcon,
  TerminalIcon,
  WrenchIcon,
  StepStatusDot,
  SpinnerIcon,
  HandIcon,
  ChevronIcon,
  BrowserWindowIcon,
} from '@/components/ui/svg-icons';

// 重新导出（保持向后兼容）
export {
  SearchIcon,
  LinkIcon,
  CursorIcon,
  GlobeIcon,
  ScrollIcon,
  CodeIcon,
  DocIcon,
  TerminalIcon,
  WrenchIcon,
  StepStatusDot,
  SpinnerIcon,
  HandIcon,
  ChevronIcon,
  BrowserWindowIcon,
};

// 本地别名
const BrowserIcon = BrowserWindowIcon;
export { BrowserIcon };

// ===== 工具类型图标（智能分发） =====
interface ToolIconProps {
  toolName: string;
  size?: number;
  className?: string;
}

export function ToolIcon({ toolName, size = 16, className }: ToolIconProps) {
  const category = toolName.split('.')[0];

  if (category === 'web_search' || toolName === 'web_search') {
    return <SearchIcon size={size} className={className} />;
  }
  if (toolName === 'web_fetch') {
    return <LinkIcon size={size} className={className} />;
  }
  if (category === 'browser') {
    const action = toolName.split('.')[1] || 'goto';
    if (action === 'click') return <CursorIcon size={size} className={className} />;
    if (action === 'goto') return <GlobeIcon size={size} className={className} />;
    if (action === 'scroll') return <ScrollIcon size={size} className={className} />;
    if (action === 'evaluate') return <CodeIcon size={size} className={className} />;
    if (action === 'extract') return <DocIcon size={size} className={className} />;
    return <BrowserIcon size={size} className={className} />;
  }
  if (category === 'workspace' || toolName.startsWith('fs.') || toolName.startsWith('shell.')) {
    return <TerminalIcon size={size} className={className} />;
  }
  return <WrenchIcon size={size} className={className} />;
}
