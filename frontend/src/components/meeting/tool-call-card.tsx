import * as React from 'react';
import type { ToolCallRecord } from '@/types';
import { ToolIcon, SpinnerIcon, StepStatusDot, ChevronIcon, HandIcon } from './tool-icons';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { WebSearchReplay } from './web-search-replay';

interface ToolCallCardProps {
  toolCall: ToolCallRecord;
  onTakeover?: (callId: string, toolName: string) => void;
  defaultExpanded?: boolean;
}

// 工具名称中文映射
const TOOL_LABELS: Record<string, string> = {
  web_search: '网络搜索',
  web_fetch: '页面抓取',
  'browser.goto': '浏览器导航',
  'browser.extract': '提取内容',
  'browser.click': '点击元素',
  'browser.scroll': '滚动页面',
  'browser.evaluate': '执行脚本',
  'browser.fill': '填写表单',
  'browser.type': '输入文本',
  'browser.press': '按键',
  'browser.hover': '悬停',
  'browser.screenshot': '截图',
  'browser.new_tab': '新标签页',
  'browser.switch_tab': '切换标签页',
  'browser.get_links': '获取链接',
  'fs.read': '读取文件',
  'fs.write': '写入文件',
  'shell.exec': '执行命令',
};

function getToolLabel(toolName: string): string {
  return TOOL_LABELS[toolName] || toolName;
}

// 格式化耗时
function formatDuration(ms?: number): string {
  if (!ms) return '';
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  return `${(ms / 60000).toFixed(1)}m`;
}

// 提取工具参数预览
function getArgPreview(call: ToolCallRecord): string {
  const args = call.arguments;
  if (call.toolName === 'web_search') return `"${String(args.query || '').slice(0, 80)}"`;
  if (call.toolName === 'web_fetch' || call.toolName === 'browser.goto') return String(args.url || '').slice(0, 60);
  if (call.toolName === 'browser.click') return String(args.selector || '').slice(0, 50);
  if (call.toolName === 'browser.evaluate') return String(args.expression || '').slice(0, 50);
  return '';
}

// 提取结果摘要
function getResultSummary(call: ToolCallRecord): React.ReactNode {
  if (call.status === 'running') {
    return (
      <span className="flex items-center gap-1.5 text-text-tertiary">
        <SpinnerIcon className="animate-spin" />
        执行中...
      </span>
    );
  }
  if (call.status === 'failed') {
    const errMsg = call.error || '';
    // 开发模式显示原始错误前 120 字符，生产模式显示友好提示
    const displayMsg = import.meta.env.DEV && errMsg ? errMsg.slice(0, 120) : '执行失败';
    return (
      <span className="text-danger" title={import.meta.env.DEV ? errMsg.slice(0, 300) : ''}>
        {displayMsg}
      </span>
    );
  }
  if (call.summary) {
    const s = call.summary as Record<string, unknown>;
    if (s.type === 'search_results') {
      const count = (s.count as number) || 0;
      return <span className="text-text-secondary">找到 {count} 条结果</span>;
    }
    if (s.type === 'page_content') {
      const len = (s.content_length as number) || 0;
      return <span className="text-text-secondary">获取 {len} 字内容</span>;
    }
    if (s.type === 'browser_action') {
      const url = (s.url as string) || '';
      return <span className="text-text-secondary truncate max-w-[200px] inline-block align-bottom">{url.slice(0, 40)}{url.length > 40 ? '...' : ''}</span>;
    }
  }
  if (call.latencyMs) {
    return <span className="text-text-tertiary">耗时 {formatDuration(call.latencyMs)}</span>;
  }
  return null;
}

// 是否为可回放的工具类型
function isReplayable(toolName: string): boolean {
  return toolName === 'web_search' || toolName === 'web_fetch' || toolName.startsWith('browser.');
}

export function ToolCallCard({ toolCall, onTakeover, defaultExpanded = false }: ToolCallCardProps) {
  const [expanded, setExpanded] = React.useState(defaultExpanded);
  const isRunning = toolCall.status === 'running';
  const isFailed = toolCall.status === 'failed';
  const safeSteps = Array.isArray(toolCall.steps) ? toolCall.steps : [];
  const hasSteps = safeSteps.length > 0;
  const canReplay = isReplayable(toolCall.toolName);
  const canTakeover = isRunning && toolCall.toolName.startsWith('browser.');

  return (
    <div
      className={cn(
        'my-2 rounded-lg border transition-colors',
        isFailed
          ? 'border-danger/20 bg-danger/5'
          : isRunning
            ? 'border-brand-500/20 bg-brand-500/[0.03]'
            : 'border-border-default bg-bg-secondary/50',
      )}
    >
      {/* 卡片头部 - 始终可见 */}
      <button
        type="button"
        className="flex w-full items-center gap-2.5 px-3 py-2 text-left"
        onClick={() => setExpanded(!expanded)}
      >
        {/* 工具图标 */}
        <span
          className={cn(
            'flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-md',
            isFailed
              ? 'bg-danger/10 text-danger'
              : isRunning
                ? 'bg-brand-500/10 text-brand-500'
                : 'bg-bg-tertiary text-text-secondary',
          )}
        >
          {isRunning ? <SpinnerIcon size={14} className="animate-spin" /> : <ToolIcon toolName={toolCall.toolName} size={14} />}
        </span>

        {/* 工具名称和描述 */}
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="text-xs font-medium text-text-primary">{getToolLabel(toolCall.toolName)}</span>
            {toolCall.reason && (
              <span className="truncate text-[11px] text-text-tertiary">{toolCall.reason.slice(0, 50)}</span>
            )}
          </div>
          <div className="mt-0.5 flex items-center gap-2 text-[11px]">
            {getArgPreview(toolCall) && (
              <code className="truncate rounded bg-bg-tertiary/50 px-1.5 py-px font-mono text-text-tertiary">
                {getArgPreview(toolCall)}
              </code>
            )}
            {getResultSummary(toolCall)}
          </div>
        </div>

        {/* 操作按钮 */}
        <div className="flex items-center gap-1">
          {canTakeover && (
            <Button
              variant="ghost"
              size="sm"
              className="h-6 px-2 text-[11px] text-accent-purple hover:bg-accent-purple/10 hover:text-accent-purple"
              onClick={(e) => {
                e.stopPropagation();
                onTakeover?.(toolCall.id, toolCall.toolName);
              }}
            >
              <HandIcon size={12} className="mr-1" />
              接管
            </Button>
          )}
          {(hasSteps || canReplay) && (
            <ChevronIcon
              direction={expanded ? 'down' : 'right'}
              size={14}
              className={cn('text-text-tertiary transition-transform', expanded && 'rotate-90')}
            />
          )}
        </div>
      </button>

      {/* 展开的详情区域 */}
      {expanded && (hasSteps || canReplay) && (
        <div className="border-t border-border-default/50 px-3 py-2.5">
          {toolCall.toolName === 'web_search' ? (
            <WebSearchReplay toolCall={toolCall} />
          ) : toolCall.toolName.startsWith('browser.') || toolCall.toolName === 'web_fetch' ? (
            <BrowserReplayView toolCall={toolCall} />
          ) : (
            <GenericStepTimeline steps={safeSteps} />
          )}
        </div>
      )}
    </div>
  );
}

// 浏览器操作回放视图
function BrowserReplayView({ toolCall }: { toolCall: ToolCallRecord }) {
  const safeSteps = Array.isArray(toolCall.steps) ? toolCall.steps : [];
  const [activeStepIdx, setActiveStepIdx] = React.useState(safeSteps.length - 1);
  const activeStep = safeSteps[activeStepIdx];

  if (safeSteps.length === 0) {
    return (
      <div className="py-3 text-center text-xs text-text-tertiary">
        {toolCall.status === 'running' ? '等待浏览器操作...' : '无详细步骤记录'}
      </div>
    );
  }

  return (
    <div className="flex gap-3">
      {/* 步骤时间线 */}
      <div className="flex w-40 flex-shrink-0 flex-col gap-0.5">
        {safeSteps.map((step, idx) => (
          <button
            key={step.id}
            type="button"
            onClick={() => setActiveStepIdx(idx)}
            className={cn(
              'flex items-start gap-2 rounded-md px-2 py-1.5 text-left text-[11px] transition-colors',
              idx === activeStepIdx
                ? 'bg-brand-500/10 text-brand-500'
                : 'text-text-tertiary hover:bg-bg-tertiary/50 hover:text-text-secondary',
            )}
          >
            <StepStatusDot status={step.status} size={8} />
            <span className="truncate flex-1">{step.label}</span>
          </button>
        ))}
      </div>

      {/* 步骤详情 */}
      <div className="min-w-0 flex-1">
        {activeStep && (
          <div className="space-y-2">
            <div className="flex items-center gap-2 text-xs text-text-secondary">
              {activeStep.url && (
                <a
                  href={activeStep.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="truncate text-brand-500 hover:underline"
                >
                  {activeStep.url}
                </a>
              )}
            </div>
            {activeStep.screenshot ? (
              <div className="overflow-hidden rounded-md border border-border-default">
                <img
                  src={`data:image/png;base64,${activeStep.screenshot}`}
                  alt="页面截图"
                  className="w-full"
                />
              </div>
            ) : (
              <div className="flex h-32 items-center justify-center rounded-md border border-dashed border-border-default bg-bg-tertiary/30 text-[11px] text-text-tertiary">
                {activeStep.status === 'running' ? '操作进行中...' : '无截图'}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// 通用步骤时间线
function GenericStepTimeline({ steps }: { steps: ToolCallRecord['steps'] }) {
  if (!Array.isArray(steps) || steps.length === 0) return null;
  return (
    <div className="flex flex-col gap-1 pl-1">
      {steps.map((step) => (
        <div key={step.id} className="flex items-center gap-2 text-[11px]">
          <StepStatusDot status={step.status} size={8} />
          <span className="text-text-secondary">{step.label}</span>
        </div>
      ))}
    </div>
  );
}
