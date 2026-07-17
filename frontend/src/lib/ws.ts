/* Conclave WebSocket 客户端
 * 会议 WS：实时事件推送（Agent 发言、阶段切换、介入回复、借调请求）
 * 系统 WS：会议列表变更、心跳
 * 含指数退避重连（delay = min(MAX, BASE*2^attempt) + jitter）
 *
 * [前端审查修复]
 * - 修复 connect() 中 destroyed 标志位 bug（disconnect() 将其设回 true 导致重连永远失效）
 * - 添加客户端心跳（每 25s 发 ping，60s 无消息则主动关闭重连）
 * - onerror 主动 close 以触发重连
 * - 4403/4429 特殊处理
 */
import { getToken } from './auth';

const WS_BACKOFF_BASE = 1000;
const WS_BACKOFF_MAX = 30000;
// 客户端心跳间隔（毫秒）
const WS_HEARTBEAT_INTERVAL = 25000;
// 心跳超时：超过此时长未收到任何消息则视为连接已断
const WS_HEARTBEAT_TIMEOUT = 60000;

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
  onRateLimited?: () => void;
}

/** 会议 WebSocket 客户端（带指数退避重连） */
export class MeetingWsClient {
  private ws: WebSocket | null = null;
  private meetingId: string | null = null;
  private reconnectTimer: number | null = null;
  private resetTimer: number | null = null;
  private heartbeatTimer: number | null = null;
  private heartbeatTimeoutTimer: number | null = null;
  private attempts = 0;
  private destroyed = false;
  /** 是否由用户主动关闭（logout/disconnect），不触发重连 */
  private intentionalClose = false;

  constructor(private handlers: MeetingWsHandlers) {}

  connect(meetingId: string): void {
    // [严重bug修复] 原代码先设 destroyed=false，再调用 disconnect()（内部设回 true），
    // 导致 scheduleReconnect() 永远直接返回，重连完全失效。
    // 正确顺序：先 disconnect() 清理旧连接（清理方法不再修改 destroyed 标志），再设标志位。
    this.intentionalClose = false;
    this.disconnect({ silent: true });
    this.destroyed = false;
    this.meetingId = meetingId;
    this.attempts = 0;
    this.createConnection();
  }

  private createConnection(): void {
    const mid = this.meetingId;
    if (!mid || this.destroyed) return;
    try {
      this.ws = new WebSocket(wsUrl(`/ws/meetings/${mid}`));
    } catch (e) {
      console.warn('[WS] 创建连接失败，将重试:', e);
      this.scheduleReconnect();
      return;
    }
    this.ws.onopen = () => {
      console.log('[WS] 会议连接已建立:', mid);
      if (this.resetTimer) { clearTimeout(this.resetTimer); this.resetTimer = null; }
      this.resetTimer = window.setTimeout(() => { this.attempts = 0; this.resetTimer = null; }, 3000);
      this.startHeartbeat();
    };
    this.ws.onmessage = (ev) => {
      this.resetHeartbeatTimeout();
      this.handleMessage(ev);
    };
    this.ws.onclose = (e) => {
      console.log('[WS] 会议连接关闭:', e.code, e.reason);
      this.clearHeartbeat();
      if (this.resetTimer) { clearTimeout(this.resetTimer); this.resetTimer = null; }
      if (this.intentionalClose || this.destroyed) return;
      if (e.code === 4401) {
        // 认证失效：停止重连，通知上层跳转登录
        this.handlers.onAuthRequired?.();
        return;
      }
      if (e.code === 4403) {
        // 权限拒绝：停止重连
        console.warn('[WS] 权限拒绝，停止重连');
        return;
      }
      if (e.code === 4429) {
        this.handlers.onRateLimited?.();
        // 速率限制：延迟更长时间后重试
        window.setTimeout(() => this.scheduleReconnect(), 5000);
        return;
      }
      if (e.code === 1000 || e.code === 1001) return; // 正常关闭
      this.scheduleReconnect();
    };
    this.ws.onerror = (e) => {
      console.warn('[WS] 连接错误，将关闭并重连');
      // onerror 后通常紧跟 onclose，主动 close 确保进入重连逻辑
      try { this.ws?.close(); } catch { /* noop */ }
    };
  }

  private startHeartbeat(): void {
    this.clearHeartbeat();
    // 定时发送客户端 ping
    this.heartbeatTimer = window.setInterval(() => {
      if (this.ws?.readyState === WebSocket.OPEN) {
        try { this.ws.send(JSON.stringify({ type: 'ping' })); } catch { /* noop */ }
      }
    }, WS_HEARTBEAT_INTERVAL);
    this.resetHeartbeatTimeout();
  }

  private resetHeartbeatTimeout(): void {
    if (this.heartbeatTimeoutTimer) { clearTimeout(this.heartbeatTimeoutTimer); }
    this.heartbeatTimeoutTimer = window.setTimeout(() => {
      console.warn('[WS] 心跳超时，主动关闭连接以触发重连');
      try { this.ws?.close(); } catch { /* noop */ }
    }, WS_HEARTBEAT_TIMEOUT);
  }

  private clearHeartbeat(): void {
    if (this.heartbeatTimer) { clearInterval(this.heartbeatTimer); this.heartbeatTimer = null; }
    if (this.heartbeatTimeoutTimer) { clearTimeout(this.heartbeatTimeoutTimer); this.heartbeatTimeoutTimer = null; }
  }

  send(msg: object): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      try {
        this.ws.send(JSON.stringify(msg));
      } catch (e) {
        console.warn('[WS] 发送消息失败:', e);
      }
    } else {
      // 连接未就绪：消息暂不发送（控制类操作调用方应感知）
      console.debug('[WS] 连接未就绪，消息被丢弃:', msg);
    }
  }

  disconnect(opts: { silent?: boolean } = {}): void {
    this.destroyed = true;
    if (!opts.silent) this.intentionalClose = true;
    this.clearHeartbeat();
    if (this.ws) {
      this.ws.onclose = null;
      this.ws.onerror = null;
      try { this.ws.close(); } catch { /* noop */ }
      this.ws = null;
    }
    if (this.reconnectTimer) { clearTimeout(this.reconnectTimer); this.reconnectTimer = null; }
    if (this.resetTimer) { clearTimeout(this.resetTimer); this.resetTimer = null; }
    this.meetingId = null;
    this.attempts = 0;
  }

  get currentMeetingId(): string | null {
    return this.meetingId;
  }

  private scheduleReconnect(): void {
    if (this.destroyed || this.intentionalClose || !this.meetingId) return;
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    const delay = wsBackoffDelay(this.attempts);
    this.attempts++;
    console.log(`[WS] 会议第 ${this.attempts} 次重连，${delay}ms 后重试`);
    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = null;
      if (!this.destroyed && this.meetingId) {
        this.createConnection();
      }
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
      case 'pong': /* 心跳响应，已在 resetHeartbeatTimeout 中处理 */ break;
      case 'ping': this.send({ type: 'pong' }); break;
      case 'error':
        if (msg.message && /未授权|未认证|401/i.test(String(msg.message))) {
          h.onAuthRequired?.();
        }
        break;
      default: console.debug('[WS] 未处理事件:', msg.type, msg);
    }
  }
}

/** 系统 WS：会议列表变更通知。返回断开函数。 */
export interface SystemWsHandlers {
  onMeetingsChanged?: () => void;
  onReady?: () => void;
  onAuthRequired?: () => void;
}

export function connectSystemWs(handlers: SystemWsHandlers): () => void {
  let ws: WebSocket | null = null;
  let reconnectTimer: number | null = null;
  let resetTimer: number | null = null;
  let heartbeatTimer: number | null = null;
  let heartbeatTimeoutTimer: number | null = null;
  let attempts = 0;
  let disposed = false;
  let intentionalClose = false;

  const clearHeartbeat = () => {
    if (heartbeatTimer) { clearInterval(heartbeatTimer); heartbeatTimer = null; }
    if (heartbeatTimeoutTimer) { clearTimeout(heartbeatTimeoutTimer); heartbeatTimeoutTimer = null; }
  };

  const resetHeartbeatTimeout = () => {
    if (heartbeatTimeoutTimer) clearTimeout(heartbeatTimeoutTimer);
    heartbeatTimeoutTimer = window.setTimeout(() => {
      console.warn('[WS] 系统心跳超时，主动关闭重连');
      try { ws?.close(); } catch { /* noop */ }
    }, WS_HEARTBEAT_TIMEOUT);
  };

  const connect = () => {
    if (disposed || intentionalClose) return;
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
      // 心跳
      clearHeartbeat();
      heartbeatTimer = window.setInterval(() => {
        if (ws?.readyState === WebSocket.OPEN) {
          try { ws.send(JSON.stringify({ type: 'ping' })); } catch { /* noop */ }
        }
      }, WS_HEARTBEAT_INTERVAL);
      resetHeartbeatTimeout();
    };
    ws.onmessage = (ev) => {
      resetHeartbeatTimeout();
      let msg: WsMessage;
      try { msg = JSON.parse(ev.data); } catch { return; }
      if (!msg) return;
      switch (msg.type) {
        case 'system.meetings.changed': handlers.onMeetingsChanged?.(); break;
        case 'system.ready': handlers.onReady?.(); break;
        case 'pong': break;
        case 'ping': if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'pong' })); break;
        case 'error':
          if (msg.message && /未授权|未认证|401|权限/i.test(String(msg.message))) {
            handlers.onAuthRequired?.();
          }
          break;
      }
    };
    ws.onclose = (e) => {
      clearHeartbeat();
      if (resetTimer) { clearTimeout(resetTimer); resetTimer = null; }
      if (disposed || intentionalClose) return;
      if (e.code === 4401 || e.code === 4403) {
        handlers.onAuthRequired?.();
        return;
      }
      if (e.code === 4429) {
        window.setTimeout(scheduleReconnect, 5000);
        return;
      }
      if (e.code === 1000 || e.code === 1001) return;
      scheduleReconnect();
    };
    ws.onerror = () => {
      try { ws?.close(); } catch { /* noop */ }
    };
  };

  const scheduleReconnect = () => {
    if (disposed || intentionalClose) return;
    if (reconnectTimer) clearTimeout(reconnectTimer);
    const delay = wsBackoffDelay(attempts);
    attempts++;
    console.log(`[WS] 系统第 ${attempts} 次重连，${delay}ms 后重试`);
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
    intentionalClose = true;
    window.removeEventListener('online', onlineHandler);
    clearHeartbeat();
    if (reconnectTimer) clearTimeout(reconnectTimer);
    if (resetTimer) clearTimeout(resetTimer);
    if (ws) { ws.onclose = null; ws.onerror = null; try { ws.close(); } catch { /* noop */ } ws = null; }
  };
}
