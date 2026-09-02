import * as React from 'react';
import { useMeetingStore } from '@/stores/meeting-slice';
import { MessageBubble } from './message-bubble';
import { ToolCallCard } from './tool-call-card';
import { TakeoverPanel } from './takeover-panel';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { wsClient } from '@/lib/ws';
import { useEventSource } from '@/hooks/use-realtime';
import { useMeetingMessages } from '@/hooks/use-meetings';
import { useParams } from 'react-router';
import { SendIcon, ArrowDownIcon, SpinnerIcon } from '@/components/ui/svg-icons';
import { toast } from '@/hooks/use-toast';
import { STAGE_LABELS, STAGE_DESCRIPTIONS, normalizeStageId } from '@/lib/constants';
import type { StageId } from '@/types';

// 合并消息和工具调用为统一的时间线条目
type TimelineItem =
  | { type: 'message'; id: string; data: ReturnType<typeof useMeetingStore.getState>['messages'][number] }
  | { type: 'tool'; id: string; data: ReturnType<typeof useMeetingStore.getState>['toolCalls'][number] };

// 渲染条目：时间线条目 + 派生的阶段分隔行
type RenderItem = TimelineItem | { type: 'stage'; id: string; stage: StageId };

export function MessageStream({ className }: { className?: string }) {
  const { id: meetingId } = useParams<{ id: string }>();
  const messages = useMeetingStore((s) => s.messages);
  const toolCalls = useMeetingStore((s) => s.toolCalls);
  const selectedMessageId = useMeetingStore((s) => s.selectedMessageId);
  const selectMessage = useMeetingStore((s) => s.selectMessage);
  const status = useMeetingStore((s) => s.status);
  const currentMeetingId = useMeetingStore((s) => s.currentMeetingId);
  const scrollRef = React.useRef<HTMLDivElement>(null);
  const shouldAutoScroll = React.useRef(true);
  const [showScrollButton, setShowScrollButton] = React.useState(false);
  const [unreadCount, setUnreadCount] = React.useState(0);
  const [input, setInput] = React.useState('');
  const [isSending, setIsSending] = React.useState(false);
  const [takeoverOpen, setTakeoverOpen] = React.useState(false);
  const [takeoverCallId, setTakeoverCallId] = React.useState<string | null>(null);
  const [takeoverToolName, setTakeoverToolName] = React.useState<string | undefined>(undefined);
  const textareaRef = React.useRef<HTMLTextAreaElement>(null);

  useEventSource(meetingId);

  // REST 历史消息兜底：WS 快照缺失/刷新页面时，从已持久化的发言记录恢复。
  // addMessage 按 id 去重，与 WS 推送和平共存。
  const { data: historyMessages, isLoading: historyLoading } = useMeetingMessages(meetingId, { limit: 500 });
  const seededRef = React.useRef<string | null>(null);
  React.useEffect(() => {
    if (!meetingId || !historyMessages || seededRef.current === meetingId) return;
    seededRef.current = meetingId;
    const store = useMeetingStore.getState();
    for (const msg of historyMessages) {
      store.addMessage(msg);
    }
  }, [meetingId, historyMessages]);

  // 合并消息和工具调用到时间线（按时间排序）
  const timeline = React.useMemo<TimelineItem[]>(() => {
    const items: TimelineItem[] = [];
    for (const m of messages) {
      items.push({ type: 'message', id: `msg-${m.id}`, data: m });
    }
    for (const tc of toolCalls) {
      items.push({ type: 'tool', id: `tool-${tc.id}`, data: tc });
    }
    items.sort((a, b) => {
      const getTs = (item: TimelineItem): number => {
        if (item.type === 'message') {
          const ts = item.data.timestamp;
          return typeof ts === 'string' ? new Date(ts).getTime() : ts;
        }
        return new Date(item.data.startedAt).getTime();
      };
      return getTs(a) - getTs(b);
    });
    return items;
  }, [messages, toolCalls]);

  // 阶段分隔行：当消息携带的阶段（归一化后）相对上一条消息发生变化时插入。
  // 分隔行上下间距由 --rhythm-stage 驱动（见 app.css 排版节奏 token）。
  // 未携带 stage 的消息（部分历史数据）不参与分隔，优雅降级为无分隔行。
  const renderItems = React.useMemo<RenderItem[]>(() => {
    const out: RenderItem[] = [];
    let prevStage: string | undefined;
    for (const item of timeline) {
      if (item.type === 'message') {
        const stage = item.data.stage ? normalizeStageId(item.data.stage) : undefined;
        if (stage && STAGE_LABELS[stage] && stage !== prevStage) {
          out.push({ type: 'stage', id: `stage-${stage}-${item.data.id}`, stage: stage as StageId });
          prevStage = stage;
        }
      }
      out.push(item);
    }
    return out;
  }, [timeline]);

  const scrollToBottom = React.useCallback((smooth = true) => {
    const el = scrollRef.current;
    if (el) {
      el.scrollTo({ top: el.scrollHeight, behavior: smooth ? 'smooth' : 'auto' });
      setUnreadCount(0);
      shouldAutoScroll.current = true;
    }
  }, []);

  // Auto-scroll to bottom on new items
  React.useEffect(() => {
    if (!shouldAutoScroll.current) {
      setUnreadCount((c) => c + 1);
      return;
    }
    requestAnimationFrame(() => {
      const el = scrollRef.current;
      if (el) el.scrollTop = el.scrollHeight;
    });
  }, [renderItems.length]);

  const handleScroll = (e: React.UIEvent<HTMLDivElement>) => {
    const el = e.currentTarget;
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    shouldAutoScroll.current = nearBottom;
    setShowScrollButton(!nearBottom && el.scrollHeight > el.clientHeight + 100);
    if (nearBottom) setUnreadCount(0);
  };

  const handleSend = () => {
    if (!input.trim() || isSending) return;
    setIsSending(true);
    const ok = wsClient.sendChat(input.trim());
    if (ok) {
      setInput('');
      shouldAutoScroll.current = true;
      if (textareaRef.current) textareaRef.current.style.height = 'auto';
    } else {
      // WS 未连接时明确提示，保留输入内容，避免"以为已发送"
      toast({
        title: '发送失败',
        description: '实时连接已断开，消息未送达。请等待连接恢复后重试。',
        variant: 'error',
      });
    }
    setTimeout(() => setIsSending(false), 300);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleInput = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInput(e.target.value);
    const el = e.target;
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 128) + 'px';
  };

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
    <div className={cn('flex h-full flex-col bg-bg-secondary relative', className)}>
      <div className="border-b border-border-soft px-4 py-2 flex-shrink-0">
        <div className="text-xs font-medium text-text-secondary">对话流</div>
      </div>

      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto py-2"
      >
        {timeline.length === 0 ? (
          <div className="flex h-full items-center justify-center gap-2 text-xs text-text-tertiary">
            {historyLoading ? (
              <>
                <SpinnerIcon size={12} className="animate-spin" />
                加载历史消息...
              </>
            ) : status === 'running' ? (
              '等待 Agent 开始讨论...'
            ) : (
              '暂无消息'
            )}
          </div>
        ) : (
          <div className="divide-y divide-border-soft/50">
            {renderItems.map((item) => {
              if (item.type === 'stage') {
                return (
                  <div
                    key={item.id}
                    role="separator"
                    aria-label={`进入${STAGE_LABELS[item.stage]}阶段`}
                    className="flex items-center gap-3 px-4 py-(--rhythm-stage)"
                  >
                    <div className="h-px flex-1 bg-border-soft" aria-hidden="true" />
                    <span
                      className="flex-shrink-0 text-xs text-text-tertiary"
                      title={STAGE_DESCRIPTIONS[item.stage]}
                    >
                      {STAGE_LABELS[item.stage]}
                    </span>
                    <div className="h-px flex-1 bg-border-soft" aria-hidden="true" />
                  </div>
                );
              }
              if (item.type === 'message') {
                return (
                  <MessageBubble
                    key={item.id}
                    message={item.data}
                    isSelected={selectedMessageId === item.data.id}
                    onSelect={selectMessage}
                  />
                );
              }
              return (
                <div key={item.id} className="px-4 py-1.5">
                  <ToolCallCard toolCall={item.data} onTakeover={handleTakeover} />
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Scroll to bottom button */}
      {showScrollButton && (
        <button
          onClick={() => scrollToBottom(true)}
          className="absolute bottom-20 left-1/2 -translate-x-1/2 flex items-center gap-1.5 rounded-full border border-border-default bg-bg-elevated px-3 py-1.5 text-xs text-text-secondary shadow-md transition-all hover:border-brand-500/30 hover:text-brand-500"
        >
          <ArrowDownIcon size={12} />
          {unreadCount > 0 ? `${unreadCount} 条新消息` : '回到底部'}
        </button>
      )}

      <div className="border-t border-border-soft bg-bg-primary p-3 flex-shrink-0">
        <div className="flex items-end gap-2 rounded-lg border border-border-default bg-bg-secondary p-2 focus-within:border-brand-500/40 focus-within:ring-2 focus-within:ring-brand-500/10 transition-colors">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={handleInput}
            onKeyDown={handleKeyDown}
            aria-label="会议发言输入框"
            placeholder={status === 'running' ? '说点什么... (Enter 发送, Shift+Enter 换行)' : '会议未在运行'}
            disabled={status !== 'running'}
            rows={1}
            className="max-h-32 flex-1 resize-none bg-transparent py-1 text-sm leading-relaxed text-text-primary outline-none placeholder:text-text-tertiary disabled:cursor-not-allowed disabled:opacity-50"
          />
          <Button
            size="icon"
            className="h-7 w-7 flex-shrink-0"
            disabled={!input.trim() || isSending || status !== 'running'}
            onClick={handleSend}
          >
            <SendIcon size={14} />
          </Button>
        </div>
      </div>

      <TakeoverPanel
        open={takeoverOpen}
        onClose={handleCloseTakeover}
        meetingId={currentMeetingId}
        callId={takeoverCallId ?? undefined}
        toolName={takeoverToolName}
      />
    </div>
  );
}
