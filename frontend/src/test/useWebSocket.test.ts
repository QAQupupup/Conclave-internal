/**
 * useWebSocket hook 单元测试
 *
 * 测试目标：
 *  - 验证会议 WebSocket 钩子的连接生命周期（建立、断开、重连、卸载清理）
 *  - 验证各类 WS 帧的解析与 dispatch：
 *      snapshot / replay.done / error / ping（控制帧）
 *      agent.spoke / stage.changed 等 DomainEvent（经 rAF 批处理）
 *  - 验证 DomainEvent 的 rAF 批处理机制（同帧多事件合并为单次 flush 后 dispatch）
 *  - 验证断线重连的指数退避策略：delay = min(1000 * 2^attempt, 30000)
 *  - 验证超过 MAX_RECONNECT_ATTEMPTS(8) 后停止重连并设置 connectionError
 *  - 验证 unmount 时正确清理 WebSocket 连接、重连定时器与 rAF 批处理
 *
 * 实现要点（不依赖真实 WS 服务器）：
 *  - 全局 Mock WebSocket 构造函数（MockWebSocket），可模拟 open/message/error/close
 *  - 自定义 requestAnimationFrame / cancelAnimationFrame mock，精确控制批处理 flush
 *  - vi.useFakeTimers() 控制重连退避的 setTimeout
 *  - 使用 @testing-library/react 的 renderHook 渲染 hook，act 包裹副作用
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useWebSocket } from '../hooks/useWebSocket.ts'
import type { Dispatch } from 'react'
import type { MeetingAction } from '../store/meetingReducer.ts'
import type { DomainEvent, MeetingState } from '../types/events.ts'

// ---------- 保存真实全局，便于 afterEach 恢复 ----------
// 在模块加载时（任何 fake timer 之前）捕获真实实现
const g = globalThis as Record<string, unknown>
const originalWebSocket = g.WebSocket
const originalRAF = globalThis.requestAnimationFrame
const originalCAF = globalThis.cancelAnimationFrame

// ---------- requestAnimationFrame mock（可控批处理） ----------
type RafCallback = (ts: number) => void
interface RafTask {
  id: number
  cb: RafCallback
}
let rafQueue: RafTask[] = []
let rafIdCounter = 0

const mockRAF = (cb: RafCallback): number => {
  const id = ++rafIdCounter
  rafQueue.push({ id, cb })
  return id
}
const mockCAF = (id: number): void => {
  rafQueue = rafQueue.filter((t) => t.id !== id)
}
/** 立即执行所有已排队的 rAF 回调（模拟一帧渲染） */
function flushRaf(): void {
  const current = rafQueue
  rafQueue = []
  for (const { cb } of current) cb(0)
}
function resetRaf(): void {
  rafQueue = []
  rafIdCounter = 0
}

// ---------- WebSocket mock ----------
type WsListener = ((ev: Event | MessageEvent) => void) | null

class MockWebSocket {
  static readonly CONNECTING = 0
  static readonly OPEN = 1
  static readonly CLOSING = 2
  static readonly CLOSED = 3

  static instances: MockWebSocket[] = []
  static last(): MockWebSocket {
    return MockWebSocket.instances[MockWebSocket.instances.length - 1]
  }
  static reset(): void {
    MockWebSocket.instances = []
  }

  url: string
  readyState: number = MockWebSocket.CONNECTING
  onopen: WsListener = null
  onmessage: WsListener = null
  onerror: WsListener = null
  onclose: WsListener = null
  sent: string[] = []
  closeCalls = 0

  constructor(url: string) {
    this.url = url
    MockWebSocket.instances.push(this)
  }

  send(data: string): void {
    this.sent.push(data)
  }

  close(): void {
    this.closeCalls += 1
    this.readyState = MockWebSocket.CLOSED
  }

  // ---- 模拟服务端事件（测试驱动） ----
  simulateOpen(): void {
    this.readyState = MockWebSocket.OPEN
    this.onopen?.(new Event('open'))
  }
  simulateMessage(data: unknown): void {
    const payload = typeof data === 'string' ? data : JSON.stringify(data)
    this.onmessage?.({ data: payload } as MessageEvent)
  }
  simulateError(): void {
    this.onerror?.(new Event('error'))
  }
  simulateClose(): void {
    this.readyState = MockWebSocket.CLOSED
    this.onclose?.(new Event('close'))
  }
}

// ---------- 共享状态 ----------
let dispatch: Dispatch<MeetingAction>

/** 渲染 hook（默认 meetingId='m1'），返回 renderHook 结果 */
function setup(meetingId: string | null = 'm1') {
  return renderHook(() => useWebSocket(meetingId, dispatch))
}

beforeEach(() => {
  dispatch = vi.fn() as unknown as Dispatch<MeetingAction>
  MockWebSocket.reset()
  resetRaf()
  localStorage.clear()
  vi.useFakeTimers()
  // 覆盖 fake timer 自带的 rAF，使用完全可控的队列实现
  g.requestAnimationFrame = mockRAF
  g.cancelAnimationFrame = mockCAF
  g.WebSocket = MockWebSocket
})

afterEach(() => {
  g.requestAnimationFrame = originalRAF
  g.cancelAnimationFrame = originalCAF
  g.WebSocket = originalWebSocket
  vi.useRealTimers()
  vi.restoreAllMocks()
})

describe('useWebSocket', () => {
  describe('连接生命周期', () => {
    it('meetingId 为 null 时不建立 WebSocket 连接', () => {
      const { result } = setup(null)
      expect(MockWebSocket.instances).toHaveLength(0)
      expect(result.current.connected).toBe(false)
      expect(result.current.lastSeq).toBe(0)
      expect(result.current.connectionError).toBeNull()
    })

    it('连接成功后 connected 变为 true 且清空错误', () => {
      const { result } = setup('m1')
      expect(MockWebSocket.instances).toHaveLength(1)
      expect(MockWebSocket.last().url).toContain('/ws/meetings/m1')

      act(() => {
        MockWebSocket.last().simulateOpen()
      })
      expect(result.current.connected).toBe(true)
      expect(result.current.connectionError).toBeNull()
      expect(result.current.lastSeq).toBe(0)
    })

    it('onerror 时设置 connectionError 但不改变 connected', () => {
      const { result } = setup('m1')
      act(() => {
        MockWebSocket.last().simulateOpen()
        MockWebSocket.last().simulateError()
      })
      expect(result.current.connectionError).toMatch(/连接异常/)
      expect(result.current.connected).toBe(true)
    })
  })

  describe('消息处理', () => {
    it('收到 snapshot 帧时 dispatch snapshot action', () => {
      const { result } = setup('m1')
      const ws = MockWebSocket.last()
      act(() => {
        ws.simulateOpen()
      })
      const snapshotPayload: MeetingState = {
        meeting_id: 'm1',
        topic: 'snapshot topic',
        stage: 'clarify',
        status: 'running',
      } as MeetingState
      act(() => {
        ws.simulateMessage({ type: 'snapshot', payload: snapshotPayload })
      })
      expect(dispatch).toHaveBeenCalledWith({
        type: 'snapshot',
        payload: expect.objectContaining({ meeting_id: 'm1', topic: 'snapshot topic' }),
      })
      expect(result.current.connected).toBe(true)
    })

    it('收到 replay.done 帧时更新 lastSeq 并 dispatch', () => {
      const { result } = setup('m1')
      const ws = MockWebSocket.last()
      act(() => {
        ws.simulateOpen()
        ws.simulateMessage({ type: 'replay.done', events: 7, last_seq: 42 })
      })
      expect(result.current.lastSeq).toBe(42)
      expect(dispatch).toHaveBeenCalledWith({ type: 'replay.done', events: 7 })
    })

    it('收到 error 帧时 dispatch error action', () => {
      const { result } = setup('m1')
      const ws = MockWebSocket.last()
      act(() => {
        ws.simulateOpen()
        ws.simulateMessage({ type: 'error', message: '后端炸了' })
      })
      expect(dispatch).toHaveBeenCalledWith({ type: 'error', message: '后端炸了' })
    })

    it('收到 ping 帧时回复 pong 且不 dispatch', () => {
      const { result } = setup('m1')
      const ws = MockWebSocket.last()
      act(() => {
        ws.simulateOpen()
        ws.simulateMessage({ type: 'ping', ts: 1700000000000 })
      })
      expect(ws.sent).toHaveLength(1)
      expect(JSON.parse(ws.sent[0])).toEqual({ type: 'pong', ts: 1700000000000 })
      expect(dispatch).not.toHaveBeenCalled()
      expect(result.current.connected).toBe(true)
    })

    it('DomainEvent 延迟到 rAF flush 后才 dispatch', () => {
      const { result } = setup('m1')
      const ws = MockWebSocket.last()
      act(() => {
        ws.simulateOpen()
      })
      dispatch.mockClear()
      const evt: DomainEvent = {
        type: 'agent.spoke',
        meeting_id: 'm1',
        ts: '2026-01-01T00:00:00Z',
        payload: {
          meeting_id: 'm1',
          role: 'moderator',
          stage: 'clarify',
          content: 'hi',
          claim_refs: [],
          message_id: 'msg-1',
        },
      }
      act(() => {
        ws.simulateMessage(evt)
      })
      // rAF 尚未 flush，事件被缓冲，不应 dispatch
      expect(dispatch).not.toHaveBeenCalled()
      act(() => {
        flushRaf()
      })
      expect(dispatch).toHaveBeenCalledTimes(1)
      expect(dispatch).toHaveBeenCalledWith({
        type: 'event',
        event: expect.objectContaining({ type: 'agent.spoke' }),
      })
    })

    it('同一帧内多个 DomainEvent 批量合并到单次 rAF flush', () => {
      const { result } = setup('m1')
      const ws = MockWebSocket.last()
      act(() => {
        ws.simulateOpen()
      })
      dispatch.mockClear()
      const evt1: DomainEvent = {
        type: 'agent.spoke',
        meeting_id: 'm1',
        ts: '2026-01-01T00:00:00Z',
        payload: {
          meeting_id: 'm1',
          role: 'moderator',
          stage: 'clarify',
          content: 'a',
          claim_refs: [],
          message_id: 'm-1',
        },
      }
      const evt2: DomainEvent = {
        type: 'stage.changed',
        meeting_id: 'm1',
        ts: '2026-01-01T00:00:01Z',
        payload: { meeting_id: 'm1', from: 'clarify', to: 'intra_team' },
      }
      act(() => {
        ws.simulateMessage(evt1)
        ws.simulateMessage(evt2)
      })
      // 两个事件都应被缓冲，尚未 dispatch
      expect(dispatch).not.toHaveBeenCalled()
      act(() => {
        flushRaf()
      })
      expect(dispatch).toHaveBeenCalledTimes(2)
      expect(dispatch).toHaveBeenNthCalledWith(1, {
        type: 'event',
        event: expect.objectContaining({ type: 'agent.spoke' }),
      })
      expect(dispatch).toHaveBeenNthCalledWith(2, {
        type: 'event',
        event: expect.objectContaining({ type: 'stage.changed' }),
      })
    })
  })

  describe('断线重连', () => {
    /**
     * 退避公式：delay = min(1000 * 2^attempt, 30000)
     * - 每次 onclose 自增 attempt，onopen 重置为 0
     * - 当 attempt >= 8 时停止重连
     */
    it('使用指数退避策略重连（1000 → 2000 → 4000）', () => {
      const { result } = setup('m1')
      const ws1 = MockWebSocket.last()
      act(() => {
        ws1.simulateOpen()
        ws1.simulateClose() // attempt 0 → 1, delay = 1000
      })
      expect(result.current.connected).toBe(false)

      // 第 1 次重连：延迟 1000ms
      vi.advanceTimersByTime(999)
      expect(MockWebSocket.instances).toHaveLength(1)
      vi.advanceTimersByTime(1)
      expect(MockWebSocket.instances).toHaveLength(2)
      const ws2 = MockWebSocket.last()
      act(() => {
        ws2.simulateClose() // attempt 1 → 2, delay = 2000
      })

      // 第 2 次重连：延迟 2000ms
      vi.advanceTimersByTime(1999)
      expect(MockWebSocket.instances).toHaveLength(2)
      vi.advanceTimersByTime(1)
      expect(MockWebSocket.instances).toHaveLength(3)
      const ws3 = MockWebSocket.last()
      act(() => {
        ws3.simulateClose() // attempt 2 → 3, delay = 4000
      })

      // 第 3 次重连：延迟 4000ms
      vi.advanceTimersByTime(3999)
      expect(MockWebSocket.instances).toHaveLength(3)
      vi.advanceTimersByTime(1)
      expect(MockWebSocket.instances).toHaveLength(4)
    })

    it('成功重连（onopen）后重置退避计数', () => {
      const { result } = setup('m1')
      const ws1 = MockWebSocket.last()
      act(() => {
        ws1.simulateOpen()
        ws1.simulateClose() // delay = 1000
      })
      vi.advanceTimersByTime(1000) // 触发第 1 次重连 → ws2
      expect(MockWebSocket.instances).toHaveLength(2)
      const ws2 = MockWebSocket.last()
      // 重连成功：onopen 重置 attempt 为 0
      act(() => {
        ws2.simulateOpen()
      })
      expect(result.current.connected).toBe(true)

      // 再次断线：delay 应回到 1000（而非 2000），证明计数已重置
      act(() => {
        ws2.simulateClose()
      })
      vi.advanceTimersByTime(999)
      expect(MockWebSocket.instances).toHaveLength(2)
      vi.advanceTimersByTime(1)
      expect(MockWebSocket.instances).toHaveLength(3)
    })

    it('超过 MAX_RECONNECT_ATTEMPTS(8) 后停止重连并设置错误', () => {
      const { result } = setup('m1')
      const ws1 = MockWebSocket.last()
      act(() => {
        ws1.simulateOpen()
        ws1.simulateClose() // 第 1 次 onclose，安排第 1 次重连
      })

      // 循环触发 8 次重连：每次 advance 触发 connect → 新 ws → 立即 close
      for (let i = 0; i < 8; i++) {
        // 最大单次延迟为 30000ms，advance 30000 必然触发下一次重连
        vi.advanceTimersByTime(30_000)
        const ws = MockWebSocket.last()
        act(() => {
          ws.simulateClose()
        })
      }

      // 初始 1 次 + 8 次重连 = 9 个 ws 实例
      expect(MockWebSocket.instances).toHaveLength(9)
      // 第 9 次 onclose 时 attempt 已达 8，触发停止
      expect(result.current.connectionError).toMatch(/连续重连 8 次失败/)
      expect(result.current.connected).toBe(false)

      // 不应再发起新连接
      const countBefore = MockWebSocket.instances.length
      vi.advanceTimersByTime(120_000)
      expect(MockWebSocket.instances.length).toBe(countBefore)
    })
  })

  describe('卸载清理', () => {
    it('unmount 时关闭处于 OPEN 的 WebSocket 并清除回调', () => {
      const { unmount } = setup('m1')
      const ws = MockWebSocket.last()
      act(() => {
        ws.simulateOpen()
      })
      expect(ws.closeCalls).toBe(0)

      unmount()

      expect(ws.closeCalls).toBe(1) // cleanup 主动 close
      expect(ws.onopen).toBeNull()
      expect(ws.onmessage).toBeNull()
      expect(ws.onclose).toBeNull()
      // 清理后不应触发重连
      vi.advanceTimersByTime(60_000)
      expect(MockWebSocket.instances).toHaveLength(1)
    })

    it('unmount 时取消待执行的重连定时器', () => {
      const { unmount } = setup('m1')
      const ws = MockWebSocket.last()
      act(() => {
        ws.simulateOpen()
        ws.simulateClose() // 安排重连定时器（1000ms）
      })
      expect(MockWebSocket.instances).toHaveLength(1)

      unmount()

      // 定时器已被清理，advance 不会发起新连接
      vi.advanceTimersByTime(60_000)
      expect(MockWebSocket.instances).toHaveLength(1)
    })

    it('unmount 时取消待执行的 rAF 批处理', () => {
      const { result, unmount } = setup('m1')
      const ws = MockWebSocket.last()
      act(() => {
        ws.simulateOpen()
      })
      dispatch.mockClear()
      act(() => {
        ws.simulateMessage({
          type: 'agent.spoke',
          meeting_id: 'm1',
          ts: '2026-01-01T00:00:00Z',
          payload: {
            meeting_id: 'm1',
            role: 'moderator',
            stage: 'clarify',
            content: 'x',
            claim_refs: [],
            message_id: 'm-x',
          },
        })
      })
      // 此刻 rAF 已排队但未执行
      expect(dispatch).not.toHaveBeenCalled()

      unmount()

      // 即使 flush，rAF 已被 cancelAnimationFrame 取消，不应 dispatch
      act(() => {
        flushRaf()
      })
      expect(dispatch).not.toHaveBeenCalled()
    })
  })

  describe('发送控制信号', () => {
    it('未连接时 sendControl 设置 connectionError 且不发送', () => {
      const { result } = setup('m1')
      const ws = MockWebSocket.last()
      // ws 处于 CONNECTING，未 OPEN
      act(() => {
        result.current.sendControl('pause')
      })
      expect(result.current.connectionError).toMatch(/未连接/)
      expect(ws.sent).toHaveLength(0)
    })

    it('连接后 sendControl 发送 control.signal 帧', () => {
      const { result } = setup('m1')
      const ws = MockWebSocket.last()
      act(() => {
        ws.simulateOpen()
      })
      act(() => {
        result.current.sendControl('pause', { reason: 'user' })
      })
      expect(ws.sent).toHaveLength(1)
      expect(JSON.parse(ws.sent[0])).toEqual({
        type: 'control.signal',
        signal: 'pause',
        payload: { reason: 'user' },
      })
      expect(result.current.connectionError).toBeNull()
    })
  })
})
