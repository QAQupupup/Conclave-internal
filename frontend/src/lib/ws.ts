import { useWSStore } from '@/stores/ws-slice';
import { useAuthStore } from '@/stores/auth-slice';
import { agUIClient } from './ag-ui/client';
import {
  WS_HEARTBEAT_INTERVAL,
  WS_RECONNECT_BASE_DELAY,
  WS_RECONNECT_MAX_DELAY,
} from './constants';

type WsEventMap = Record<string, (...args: unknown[]) => void>;

export class WsClient {
  private ws: WebSocket | null = null;
  private url: string;
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private shouldReconnect = true;
  private eventListeners: Map<string, Set<(...args: unknown[]) => void>> = new Map();
  private lastSeq: number = 0;

  constructor(url: string) {
    this.url = url;
  }

  connect(meetingId: string) {
    this.disconnect();
    this.shouldReconnect = true;
    this.createConnection(meetingId);
  }

  private createConnection(meetingId: string) {
    // 安全关闭已有连接（防止旧连接泄漏）
    if (this.ws) {
      this.stopHeartbeat();
      try { this.ws.close(1000, 'reconnect'); } catch { /* ignore */ }
      this.ws = null;
    }

    const wsStore = useWSStore.getState();
    wsStore.setStatus('connecting');

    const token = useAuthStore.getState().token;
    const wsUrl = new URL(this.url, window.location.origin);
    wsUrl.protocol = wsUrl.protocol.replace('http', 'ws');
    wsUrl.pathname = `/ws/${meetingId}`;
    if (this.lastSeq > 0) wsUrl.searchParams.set('from_seq', String(this.lastSeq));
    if (token) wsUrl.searchParams.set('token', token);

    let ws: WebSocket;
    try {
      ws = new WebSocket(wsUrl.toString());
      this.ws = ws;
    } catch {
      this.scheduleReconnect(meetingId);
      return;
    }

    // 用闭包变量 ws 做竞态防护：旧连接的延迟 onclose/onopen 不会干扰新连接
    ws.onopen = () => {
      if (this.ws !== ws) return;
      const s = useWSStore.getState();
      s.setStatus('connected');
      s.resetReconnectCount();
      this.startHeartbeat();
      this.emit('open');
    };

    ws.onmessage = (event) => {
      if (this.ws !== ws) return;
      try {
        const msg = JSON.parse(event.data);
        this.handleMessage(msg);
      } catch (e) {
        console.warn('[ws] failed to parse message', e);
      }
    };

    ws.onerror = () => {
      if (this.ws !== ws) return;
      useWSStore.getState().setError('连接异常');
    };

    ws.onclose = (event) => {
      // 忽略旧连接的延迟 close 事件——只处理当前活跃连接
      if (this.ws !== ws) return;
      this.stopHeartbeat();
      useWSStore.getState().setStatus('disconnected');
      this.emit('close', event);
      if (this.shouldReconnect && event.code !== 1000) {
        this.scheduleReconnect(meetingId);
      }
    };
  }

  private handleMessage(msg: Record<string, unknown>) {
    const type = msg.type as string;

    // 心跳协议：收到 ping 回复 pong，收到 pong 忽略
    if (type === 'pong') return;
    if (type === 'ping') {
      this.send({ type: 'pong' });
      return;
    }

    // Update lastSeq
    if (typeof msg.seq === 'number') {
      this.lastSeq = Math.max(this.lastSeq, msg.seq);
      useWSStore.getState().setLastSeq(this.lastSeq);
    }

    // Feed to AG-UI adapter
    agUIClient.handleRawMessage(msg);

    this.emit('message', msg);
  }

  private startHeartbeat() {
    this.stopHeartbeat();
    this.heartbeatTimer = setInterval(() => {
      if (this.ws?.readyState === WebSocket.OPEN) {
        this.ws.send(JSON.stringify({ type: 'ping' }));
      }
    }, WS_HEARTBEAT_INTERVAL);
  }

  private stopHeartbeat() {
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
  }

  private scheduleReconnect(meetingId: string) {
    if (this.reconnectTimer) return;
    const s = useWSStore.getState();
    s.incReconnectCount();
    const delay = Math.min(
      WS_RECONNECT_BASE_DELAY * Math.pow(2, s.reconnectCount),
      WS_RECONNECT_MAX_DELAY
    );
    s.setError(`连接断开，${Math.round(delay / 1000)}秒后重试...`);
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      if (this.shouldReconnect) this.createConnection(meetingId);
    }, delay);
  }

  send(data: unknown) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(data));
      return true;
    }
    return false;
  }

  sendControl(signal: string, payload: Record<string, unknown> = {}) {
    return this.send({ type: 'control.signal', signal, payload });
  }

  sendChat(content: string, replyTo?: string) {
    return this.send({ type: 'chat', content, replyTo });
  }

  sendReaction(reaction: string, targetId?: string) {
    return this.send({ type: 'reaction', reaction, target_id: targetId });
  }

  disconnect() {
    this.shouldReconnect = false;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.stopHeartbeat();
    if (this.ws) {
      try {
        this.ws.close(1000, 'client disconnect');
      } catch { /* ignore close error */ }
      this.ws = null;
    }
    useWSStore.getState().setStatus('disconnected');
  }

  on<K extends keyof WsEventMap>(event: K, handler: WsEventMap[K]) {
    if (!this.eventListeners.has(event)) {
      this.eventListeners.set(event, new Set());
    }
    this.eventListeners.get(event)!.add(handler);
    return () => this.off(event, handler);
  }

  off<K extends keyof WsEventMap>(event: K, handler: WsEventMap[K]) {
    this.eventListeners.get(event)?.delete(handler);
  }

  private emit(event: string, ...args: unknown[]) {
    this.eventListeners.get(event)?.forEach((h) => {
      try {
        h(...args);
      } catch (e) {
        console.error('[ws] listener error', e);
      }
    });
  }
}

export const wsClient = new WsClient('/ws');
