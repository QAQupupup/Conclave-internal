import * as React from 'react';
import { cn, formatRelativeTime } from '@/lib/utils';
import { ROLE_LABELS, ROLE_AVATAR_COLORS, STAGE_LABELS } from '@/lib/constants';
import type { MeetingMessage } from '@/types';
import { useMeetingStore } from '@/stores/meeting-slice';
import { Markdown } from '@/components/ui/markdown';
import { AgentAvatar, UserAvatar, BrainIcon, CornerDownRightIcon, ChevronIcon } from '@/components/ui/svg-icons';
import { ToolCallCard } from './tool-call-card';
import { TakeoverPanel } from './takeover-panel';

interface MessageBubbleProps {
  message: MeetingMessage;
  isSelected: boolean;
  onSelect: (id: string | null) => void;
  /** 可选：传入才显示分支按钮（MR-3：功能未实现时不展示入口） */
  onBranch?: (id: string) => void;
}

export function MessageBubble({ message, isSelected, onSelect, onBranch }: MessageBubbleProps) {
  const [isHovered, setIsHovered] = React.useState(false);
  const [takeoverOpen, setTakeoverOpen] = React.useState(false);
  const [takeoverCallId, setTakeoverCallId] = React.useState<string | null>(null);
  const [takeoverToolName, setTakeoverToolName] = React.useState<string | undefined>(undefined);
  const isThinking = !!message.isThinking;
  const isUser = !!message.isUser;
  const toolCalls = useMeetingStore((s) => s.toolCalls);
  const meetingId = useMeetingStore((s) => s.currentMeetingId);

  // 查找与这条消息关联的工具调用（按 iteration 或时间匹配）
  const relatedToolCalls = React.useMemo(() => {
    return toolCalls.filter((tc) => {
      const ids = (message.metadata?.tool_call_ids as string[]) || [];
      if (ids.length > 0) return ids.includes(tc.id);
      return false;
    });
  }, [toolCalls, message.metadata]);

  if (isUser) {
    return <UserBubble message={message} />;
  }

  const name = message.agentName || 'Agent';
  const roleLabel = message.agentRole ? ROLE_LABELS[message.agentRole] : '';
  const roleColor = message.agentRole ? ROLE_AVATAR_COLORS[message.agentRole] : undefined;
  const stageLabel = message.stage ? STAGE_LABELS[message.stage] : '';
  const isStreaming = isThinking && !message.content;

  const handleTakeover = (callId: string, toolName: string) => {
    setTakeoverCallId(callId);
    setTakeoverToolName(toolName);
    setTakeoverOpen(true);
  };

  const handleCloseTakeover = () => {
    setTakeoverOpen(false);
    setTakeoverCallId(null);
    setTakeoverToolName(undefined);
  };

  return (
    <>
      <div
        role="button"
        tabIndex={0}
        className={cn(
          'group flex gap-3 px-4 py-2 transition-colors message-enter',
          isSelected && 'bg-brand-soft'
        )}
        onClick={() => onSelect(message.id)}
        onKeyDown={(e) => {
          if (e.target !== e.currentTarget) return;
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            onSelect(message.id);
          }
        }}
        onMouseEnter={() => setIsHovered(true)}
        onMouseLeave={() => setIsHovered(false)}
      >
        <div className="mt-0.5 flex-shrink-0">
          <AgentAvatar
            agentId={message.agentId || name}
            agentName={name}
            role={message.agentRole}
            size={28}
          />
        </div>

        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <span className="text-xs font-medium text-text-primary">{name}</span>
            {roleLabel && (
              <span
                className="inline-flex items-center rounded px-1.5 py-px text-[10px] font-medium leading-tight"
                style={roleColor ? { color: roleColor, backgroundColor: `color-mix(in srgb, ${roleColor} 10%, transparent)` } : { color: 'var(--color-text-tertiary)' }}
              >
                {roleLabel}
              </span>
            )}
            {stageLabel && (
              <span className="text-[10px] text-text-tertiary">· {stageLabel}</span>
            )}
            <span className="ml-auto text-[10px] text-text-tertiary opacity-0 transition-opacity group-hover:opacity-100">
              {formatRelativeTime(message.timestamp)}
            </span>
          </div>

          {message.thinking && (
            <ThinkingBlock content={message.thinking} />
          )}

          <div>
            <Markdown content={message.content} className="prose-stream" />
            {isStreaming && <span className="typing-cursor" />}
          </div>

          {/* 关联的工具调用卡片 */}
          {relatedToolCalls.map((tc) => (
            <ToolCallCard key={tc.id} toolCall={tc} onTakeover={handleTakeover} />
          ))}

          {isHovered && !isThinking && message.content && onBranch && (
            <div className="mt-1 flex gap-1 opacity-0 transition-opacity group-hover:opacity-100">
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  onBranch(message.id);
                }}
                className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] text-text-tertiary transition-colors hover:bg-bg-tertiary hover:text-text-secondary"
                title="从此分支探索"
              >
                <CornerDownRightIcon size={10} />
                分支探索
              </button>
            </div>
          )}
        </div>
      </div>

      <TakeoverPanel
        open={takeoverOpen}
        onClose={handleCloseTakeover}
        meetingId={meetingId}
        callId={takeoverCallId ?? undefined}
        toolName={takeoverToolName}
      />
    </>
  );
}

function UserBubble({ message }: { message: MeetingMessage }) {
  return (
    <div className="flex justify-end gap-3 px-4 py-2 message-enter">
      <div className="max-w-[80%] whitespace-pre-wrap break-words rounded-lg bg-brand-500 px-3 py-2 text-sm leading-relaxed text-white shadow-sm">
        {message.content}
      </div>
      <div className="mt-0.5 flex-shrink-0">
        <UserAvatar size={28} />
      </div>
    </div>
  );
}

function ThinkingBlock({ content }: { content: string }) {
  const [expanded, setExpanded] = React.useState(false);
  if (!content) return null;
  return (
    <div className="mb-1.5">
      <button
        onClick={(e) => {
          e.stopPropagation();
          setExpanded(!expanded);
        }}
        className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] text-text-tertiary transition-colors hover:bg-bg-tertiary"
      >
        <BrainIcon size={10} />
        思考过程
        <ChevronIcon direction={expanded ? 'down' : 'right'} size={10} className="text-text-tertiary/60" />
      </button>
      {expanded && (
        <div className="mt-1 rounded-md border border-border-soft bg-bg-secondary p-2 text-[11px] italic leading-relaxed text-text-tertiary whitespace-pre-wrap">
          {content}
        </div>
      )}
    </div>
  );
}
