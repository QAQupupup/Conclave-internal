import * as React from 'react';
import { useMeetingStore } from '@/stores/meeting-slice';
import { cn } from '@/lib/utils';
import { STAGE_LABELS, STAGE_DESCRIPTIONS, normalizeStageId } from '@/lib/constants';
import type { StageId } from '@/types';
import { CheckIcon, CircleIcon, SpinnerIcon } from '@/components/ui/svg-icons';

const STAGE_ORDER: StageId[] = [
  'clarification',
  'intra_team',
  'cross_team',
  'evidence_check',
  'arbitrate',
  'produce',
];

export function StageTimeline({ className }: { className?: string }) {
  const currentStage = useMeetingStore((s) => s.stage);
  const status = useMeetingStore((s) => s.status);

  // 兼容 clarify / clarification 两种写法（边界已统一为 clarification，此处兜底）
  const normalizedStage = normalizeStageId(currentStage);
  const currentIdx = STAGE_ORDER.indexOf(normalizedStage as StageId);

  return (
    <div className={cn('flex h-full flex-col bg-bg-primary', className)}>
      <div className="flex items-center gap-2 border-b border-border-soft px-3 py-2.5">
        <span className="text-xs font-medium text-text-secondary">讨论阶段</span>
      </div>
      <div className="flex-1 overflow-y-auto p-3">
        <ol className="relative space-y-0">
          {STAGE_ORDER.map((stageId, idx) => {
            const isCurrent = idx === currentIdx && status === 'running';
            const isDone = idx < currentIdx || status === 'done';
            const isPending = idx > currentIdx || (status !== 'running' && status !== 'done' && idx > 0);
            const isActive = isCurrent;

            return (
              <li key={stageId} className="relative flex gap-3 pb-1">
                {/* connector line */}
                {idx < STAGE_ORDER.length - 1 && (
                  <span
                    className={cn(
                      'absolute left-[11px] top-6 w-px',
                      isDone ? 'bg-brand-500' : 'bg-border-default'
                    )}
                    style={{ height: 'calc(100% - 4px)' }}
                  />
                )}

                <div className="relative flex h-6 flex-shrink-0 items-center justify-center">
                  {isCurrent ? (
                    <span className="flex h-[22px] w-[22px] items-center justify-center rounded-full bg-brand-500 ring-4 ring-brand-soft">
                      <SpinnerIcon size={12} className="text-white" />
                    </span>
                  ) : isDone ? (
                    <span className="flex h-[22px] w-[22px] items-center justify-center rounded-full bg-brand-500">
                      <CheckIcon size={12} className="text-white" />
                    </span>
                  ) : (
                    <span className="flex h-[22px] w-[22px] items-center justify-center rounded-full border-2 border-border-default bg-bg-primary">
                      <CircleIcon size={8} fill="var(--color-border-default)" />
                    </span>
                  )}
                </div>

                <div className={cn('flex-1 pb-4 pt-0.5', isPending && 'opacity-50')}>
                  <div
                    className={cn(
                      'text-xs font-medium leading-snug',
                      isActive ? 'text-brand-600 dark:text-brand-500' : isDone ? 'text-text-primary' : 'text-text-tertiary'
                    )}
                  >
                    {STAGE_LABELS[stageId]}
                  </div>
                  <div className="mt-0.5 text-[11px] leading-relaxed text-text-tertiary">
                    {STAGE_DESCRIPTIONS[stageId]}
                  </div>
                </div>
              </li>
            );
          })}
        </ol>
      </div>
    </div>
  );
}
