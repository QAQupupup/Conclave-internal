/* Conclave WebSocket 客户端 — ported from app.html
 * 会议 WS：实时事件推送（Agent 发言、阶段切换、介入回复、借调请求）
 * 系统 WS：会议列表变更、心跳
 * 含指数退避重连（delay = min(MAX, BASE*2^attempt) + jitter） */
import { getToken } from './auth';

const WS_BACKOFF_BASE = 1000;
const WS_BACKOFF_MAX = 30000;

function wsBackoffDelay(attempt: number): number {
  const exp = Math.min(WS_BACKOFF_MAX, WS_BACKOFF_BASE * Math.pow(2, attempt));
  return exp + Math.floor(Math.random() * 1000); // 0-1000ms 抖动
}

function wsUrl(path: string): string {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const token = getToken();
  const tokenParam = token ? `?token=${encodeURIComponent(token)}` : '';
  return `${proto}//${location.host}${path}${tokenParam}`;
}

/** 后端 Stage 枚举（与 models.py Stage 对齐） */
export const STAGE_KEYS = ['clarify', 'intra_team', 'cross_team', 'evidence_check', 'arbitrate', 'produce'] as const;
export const STAGE_MAP: Record<number, string> = {
  0: 'clarify', 1: 'intra_team', 2: 'cross_team', 3: 'evidence_check', 4: 'arbitrate', 5: 'produce',
};

export interface WsMessage {
  type: string;
  payload?: any;
  [k: string]: any;
}

/** 会议 WS 事件回调集合（仅注册需要的） */
export interface MeetingWsHandlers {
  onSnapshot?: (state: any) => void;
  onAgentSpoke?: (msg: WsMessage) => void;
  onStageChanged?: (msg: WsMessage) => void;
  onRunStarted?: (msg: WsMessage) => void;
  onControlSignal?: (msg: WsMessage) => void;
  onControlAck?: (msg: WsMessage) => void;
  onInterventionReply?: (msg: WsMessage) => void;
  onBorrowRequest?: (msg: WsMessage) => void;
  onBorrowResolved?: (msg: WsMessage) => void;
  onProduceProgress?: (msg: WsMessage) => void;
  onProduceDegradation?: (msg: WsMessage) => void;
  onLogEntry?: (msg: WsMessage) => void;
  onReplayDone?: (lastSeq: number) => void;
  onAuthRequired?: () => void;
}

/** 会议 WebSocket 客户端（带指数退避重连） */
export class MeetingWsClient {
  private ws: WebSocket | null = null;
  private meetingId: string | null = null;
  private reconnectTimer: number | null = null;
  private resetTimer: number | null = null;
  private attempts = 0;
  private destroyed = false;

  constructor(private handlers: MeetingWsHandlers) {}

  connect(meetingId: string): void {
    this.destroyed = false;
    if (this.ws && this.ws.readyState <= 1 && this.meetingId === meetingId) return;
    this.disconnect();
    this.meetingId = meetingId;
    try {
      this.ws = new WebSocket(wsUrl(`/ws/meetings/${meetingId}`));
    } catch (e) {
      this.scheduleReconnect();
      return;
    }
    this.ws.onopen = () => {
      console.log('[WS] 会议连接已建立:', meetingId);
      if (this.resetTimer) clearTimeout(this.resetTimer);
      this.resetTimer = window.setTimeout(() => { this.attempts = 0; this.resetTimer = null; }, 3000);
    };
    this.ws.onmessage = (ev) => this.handleMessage(ev);
    this.ws.onclose = (e) => {
      console.log('[WS] 会议连接关闭:', e.code, e.reason);
      if (this.resetTimer) { clearTimeout(this.resetTimer); this.resetTimer = null; }
      if (e.code === 4401) { this.handlers.onAuthRequired?.(); return; }
      if (e.code === 4429) { console.warn('[WS] 速率限制'); return; }
      if (e.code === 1000 || e.code === 1001) return; // 正常关闭
      this.scheduleReconnect();
    };
    this.ws.onerror = () => console.warn('[WS] 连接错误');
  }

  send(msg: object): void {
    if (this.ws && this.ws.readyState === 1) this.ws.send(JSON.stringify(msg));
  }

  disconnect(): void {
    this.destroyed = true;
    if (this.ws) {
      this.ws.onclose = null;
      this.ws.close();
      this.ws = null;
    }
    if (this.reconnectTimer) { clearTimeout(this.reconnectTimer); this.reconnectTimer = null; }
    this.meetingId = null;
    this.attempts = 0;
  }

  get currentMeetingId(): string | null {
    return this.meetingId;
  }

  private scheduleReconnect(): void {
    if (this.destroyed || !this.meetingId) return;
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    const delay = wsBackoffDelay(this.attempts);
    this.attempts++;
    console.log(`[WS] 会议 ${this.attempts} 次重连，${delay}ms 后重试`);
    this.reconnectTimer = window.setTimeout(() => {
      if (this.meetingId) this.connect(this.meetingId);
    }, delay);
  }

  private handleMessage(ev: MessageEvent): void {
    let msg: WsMessage;
    try { msg = JSON.parse(ev.data); } catch { return; }
    if (!msg || !msg.type) return;
    const h = this.handlers;
    switch (msg.type) {
      case 'snapshot': h.onSnapshot?.(msg.payload || {}); break;
      case 'replay.done': h.onReplayDone?.(msg.last_seq || 0); break;
      case 'agent.spoke': h.onAgentSpoke?.(msg); break;
      case 'stage.changed': h.onStageChanged?.(msg); break;
      case 'run.started': h.onRunStarted?.(msg); break;
      case 'control.signal': h.onControlSignal?.(msg); break;
      case 'control.ack': h.onControlAck?.(msg); break;
      case 'intervention.reply': h.onInterventionReply?.(msg); break;
      case 'borrow.awaiting_user': h.onBorrowRequest?.(msg); break;
      case 'borrow.approved_by_user':
      case 'borrow.rejected_by_user':
      case 'borrow.frozen':
      case 'borrow.auto_approved': h.onBorrowResolved?.(msg); break;
      case 'produce.progress': h.onProduceProgress?.(msg); break;
      case 'produce.degradation': h.onProduceDegradation?.(msg); break;
      case 'log.entry': h.onLogEntry?.(msg); break;
      case 'ping': this.send({ type: 'pong' }); break;
      default: console.debug('[WS] 未处理事件:', msg.type, msg);
    }
  }
}

/** 系统 WS：会议列表变更通知。返回断开函数。 */
export interface SystemWsHandlers {
  onMeetingsChanged?: () => void;
  onReady?: () => void;
}

export function connectSystemWs(handlers: SystemWsHandlers): () => void {
  let ws: WebSocket | null = null;
  let reconnectTimer: number | null = null;
  let resetTimer: number | null = null;
  let attempts = 0;
  let disposed = false;

  const connect = () => {
    if (disposed) return;
    if (ws && ws.readyState <= 1) return;
    if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
    try {
      ws = new WebSocket(wsUrl('/ws/system'));
    } catch {
      scheduleReconnect();
      return;
    }
    ws.onopen = () => {
      console.log('[WS] 系统连接已建立');
      if (resetTimer) clearTimeout(resetTimer);
      resetTimer = window.setTimeout(() => { attempts = 0; resetTimer = null; }, 3000);
    };
    ws.onmessage = (ev) => {
      let msg: WsMessage;
      try { msg = JSON.parse(ev.data); } catch { return; }
      if (!msg) return;
      switch (msg.type) {
        case 'system.meetings.changed': handlers.onMeetingsChanged?.(); break;
        case 'system.ready': handlers.onReady?.(); break;
        case 'ping': if (ws?.readyState === 1) ws.send(JSON.stringify({ type: 'pong' })); break;
      }
    };
    ws.onclose = (e) => {
      if (resetTimer) { clearTimeout(resetTimer); resetTimer = null; }
      if (e.code === 1000 || e.code === 1001) return;
      scheduleReconnect();
    };
    ws.onerror = () => ws?.close();
  };

  const scheduleReconnect = () => {
    if (disposed) return;
    if (reconnectTimer) clearTimeout(reconnectTimer);
    const delay = wsBackoffDelay(attempts);
    attempts++;
    console.log(`[WS] 系统 ${attempts} 次重连，${delay}ms 后重试`);
    reconnectTimer = window.setTimeout(connect, delay);
  };

  connect();

  // 网络恢复立即重连
  const onlineHandler = () => {
    attempts = 0;
    if (!ws || ws.readyState > 1) connect();
  };
  window.addEventListener('online', onlineHandler);

  return () => {
    disposed = true;
    window.removeEventListener('online', onlineHandler);
    if (reconnectTimer) clearTimeout(reconnectTimer);
    if (resetTimer) clearTimeout(resetTimer);
    if (ws) { ws.onclose = null; ws.close(); }
  };
}
