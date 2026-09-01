import * as React from 'react';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { api } from '@/lib/api';
import { toast } from '@/hooks/use-toast';
import {
  HandIcon,
  PauseIcon,
  PlayIcon,
  XIcon,
  BrowserWindowIcon,
} from '@/components/ui/svg-icons';

interface TakeoverPanelProps {
  open: boolean;
  onClose: () => void;
  meetingId: string | null;
  toolName?: string;
  callId?: string;
}

type TakeoverMode = 'watching' | 'paused' | 'controlling';

// 接管面板：允许用户暂停Agent操作、观察浏览器、手动接管
// 通过后端 noVNC 实现浏览器画面预览和控制
export function TakeoverPanel({ open, onClose, meetingId, toolName, callId }: TakeoverPanelProps) {
  const [mode, setMode] = React.useState<TakeoverMode>('watching');
  const [vncConnected, setVncConnected] = React.useState(false);
  const iframeRef = React.useRef<HTMLIFrameElement>(null);

  React.useEffect(() => {
    if (!open) {
      setMode('watching');
      setVncConnected(false);
    }
  }, [open]);

  const sendControlSignal = React.useCallback(
    async (signal: string, payload: Record<string, unknown>) => {
      if (!meetingId) return;
      try {
        await api.post(`/meetings/${meetingId}/control`, { signal, payload });
      } catch (err: unknown) {
        const message = err instanceof Error ? err.message : '未知错误';
        toast({ title: '操作失败', description: message, variant: 'destructive' });
      }
    },
    [meetingId],
  );

  if (!open) return null;

  // VNC URL 使用相对路径，通过 nginx/vite proxy 转发到 noVNC 服务
  const vncBase = (import.meta as { env?: { VITE_VNC_URL?: string } }).env?.VITE_VNC_URL || '';
  const vncUrl = meetingId
    ? `${vncBase}/vnc.html?autoconnect=true&resize=scale&path=websockify&meeting_id=${meetingId}`
    : '';

  const handlePause = () => {
    sendControlSignal('pause', { call_id: callId });
    setMode('paused');
  };

  const handleResume = () => {
    sendControlSignal('resume', { call_id: callId });
    setMode('watching');
  };

  const handleTakeover = () => {
    // 接管 = 暂停 Agent，避免 Agent 与用户争夺浏览器控制权
    sendControlSignal('pause', { call_id: callId, reason: 'browser_takeover' });
    setMode('controlling');
    setVncConnected(true);
  };

  const handleRelease = () => {
    // 释放控制权 = 恢复 Agent 继续执行
    sendControlSignal('resume', { call_id: callId, reason: 'browser_release' });
    setMode('watching');
    setVncConnected(false);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="relative flex h-[80vh] w-[90vw] max-w-5xl flex-col overflow-hidden rounded-lg border border-border-default bg-bg-elevated shadow-md">
        {/* 头部 */}
        <div className="flex items-center justify-between border-b border-border-default px-4 py-3">
          <div className="flex items-center gap-2.5">
            <div className={cn(
              'flex h-8 w-8 items-center justify-center rounded-lg',
              mode === 'controlling' ? 'bg-accent-purple/15 text-accent-purple' : 'bg-brand-500/10 text-brand-500',
            )}>
              {mode === 'controlling' ? <HandIcon size={16} /> : <BrowserWindowIcon size={16} />}
            </div>
            <div>
              <h3 className="text-sm font-semibold text-text-primary">
                {mode === 'controlling' ? '手动控制中' : mode === 'paused' ? '已暂停' : '浏览器观察'}
              </h3>
              <p className="text-[11px] text-text-tertiary">
                {toolName ? `${toolName} · ` : ''}
                {mode === 'watching' && '你可以观察 Agent 的浏览器操作，必要时暂停并接管'}
                {mode === 'paused' && 'Agent 已暂停，你可以手动处理后继续'}
                {mode === 'controlling' && '你正在控制浏览器，操作完成后释放控制权'}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1.5 text-text-tertiary hover:bg-bg-tertiary hover:text-text-secondary"
          >
            <XIcon size={16} />
          </button>
        </div>

        {/* 浏览器画面区域 */}
        <div className="relative flex-1 bg-[#1a1a2e]">
          {vncConnected && vncUrl ? (
            <iframe
              ref={iframeRef}
              src={vncUrl}
              className="h-full w-full border-0"
              title="Browser VNC"
              sandbox="allow-scripts allow-same-origin allow-forms allow-popups"
            />
          ) : (
            <div className="flex h-full flex-col items-center justify-center gap-3 text-text-tertiary">
              <BrowserWindowIcon size={48} className="opacity-40" />
              <p className="text-xs">
                {mode === 'paused' ? 'Agent 已暂停。点击"接管控制"以手动操作浏览器。' : '点击"接管控制"连接浏览器画面'}
              </p>
              {!meetingId && (
                <p className="text-[10px] text-danger">未连接到会议</p>
              )}
            </div>
          )}

          {/* 状态指示 */}
          {mode !== 'controlling' && (
            <div className="absolute left-3 top-3 flex items-center gap-1.5 rounded-md bg-black/40 px-2 py-1 text-[10px] text-white/80 backdrop-blur-sm">
              <span className={cn('h-1.5 w-1.5 rounded-full', mode === 'paused' ? 'bg-yellow-400' : 'bg-green-400 animate-pulse')} />
              {mode === 'paused' ? '已暂停' : 'Agent 操作中'}
            </div>
          )}
        </div>

        {/* 底部操作栏 */}
        <div className="flex items-center justify-between border-t border-border-default px-4 py-3">
          <div className="flex items-center gap-2">
            {mode === 'watching' && (
              <>
                <Button variant="outline" size="sm" onClick={handlePause}>
                  <PauseIcon size={12} className="mr-1.5" />
                  暂停 Agent
                </Button>
                <Button size="sm" onClick={handleTakeover}>
                  <HandIcon size={12} className="mr-1.5" />
                  接管控制
                </Button>
              </>
            )}
            {mode === 'paused' && (
              <>
                <Button variant="outline" size="sm" onClick={handleResume}>
                  <PlayIcon size={12} className="mr-1.5" />
                  继续执行
                </Button>
                <Button size="sm" onClick={handleTakeover}>
                  <HandIcon size={12} className="mr-1.5" />
                  接管控制
                </Button>
              </>
            )}
            {mode === 'controlling' && (
              <Button variant="outline" size="sm" onClick={handleRelease} className="border-accent-purple/30 text-accent-purple hover:bg-accent-purple/10">
                释放控制权
              </Button>
            )}
          </div>
          <div className="flex items-center gap-3 text-[10px] text-text-tertiary">
            <span>快捷键: ESC 释放控制</span>
          </div>
        </div>
      </div>
    </div>
  );
}
