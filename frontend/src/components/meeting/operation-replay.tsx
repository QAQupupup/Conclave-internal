import * as React from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { useMeetingStore } from '@/stores/meeting-slice';
import type { ToolCallRecord, ToolStep } from '@/types';
import { cn } from '@/lib/utils';
import { ToolIcon } from './tool-icons';
import { buildToolCallsFromEvents } from './operation-replay-utils';
import { RecordingImage } from './recording-image';
import {
  PlayIcon,
  PauseIcon,
  SpinnerIcon,
  StepStatusDot,
} from '@/components/ui/svg-icons';

interface OperationReplayContentProps {
  meetingId: string;
}

type Speed = 0.5 | 1 | 2 | 4;
type ToolFilter = 'all' | 'web_search' | 'browser' | 'web_fetch';

const SPEEDS: Speed[] = [0.5, 1, 2, 4];
// 1× 速度下每个步骤的停留时长（ms），越大越舒缓
const BASE_STEP_MS = 700;

const FILTERS: { key: ToolFilter; label: string }[] = [
  { key: 'all', label: '全部' },
  { key: 'web_search', label: '搜索' },
  { key: 'browser', label: '浏览器' },
  { key: 'web_fetch', label: '抓取' },
];

/** 单个可播放节点：stepIndex 为 -1 表示"调用开始"，为 steps.length 表示"完成/失败" */
interface PlayItem {
  callId: string;
  stepIndex: number;
}

/** 将工具调用列表拍平为可播放的步骤节点序列 */
function flattenToolCalls(toolCalls: ToolCallRecord[]): PlayItem[] {
  const items: PlayItem[] = [];
  for (const tc of toolCalls) {
    items.push({ callId: tc.id, stepIndex: -1 });
    for (let i = 0; i < tc.steps.length; i += 1) {
      items.push({ callId: tc.id, stepIndex: i });
    }
    if (tc.status !== 'running') {
      items.push({ callId: tc.id, stepIndex: tc.steps.length });
    }
  }
  return items;
}

function matchesFilter(tc: ToolCallRecord, filter: ToolFilter): boolean {
  if (filter === 'all') return true;
  if (filter === 'web_search') return tc.toolName === 'web_search';
  if (filter === 'web_fetch') return tc.toolName === 'web_fetch';
  if (filter === 'browser') return tc.toolName.startsWith('browser.');
  return false;
}

function toolLabel(toolName: string): string {
  if (toolName === 'web_search') return '网络搜索';
  if (toolName === 'web_fetch') return '抓取网页';
  if (toolName.startsWith('browser.')) {
    const action = toolName.split('.')[1] || '';
    const map: Record<string, string> = {
      goto: '导航',
      extract: '提取内容',
      click: '点击元素',
      scroll: '滚动页面',
      evaluate: '执行脚本',
    };
    return map[action] || '浏览器操作';
  }
  return toolName;
}

/**
 * 会议级「操作回放」画布内容：聚合整场会议的工具调用，支持播放/暂停/倍速/拖动/过滤。
 * 由悬浮画布体系（FloatingPanel L 档）承载：标题栏、关闭按钮、ESC、入场/退场动效
 * 统一由画布提供，本组件不再自带遮罩与抽屉外壳（非模态，对话流保持可操作）。
 */
export function OperationReplayContent({ meetingId }: OperationReplayContentProps) {
  const liveToolCalls = useMeetingStore((s) => s.toolCalls);
  const [filter, setFilter] = React.useState<ToolFilter>('all');
  const [speed, setSpeed] = React.useState<Speed>(1);
  const [playing, setPlaying] = React.useState(false);
  const [cursor, setCursor] = React.useState(0);

  const eventsQuery = useQuery({
    queryKey: ['meeting', 'events', meetingId],
    queryFn: () => api.getMeetingEvents(meetingId, 0),
    // 组件仅在画布展开期间挂载（画布层按需渲染），无需 open 门控
    enabled: !!meetingId,
    staleTime: 0,
  });

  // 历史事件 + 实时 store 合并（实时记录优先，历史补全页面加载前的内容）
  const toolCalls = React.useMemo<ToolCallRecord[]>(() => {
    const historical = buildToolCallsFromEvents(eventsQuery.data?.events ?? []);
    const map = new Map<string, ToolCallRecord>();
    for (const tc of historical) map.set(tc.id, tc);
    for (const tc of liveToolCalls) map.set(tc.id, tc);
    return [...map.values()].sort((a, b) => a.startedAt.localeCompare(b.startedAt));
  }, [eventsQuery.data, liveToolCalls]);

  const filtered = React.useMemo(
    () => toolCalls.filter((tc) => matchesFilter(tc, filter)),
    [toolCalls, filter],
  );

  const items = React.useMemo(() => flattenToolCalls(filtered), [filtered]);

  // 过滤切换后把游标归位到起始，避免越界
  React.useEffect(() => {
    setCursor(0);
    setPlaying(false);
  }, [filter]);

  // 播放推进（定时器按倍速推进游标）
  React.useEffect(() => {
    if (!playing) return;
    if (items.length === 0) {
      setPlaying(false);
      return;
    }
    const intervalMs = BASE_STEP_MS / speed;
    const timer = setInterval(() => {
      setCursor((prev) => {
        if (prev + 1 >= items.length) {
          setPlaying(false);
          return prev;
        }
        return prev + 1;
      });
    }, intervalMs);
    return () => clearInterval(timer);
  }, [playing, speed, items.length]);

  const safeCursor = Math.min(cursor, Math.max(0, items.length - 1));
  const currentItem = items[safeCursor];
  const currentCall = currentItem
    ? (toolCalls.find((tc) => tc.id === currentItem.callId) ?? null)
    : null;
  const currentStep =
    currentCall && currentItem && currentItem.stepIndex >= 0 && currentItem.stepIndex < currentCall.steps.length
      ? currentCall.steps[currentItem.stepIndex]
      : null;

  const togglePlay = () => {
    if (items.length === 0) return;
    if (playing) {
      setPlaying(false);
    } else if (safeCursor >= items.length - 1) {
      setCursor(0);
      setPlaying(true);
    } else {
      setPlaying(true);
    }
  };

  const jumpToCall = (callId: string) => {
    const idx = items.findIndex((it) => it.callId === callId);
    if (idx >= 0) {
      setCursor(idx);
      setPlaying(false);
    }
  };

  return (
    <div className="flex h-full flex-col">
      {/* 过滤工具栏（含操作计数）；标题栏与关闭按钮由画布统一提供 */}
      <div className="flex flex-shrink-0 items-center gap-1 border-b border-border-soft px-4 py-2">
        {FILTERS.map((f) => (
          <button
            key={f.key}
            type="button"
            onClick={() => setFilter(f.key)}
            className={cn(
              'rounded px-2 py-1 text-[11px] font-medium transition-colors duration-(--duration-hover)',
              filter === f.key
                ? 'bg-brand-500 text-white'
                : 'text-text-tertiary hover:bg-bg-tertiary hover:text-text-secondary',
            )}
          >
            {f.label}
          </button>
        ))}
        <span className="ml-auto flex-shrink-0 rounded-full bg-bg-tertiary px-2 py-0.5 text-[10px] text-text-tertiary">
          {filtered.length} 次操作
        </span>
      </div>

        {/* 播放控制栏 */}
        <div className="flex flex-shrink-0 items-center gap-3 border-b border-border-soft px-4 py-2">
          <button
            type="button"
            onClick={togglePlay}
            disabled={items.length === 0}
            className="flex h-8 w-8 items-center justify-center rounded-full bg-brand-500 text-white transition-colors hover:bg-brand-600 disabled:cursor-not-allowed disabled:opacity-40"
            aria-label={playing ? '暂停' : '播放'}
          >
            {playing ? <PauseIcon size={14} /> : <PlayIcon size={14} />}
          </button>

          <div className="flex items-center gap-0.5 rounded bg-bg-tertiary p-0.5">
            {SPEEDS.map((sp) => (
              <button
                key={sp}
                type="button"
                onClick={() => setSpeed(sp)}
                className={cn(
                  'rounded px-1.5 py-0.5 text-[11px] font-medium transition-colors',
                  speed === sp ? 'bg-bg-primary text-brand-600 shadow-sm' : 'text-text-tertiary hover:text-text-secondary',
                )}
              >
                {sp}×
              </button>
            ))}
          </div>

          <div className="ml-auto flex items-center gap-2 text-[11px] text-text-tertiary">
            <span>
              步 {items.length === 0 ? 0 : safeCursor + 1} / {items.length}
            </span>
          </div>
        </div>

        {/* 进度条（可拖动） */}
        <div className="flex-shrink-0 px-4 py-2">
          <input
            type="range"
            min={0}
            max={Math.max(0, items.length - 1)}
            value={safeCursor}
            onChange={(e) => {
              setCursor(Number(e.target.value));
              setPlaying(false);
            }}
            disabled={items.length === 0}
            className="h-1.5 w-full cursor-pointer appearance-none rounded-full bg-bg-tertiary accent-brand-500"
            aria-label="回放进度"
          />
        </div>

        {/* 主体 */}
        {eventsQuery.isLoading && filtered.length === 0 ? (
          <div className="flex flex-1 items-center justify-center gap-2 text-xs text-text-tertiary">
            <SpinnerIcon size={14} className="animate-spin" />
            加载操作记录...
          </div>
        ) : filtered.length === 0 ? (
          <div className="flex flex-1 flex-col items-center justify-center gap-2 text-xs text-text-tertiary">
            <span>暂无操作记录</span>
            <span className="text-[11px] text-text-tertiary/70">
              会议运行并调用工具（搜索/浏览器/抓取）后，这里会生成可回放的操作轨迹。
            </span>
          </div>
        ) : (
          <div className="flex min-h-0 flex-1">
            {/* 左侧：工具调用列表 */}
            <div className="flex w-60 flex-shrink-0 flex-col overflow-y-auto border-r border-border-soft">
              {filtered.map((tc) => {
                const isCurrent = currentCall?.id === tc.id;
                return (
                  <button
                    key={tc.id}
                    type="button"
                    onClick={() => jumpToCall(tc.id)}
                    className={cn(
                      'flex items-center gap-2.5 border-b border-border-soft/50 px-3 py-2.5 text-left transition-colors',
                      isCurrent ? 'bg-brand-500/10' : 'hover:bg-bg-tertiary/50',
                    )}
                  >
                    <ToolIcon toolName={tc.toolName} size={15} className={cn('flex-shrink-0', isCurrent ? 'text-brand-500' : 'text-text-tertiary')} />
                    <div className="min-w-0 flex-1">
                      <div className={cn('truncate text-[11px] font-medium', isCurrent ? 'text-brand-600' : 'text-text-primary')}>
                        {toolLabel(tc.toolName)}
                      </div>
                      <div className="mt-0.5 flex items-center gap-1.5 text-[10px] text-text-tertiary">
                        <StepStatusDot status={tc.status === 'pending' ? 'pending' : tc.status} size={6} />
                        <span>{tc.steps.length} 步</span>
                        {tc.latencyMs != null && (
                          <span>· {(tc.latencyMs / 1000).toFixed(1)}s</span>
                        )}
                      </div>
                    </div>
                    {isCurrent && <span className="h-1.5 w-1.5 flex-shrink-0 rounded-full bg-brand-500" />}
                  </button>
                );
              })}
            </div>

            {/* 右侧：当前步骤详情 */}
            <div className="flex min-w-0 flex-1 flex-col overflow-y-auto">
              {currentCall ? (
                <div className="flex min-h-0 flex-1 flex-col">
                  {/* 步骤时间线 */}
                  <div className="flex-shrink-0 border-b border-border-soft px-4 py-2">
                    <div className="flex items-baseline gap-2">
                      <span className="text-xs font-medium text-text-primary">{toolLabel(currentCall.toolName)}</span>
                      <span className="truncate text-[10px] text-text-tertiary">
                        {typeof currentCall.arguments.query === 'string' && currentCall.arguments.query
                          ? currentCall.arguments.query
                          : typeof currentCall.arguments.url === 'string' && currentCall.arguments.url
                            ? currentCall.arguments.url
                            : currentCall.reason || ''}
                      </span>
                    </div>
                  </div>

                  <div className="flex-shrink-0 overflow-y-auto border-b border-border-soft/50 px-4 py-2">
                    {/* 开始节点 */}
                    <StepRow
                      label={`调用 ${toolLabel(currentCall.toolName)}`}
                      status="completed"
                      active={currentItem?.stepIndex === -1}
                      onClick={() => jumpToCall(currentCall.id)}
                    />
                    {currentCall.steps.map((step, i) => (
                      <StepRow
                        key={step.id}
                        step={step}
                        active={currentItem?.stepIndex === i}
                        onClick={() => {
                          const idx = items.findIndex((it) => it.callId === currentCall.id && it.stepIndex === i);
                          if (idx >= 0) {
                            setCursor(idx);
                            setPlaying(false);
                          }
                        }}
                      />
                    ))}
                    {currentCall.status !== 'running' && (
                      <StepRow
                        label={currentCall.status === 'failed' ? '操作失败' : '操作完成'}
                        status={currentCall.status}
                        active={currentItem?.stepIndex === currentCall.steps.length}
                        onClick={() => {
                          const idx = items.findIndex((it) => it.callId === currentCall.id && it.stepIndex === currentCall.steps.length);
                          if (idx >= 0) {
                            setCursor(idx);
                            setPlaying(false);
                          }
                        }}
                      />
                    )}
                  </div>

                  {/* 截图/详情预览 */}
                  <div className="min-h-0 flex-1 p-4">
                    {currentStep?.screenshotRef ? (
                      <div className="overflow-hidden rounded-md border border-border-default">
                        <RecordingImage
                          src={currentStep.screenshotRef}
                          alt="操作截图"
                          className="w-full"
                        />
                      </div>
                    ) : currentStep?.screenshot ? (
                      <div className="overflow-hidden rounded-md border border-border-default">
                        <img
                          src={`data:image/png;base64,${currentStep.screenshot}`}
                          alt="操作截图"
                          className="w-full"
                        />
                      </div>
                    ) : currentStep?.url ? (
                      <a
                        href={currentStep.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="block truncate text-xs text-brand-500 hover:underline"
                      >
                        {currentStep.url}
                      </a>
                    ) : (
                      <div className="flex h-40 items-center justify-center rounded-md border border-dashed border-border-default bg-bg-tertiary/30 text-[11px] text-text-tertiary">
                        {currentItem?.stepIndex === -1
                          ? '调用开始'
                          : currentItem?.stepIndex === currentCall.steps.length
                            ? '操作结束'
                            : '该步骤无截图'}
                      </div>
                    )}
                  </div>
                </div>
              ) : (
                <div className="flex flex-1 items-center justify-center text-xs text-text-tertiary">
                  选择左侧操作以查看详情
                </div>
              )}
            </div>
          </div>
        )}
    </div>
  );
}

interface StepRowProps {
  step?: ToolStep;
  label?: string;
  status?: ToolStep['status'];
  active: boolean;
  onClick: () => void;
}

function StepRow({ step, label, status, active, onClick }: StepRowProps) {
  const displayLabel = label || step?.label || step?.stepType || '';
  const displayStatus: ToolStep['status'] = status || step?.status || 'completed';
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-[11px] transition-colors',
        active ? 'bg-brand-500/10 text-brand-600' : 'text-text-secondary hover:bg-bg-tertiary/50',
      )}
    >
      <StepStatusDot status={displayStatus} size={7} />
      <span className="truncate">{displayLabel}</span>
    </button>
  );
}