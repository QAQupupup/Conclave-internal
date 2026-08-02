import * as React from 'react';
import type { ToolCallRecord } from '@/types';
import {
  StepStatusDot,
  SpinnerIcon,
  ChevronIcon,
  SearchIcon,
  DomainFavicon,
} from '@/components/ui/svg-icons';
import { cn } from '@/lib/utils';

interface WebSearchReplayProps {
  toolCall: ToolCallRecord;
}

type SearchPhase = 'querying' | 'searching' | 'results' | 'fetching' | 'extracting' | 'done';

interface SearchResult {
  url: string;
  title: string;
  domain: string;
  sourceTier?: string;
  snippet?: string;
}

// 从 summary 中提取搜索结果
function extractResults(toolCall: ToolCallRecord): SearchResult[] {
  if (!toolCall.summary) return [];
  const s = toolCall.summary as Record<string, unknown>;
  if (s.type === 'search_results' && Array.isArray(s.items)) {
    return (s.items as Record<string, unknown>[]).map((item) => ({
      url: String(item.url || ''),
      title: String(item.title || ''),
      domain: String(item.domain || ''),
      sourceTier: String(item.source_tier || ''),
    }));
  }
  return [];
}

// 来源评级徽章
function TierBadge({ tier }: { tier: string }) {
  if (!tier) return null;
  const colors: Record<string, string> = {
    S: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/20',
    A: 'bg-blue-500/15 text-blue-400 border-blue-500/20',
    B: 'bg-yellow-500/15 text-yellow-400 border-yellow-500/20',
    C: 'bg-orange-500/15 text-orange-400 border-orange-500/20',
    D: 'bg-red-500/15 text-red-400 border-red-500/20',
  };
  return (
    <span className={cn('inline-flex items-center rounded border px-1 py-px text-[10px] font-semibold', colors[tier] || colors.D)}>
      {tier}
    </span>
  );
}

export function WebSearchReplay({ toolCall }: WebSearchReplayProps) {
  const results = React.useMemo(() => extractResults(toolCall), [toolCall]);
  const [selectedResult, setSelectedResult] = React.useState<number>(-1);
  const [fetchProgress, setFetchProgress] = React.useState(0);

  const isRunning = toolCall.status === 'running';
  const query = String(toolCall.arguments.query || '');

  // 根据步骤推断当前阶段
  const phase: SearchPhase = React.useMemo(() => {
    if (toolCall.status === 'completed') return 'done';
    const steps = Array.isArray(toolCall.steps) ? toolCall.steps : [];
    if (steps.length === 0) return 'querying';
    const lastStep = steps[steps.length - 1];
    if (lastStep.stepType.includes('search')) return 'searching';
    if (lastStep.stepType.includes('result')) return 'results';
    if (lastStep.stepType.includes('fetch') || lastStep.stepType.includes('navigate') || lastStep.stepType.includes('goto')) return 'fetching';
    if (lastStep.stepType.includes('extract')) return 'extracting';
    return 'searching';
  }, [toolCall.steps, toolCall.status]);

  // 模拟进度（真实场景由 step 事件驱动）
  React.useEffect(() => {
    if (!isRunning) {
      setFetchProgress(results.length > 0 ? 100 : 0);
      return;
    }
    const phaseTargets: Record<SearchPhase, number> = {
      querying: 10,
      searching: 30,
      results: 50,
      fetching: 75,
      extracting: 90,
      done: 100,
    };
    const target = phaseTargets[phase];
    const interval = setInterval(() => {
      setFetchProgress((prev) => Math.min(prev + 2, target));
    }, 100);
    return () => clearInterval(interval);
  }, [isRunning, phase, results.length]);

  return (
    <div className="space-y-3">
      {/* 搜索查询 */}
      <div className="flex items-center gap-2 rounded-md bg-bg-tertiary/40 px-2.5 py-2">
        <SearchIcon size={13} className="flex-shrink-0 text-brand-500" />
        <span className="text-xs text-text-primary">{query}</span>
        {isRunning && <SpinnerIcon size={12} className="ml-auto animate-spin text-text-tertiary" />}
      </div>

      {/* 进度条 */}
      {(isRunning || toolCall.status === 'completed') && (
        <div className="space-y-1.5">
          <div className="flex items-center justify-between text-[10px] text-text-tertiary">
            <span>
              {phase === 'querying' && '初始化搜索...'}
              {phase === 'searching' && '正在搜索...'}
              {phase === 'results' && `找到 ${results.length} 个结果`}
              {phase === 'fetching' && '抓取页面内容...'}
              {phase === 'extracting' && '提取正文...'}
              {phase === 'done' && `搜索完成 · ${results.length} 条结果 · ${toolCall.latencyMs ? `${(toolCall.latencyMs / 1000).toFixed(1)}s` : ''}`}
            </span>
            <span>{fetchProgress}%</span>
          </div>
          <div className="h-1 w-full overflow-hidden rounded-full bg-bg-tertiary">
            <div
              className="h-full rounded-full bg-gradient-to-r from-brand-500 to-accent-purple transition-all duration-300"
              style={{ width: `${fetchProgress}%` }}
            />
          </div>
        </div>
      )}

      {/* 阶段指示器（SVG 步骤线） */}
      <div className="flex items-center gap-0 px-1">
        {([
          { key: 'querying', label: '查询' },
          { key: 'searching', label: '搜索' },
          { key: 'fetching', label: '抓取' },
          { key: 'extracting', label: '提取' },
          { key: 'done', label: '完成' },
        ] as const).map((p, i, arr) => {
          const phaseOrder: Record<string, number> = { querying: 0, searching: 1, results: 1, fetching: 2, extracting: 3, done: 4 };
          const currentIdx = phaseOrder[phase];
          const isActive = i <= currentIdx;
          const isCurrent = i === currentIdx;
          return (
            <React.Fragment key={p.key}>
              <div className="flex flex-col items-center gap-1">
                <div
                  className={cn(
                    'flex h-5 w-5 items-center justify-center rounded-full border text-[9px] font-semibold transition-colors',
                    isActive
                      ? isCurrent && isRunning
                        ? 'border-brand-500 bg-brand-500 text-white'
                        : 'border-brand-500/40 bg-brand-500/10 text-brand-500'
                      : 'border-border-default bg-bg-tertiary/50 text-text-tertiary',
                  )}
                >
                  {isCurrent && isRunning ? <SpinnerIcon size={8} className="animate-spin" /> : i + 1}
                </div>
                <span className={cn('text-[9px]', isActive ? 'text-text-secondary' : 'text-text-tertiary')}>{p.label}</span>
              </div>
              {i < arr.length - 1 && (
                <div className={cn('mx-1 mb-3.5 h-px flex-1 transition-colors', isActive && i < currentIdx ? 'bg-brand-500/30' : 'bg-border-default')} />
              )}
            </React.Fragment>
          );
        })}
      </div>

      {/* 搜索结果列表 */}
      {results.length > 0 && (
        <div className="space-y-1">
          <div className="flex items-center justify-between px-0.5">
            <span className="text-[10px] font-medium uppercase tracking-wider text-text-tertiary">搜索结果</span>
            <span className="text-[10px] text-text-tertiary">{results.length} 条</span>
          </div>
          <div className="max-h-64 space-y-1 overflow-y-auto pr-1">
            {results.map((r, idx) => (
              <button
                key={`${r.url}-${idx}`}
                type="button"
                onClick={() => setSelectedResult(selectedResult === idx ? -1 : idx)}
                className={cn(
                  'group flex w-full items-start gap-2 rounded-md border px-2.5 py-2 text-left transition-all',
                  selectedResult === idx
                    ? 'border-brand-500/30 bg-brand-500/[0.05]'
                    : 'border-transparent hover:border-border-default hover:bg-bg-tertiary/30',
                )}
              >
                <DomainFavicon domain={r.domain} size={16} />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1.5">
                    <span className="truncate text-[11px] font-medium text-text-primary group-hover:text-brand-500">
                      {r.title || r.domain}
                    </span>
                    {r.sourceTier && <TierBadge tier={r.sourceTier} />}
                  </div>
                  <div className="mt-0.5 flex items-center gap-1.5">
                    <span className="truncate text-[10px] text-text-tertiary">{r.url}</span>
                  </div>
                </div>
                <ChevronIcon
                  direction={selectedResult === idx ? 'down' : 'right'}
                  size={12}
                  className={cn(
                    'mt-0.5 flex-shrink-0 text-text-tertiary transition-transform',
                    selectedResult === idx && 'rotate-90',
                  )}
                />
              </button>
            ))}
          </div>
        </div>
      )}

      {/* 详细步骤时间线（来自 tool.step 事件） */}
      {Array.isArray(toolCall.steps) && toolCall.steps.length > 0 && (
        <div className="border-t border-border-default/50 pt-2">
          <div className="mb-1.5 px-0.5 text-[10px] font-medium uppercase tracking-wider text-text-tertiary">操作日志</div>
          <div className="max-h-40 space-y-0.5 overflow-y-auto pl-0.5">
            {toolCall.steps.map((step) => (
              <div key={step.id} className="flex items-center gap-2 py-0.5">
                <StepStatusDot status={step.status} size={7} />
                <span className="text-[10px] text-text-tertiary">{step.label}</span>
                {step.url && (
                  <span className="ml-auto truncate text-[10px] text-text-tertiary/60">{step.url.slice(0, 35)}{step.url.length > 35 ? '...' : ''}</span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 空状态提示 */}
      {results.length === 0 && !isRunning && toolCall.status !== 'failed' && (
        <div className="py-3 text-center text-[11px] text-text-tertiary">暂无结果</div>
      )}
    </div>
  );
}
