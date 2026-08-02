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
  );
};

export { Tooltip };
