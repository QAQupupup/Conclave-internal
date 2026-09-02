import * as React from 'react';
import { useMeetingStore } from '@/stores/meeting-slice';
import { cn } from '@/lib/utils';
import { ROLE_LABELS, ROLE_AVATAR_COLORS } from '@/lib/constants';
import type { AgentInfo, AgentState, BorrowRequest } from '@/types';
import { AgentAvatar, StatusDot } from '@/components/ui/svg-icons';
import { Tooltip } from '@/components/ui/tooltip';

export function ThoughtTree({ className }: { className?: string }) {
  const agents = useMeetingStore((s) => s.agents);
  const messages = useMeetingStore((s) => s.messages);
  const selectedMessageId = useMeetingStore((s) => s.selectedMessageId);
  const borrowRequest = useMeetingStore((s) => s.borrowRequest);

  // Build agent ID -> name lookup map
  const agentNameMap = React.useMemo(() => {
    const map = new Map<string, string>();
    for (const agent of agents) {
      map.set(agent.id, agent.name);
    }
    return map;
  }, [agents]);

  return (
    <div className={cn('flex h-full flex-col bg-bg-primary', className)}>
      <div className="flex items-center justify-between border-b border-border-soft px-3 py-2.5">
        <span className="text-xs font-medium text-text-secondary">Agent 状态</span>
        <span className="text-[10px] text-text-tertiary">{agents.length} 位 Agent</span>
      </div>
      <div className="flex-1 overflow-y-auto">
        {/* Agents section */}
        <div className="p-2">
          <div className="mb-1 px-1 text-[10px] font-medium uppercase tracking-wider text-text-tertiary">
            参与 Agent
          </div>
          <div className="space-y-1">
            {agents.length === 0 ? (
              <div className="px-2 py-4 text-center text-[11px] text-text-tertiary">
                Agent 正在加入...
              </div>
            ) : (
              agents.map((agent) => (
                <AgentCard
                  key={agent.id}
                  agent={agent}
                  isHighlighted={
                    selectedMessageId
                      ? messages?.find((m) => m.id === selectedMessageId)?.agentId === agent.id
                      : false
                  }
                />
              ))
            )}
          </div>
        </div>

        {/* Borrow request section */}
        {borrowRequest && (
          <div className="border-t border-border-soft p-2">
            <div className="mb-1 px-1 text-[10px] font-medium uppercase tracking-wider text-warning">
              需要您介入
            </div>
            <BorrowRequestCard request={borrowRequest} agentNameMap={agentNameMap} />
          </div>
        )}
      </div>
    </div>
  );
}

function AgentCard({
  agent,
  isHighlighted,
}: {
  agent: AgentInfo;
  isHighlighted: boolean;
}) {
  const stateLabel: Record<AgentState, string> = {
    idle: '空闲',
    thinking: '思考中',
    speaking: '发言中',
    waiting: '等待中',
    done: '已完成',
    paused: '已暂停',
  };
  const stateDotStatus: Record<AgentState, 'idle' | 'active' | 'thinking' | 'done'> = {
    idle: 'idle',
    thinking: 'thinking',
    speaking: 'active',
    waiting: 'idle',
    done: 'done',
    paused: 'idle',
  };
  const roleLabel = agent.role ? ROLE_LABELS[agent.role] : '';
  const roleColor = agent.role ? ROLE_AVATAR_COLORS[agent.role] : undefined;
  // name 兜底：STATE_DELTA 瘦身负载或历史数据可能缺 name，
  // 退化为角色标签而非空白，避免"无名 Agent"（数据层合并见 lib/agent-merge）
  const displayName = agent.name || roleLabel || '未命名 Agent';
  const tooltipText = roleLabel && agent.name
    ? `${displayName} · ${roleLabel} · ${stateLabel[agent.state]}`
    : `${displayName} · ${stateLabel[agent.state]}`;

  return (
    <div
      className={cn(
        'rounded-md border border-transparent p-2 transition-colors',
        isHighlighted && 'border-brand-500/30 bg-brand-soft',
        !isHighlighted && 'hover:bg-bg-tertiary'
      )}
    >
      <div className="flex items-center gap-2">
        <Tooltip content={tooltipText} side="left">
          <span className="flex flex-shrink-0 items-center" tabIndex={-1}>
            <AgentAvatar
              agentId={agent.id}
              agentName={displayName}
              role={agent.role}
              size={24}
            />
          </span>
        </Tooltip>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <span className="truncate text-xs font-medium text-text-primary">{displayName}</span>
            {roleLabel && (
              <span
                className="inline-flex flex-shrink-0 items-center rounded px-1.5 py-px text-[10px] font-medium leading-tight"
                style={roleColor ? { color: roleColor, backgroundColor: `color-mix(in srgb, ${roleColor} 10%, transparent)` } : { color: 'var(--color-text-tertiary)' }}
              >
                {roleLabel}
              </span>
            )}
          </div>
        </div>
        <div className="flex items-center gap-1 text-[10px] text-text-tertiary">
          <StatusDot status={stateDotStatus[agent.state]} size={7} />
          <span className={agent.state === 'thinking' || agent.state === 'speaking' ? 'text-brand-500' : ''}>
            {stateLabel[agent.state]}
          </span>
        </div>
      </div>
    </div>
  );
}

function BorrowRequestCard({
  request,
  agentNameMap,
}: {
  request: BorrowRequest;
  agentNameMap: Map<string, string>;
}) {
  const [isSubmitting, setIsSubmitting] = React.useState(false);

  const fromName = agentNameMap.get(request.fromAgent) || request.fromAgent;
  const toName = agentNameMap.get(request.toAgent) || request.toAgent;

  const respond = (decision: 'approve' | 'reject') => {
    setIsSubmitting(true);
    import('@/lib/ws').then(({ wsClient }) => {
      wsClient.send({ type: 'borrow.respond', request_id: request.id, decision });
      setTimeout(() => setIsSubmitting(false), 300);
    });
  };
  return (
    <div className="rounded-md border border-warning/20 bg-warning-bg p-2.5">
      <div className="text-[11px] font-medium text-warning">
        {fromName} 请求借调 {toName}
      </div>
      <div className="mt-1 text-[11px] leading-relaxed text-text-secondary">{request.reason}</div>
      <div className="mt-2 flex gap-2">
        <button
          onClick={() => respond('approve')}
          disabled={isSubmitting}
          className="flex-1 rounded bg-brand-500 px-2 py-1 text-[10px] font-medium text-white transition-colors hover:bg-brand-600 disabled:opacity-50"
        >
          批准
        </button>
        <button
          onClick={() => respond('reject')}
          disabled={isSubmitting}
          className="flex-1 rounded border border-border-default bg-bg-primary px-2 py-1 text-[10px] text-text-secondary transition-colors hover:bg-bg-tertiary disabled:opacity-50"
        >
          拒绝
        </button>
      </div>
    </div>
  );
}
