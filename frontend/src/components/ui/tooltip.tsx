import * as React from 'react';
import * as TooltipPrimitive from '@radix-ui/react-tooltip';
import { cn } from '@/lib/utils';

interface TooltipProps {
  content: React.ReactNode;
  children: React.ReactNode;
  side?: 'top' | 'right' | 'bottom' | 'left';
  className?: string;
}

const Tooltip: React.FC<TooltipProps> = ({ content, children, side = 'top', className }) => {
  return (
    // 自带 Provider：使 Tooltip 在任何上下文（含未挂载全局 Provider 的
    // 组件测试）中独立可用；Radix 允许嵌套 Provider，不影响全局配置
    <TooltipPrimitive.Provider delayDuration={200}>
      <TooltipPrimitive.Root>
        <TooltipPrimitive.Trigger asChild>
          {children}
        </TooltipPrimitive.Trigger>
        <TooltipPrimitive.Portal>
          <TooltipPrimitive.Content
            side={side}
            sideOffset={4}
            className={cn(
              'z-tooltip px-2 py-1 text-xs rounded-md bg-bg-inverse text-text-inverse whitespace-nowrap pointer-events-none shadow-sm',
              'data-[state=delayed-open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=delayed-open]:fade-in-0',
              className
            )}
          >
            {content}
            <TooltipPrimitive.Arrow className="fill-bg-inverse" />
          </TooltipPrimitive.Content>
        </TooltipPrimitive.Portal>
      </TooltipPrimitive.Root>
    </TooltipPrimitive.Provider>
  );
};

export { Tooltip };
