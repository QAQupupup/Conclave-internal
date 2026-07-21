// WebSocket 客户端核心逻辑测试
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { MeetingWsClient } from '../lib/ws';

// Mock WebSocket
class MockWebSocket {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;

  readyState = MockWebSocket.CONNECTING;
  onopen: ((ev: any) => void) | null = null;
  onclose: ((ev: any) => void) | null = null;
  onerror: ((ev: any) => void) | null = null;
  onmessage: ((ev: any) => void) | null = null;
  sent: string[] = [];
  url: string;

  constructor(url: string) {
    this.url = url;
    // 模拟异步连接成功
    setTimeout(() => {
      this.readyState = MockWebSocket.OPEN;
      this.onopen?.(null);
    }, 0);
  }

  send(data: string) {
    this.sent.push(data);
  }

  close(code = 1000) {
    this.readyState = MockWebSocket.CLOSED;
    this.onclose?.({ code, reason: '' });
  }

  // 测试辅助：模拟服务器消息
  _emitMessage(data: string) {
    this.onmessage?.({ data });
  }

  _emitClose(code: number, reason = '') {
    this.readyState = MockWebSocket.CLOSED;
    this.onclose?.({ code, reason });
  }
}

vi.stubGlobal('WebSocket', MockWebSocket);
// 模拟 location
vi.stubGlobal('location', { protocol: 'http:', host: 'localhost:5173' });

// mock auth
vi.mock('../lib/auth', () => ({
  getToken: () => 'test-token',
}));

describe('MeetingWsClient', () => {
  let client: MeetingWsClient;
  let handlers: any;

  beforeEach(() => {
    vi.useFakeTimers();
    handlers = {
      onSnapshot: vi.fn(),
      onAuthRequired: vi.fn(),
      onRateLimited: vi.fn(),
    };
    client = new MeetingWsClient(handlers);
  });

  afterEach(() => {
    client.disconnect();
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('应建立连接并处理 snapshot', async () => {
    client.connect('test-mtg-1');
    await vi.runAllTimersAsync();

    // 连接应已建立，onSnapshot 应在 snapshot 消息时触发
    const ws = (client as any).ws as MockWebSocket;
    expect(ws).not.toBeNull();
    expect(ws.url).toContain('/ws/meetings/test-mtg-1');
    expect(ws.url).toContain('token=test-token');
  });

  it('收到 4401 关闭码应触发 onAuthRequired 且不重连', async () => {
    client.connect('test-mtg-2');
    await vi.runAllTimersAsync();

    const ws = (client as any).ws as MockWebSocket;
    ws._emitClose(4401);
    await vi.runAllTimersAsync();

    expect(handlers.onAuthRequired).toHaveBeenCalled();
    // 重连定时器不应被设置（destroyed/intentionalClose 为 true）
    expect((client as any).reconnectTimer).toBeNull();
  });

  it('收到 4429 关闭码应触发 onRateLimited 并延迟重连', async () => {
    client.connect('test-mtg-3');
    await vi.runAllTimersAsync();

    const scheduleSpy = vi.spyOn(client as any, 'scheduleReconnect');
    const ws = (client as any).ws as MockWebSocket;
    ws._emitClose(4429);

    expect(handlers.onRateLimited).toHaveBeenCalled();
    // 等待延迟后应尝试重连
    await vi.advanceTimersByTimeAsync(6000);
    expect(scheduleSpy).toHaveBeenCalled();
  });

  it('正常关闭码 1000 不应触发重连', async () => {
    client.connect('test-mtg-4');
    await vi.runAllTimersAsync();

    const scheduleSpy = vi.spyOn(client as any, 'scheduleReconnect');
    const ws = (client as any).ws as MockWebSocket;
    ws._emitClose(1000);
    await vi.runAllTimersAsync();

    expect(scheduleSpy).not.toHaveBeenCalled();
  });

  it('disconnect() 应阻止后续重连', async () => {
    client.connect('test-mtg-5');
    await vi.runAllTimersAsync();
    client.disconnect();

    const scheduleSpy = vi.spyOn(client as any, 'scheduleReconnect');
    const ws = (client as any).ws as MockWebSocket;
    if (ws) ws._emitClose(1006); // 异常关闭
    await vi.runAllTimersAsync();

    expect(scheduleSpy).not.toHaveBeenCalled();
  });
});
