// WebSocket 钩子：连接会议 WS、接收回放与实时事件、分发到 reducer、发送控制信号
// 协议：
//   连接 → 收到 {type:'snapshot', payload} → 历史事件 DomainEvent → {type:'replay.done', events}
//   之后实时推送 DomainEvent（agent.spoke / stage.changed / evidence.attached / artifact.generated / control.signal / control.ack / error）
// 断线重连：携带 ?from_seq=<lastSeq>，后端只推增量事件，避免全量 snapshot
import { useEffect, useRef, useState, useCallback } from 'react'
import type { Dispatch } from 'react'
import type { MeetingAction } from '../store/meetingReducer.ts'
import type {
  BorrowRequestPayload,
  ControlRequest,
  DomainEvent,
  MeetingState,
} from '../types/events.ts'
import { STORAGE_KEYS } from '../constants.ts'

interface UseWebSocketResult {
  /** 是否已连接 */
  connected: boolean
  /** 连接错误信息（便于 UI 提示） */
  connectionError: string | null
  /** 最后收到的事件序列号（用于增量回放） */
  lastSeq: number
  /** 向后端发送控制信号（经 WS 转发给 Orchestrator） */
  sendControl: (signal: ControlRequest['signal'], payload?: Record<string, unknown>) => void
  /** 发送借调请求（loan 控制信号，payload 为借调三问） */
  sendBorrow: (payload: BorrowRequestPayload) => void
  /** 批准待审批的借调申请 */
  approveBorrow: (requestId: string) => void
  /** 拒绝待审批的借调申请 */
  rejectBorrow: (requestId: string, reason?: string) => void
  /** 冻结借调（本次会议后续不再允许借调） */
  freezeBorrow: () => void
}

/**
 * 根据 meetingId 和 lastSeq 推导 WS 地址
 * - lastSeq > 0 时携带 from_seq，后端只推增量事件（断线重连）
 * - lastSeq == 0 时全量回放（首次连接）
 * - 认证 token（如果 localStorage 有）附加到 query 参数
 */
function buildWsUrl(meetingId: string, fromSeq: number): string {
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
  const base = `${proto}://${window.location.host}/ws/meetings/${meetingId}`
  const params = new URLSearchParams()
  if (fromSeq > 0) params.set('from_seq', String(fromSeq))
  // 附加认证 token（优先 JWT authToken，兼容旧 dev apiToken）
  try {
    const token = localStorage.getItem(STORAGE_KEYS.authToken) || localStorage.getItem(STORAGE_KEYS.apiToken)
    if (token) params.set('token', token)
  } catch { /* localStorage 不可用时忽略 */ }
  const qs = params.toString()
  return qs ? `${base}?${qs}` : base
}

/** 自动重连的退避参数 */
const RECONNECT_BASE_DELAY = 1000
const RECONNECT_MAX_DELAY = 30000
// [CON-08 修复] 最大重连次数：超过后停止重连，避免 CPU 耗尽。
// 8 次后停止（约 4 分钟累积指数退避）
const MAX_RECONNECT_ATTEMPTS = 8

// 持续推送心跳的客户端心跳 watchdog：超过 90s 没收到任何消息则主动重连
// [CON-08 修复] 服务端僵尸连接不会发 ping，靠客户端 watchdog 检测
// （预留常量，未来在 onmessage 中加入 lastMessageTs 超时检查）

/**
 * 会议 WebSocket 钩子
 * @param meetingId 当前会议 id；为 null 时不连接
 * @param dispatch reducer 的 dispatch（用于把 WS 帧转为 state 更新）
 */
export function useWebSocket(
  meetingId: string | null,
  dispatch: Dispatch<MeetingAction>,
): UseWebSocketResult {
  const [connected, setConnected] = useState(false)
  const [connectionError, setConnectionError] = useState<string | null>(null)
  const [lastSeq, setLastSeq] = useState(0)
  const wsRef = useRef<WebSocket | null>(null)
  // lastSeq ref：重连时读取最新值，避免闭包陈旧
  const lastSeqRef = useRef(0)
  // dispatch 引用稳定（来自 useReducer），但用 ref 规避闭包陈旧问题
  const dispatchRef = useRef(dispatch)
  dispatchRef.current = dispatch
  // 重连控制
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const reconnectAttemptRef = useRef(0)
  const closedByUnmountRef = useRef(false)
  // rAF 事件批处理：同一帧内到达的多个 DomainEvent 合并为单次 dispatch，减少 re-render
  const pendingEventsRef = useRef<DomainEvent[]>([])
  const rafIdRef = useRef<number | null>(null)

  useEffect(() => {
    if (!meetingId) {
      setConnected(false)
      return
    }
    closedByUnmountRef.current = false

    // 切换会议时重置 lastSeq，确保新会议从 seq=0 开始获取全部历史事件
    setLastSeq(0)
    lastSeqRef.current = 0

    const connect = () => {
      if (closedByUnmountRef.current) return
      const fromSeq = lastSeqRef.current
      const url = buildWsUrl(meetingId!, fromSeq)
      const ws = new WebSocket(url)
      wsRef.current = ws

      ws.onopen = () => {
        if (closedByUnmountRef.current) return
        setConnected(true)
        setConnectionError(null)
        reconnectAttemptRef.current = 0
      }

      ws.onmessage = (ev: MessageEvent) => {
        if (closedByUnmountRef.current) return
        let data: unknown
        try {
          data = JSON.parse(typeof ev.data === 'string' ? ev.data : '')
        } catch {
          setConnectionError('收到无法解析的 WS 消息')
          return
        }
        // 区分控制帧与领域事件（统一以 Record 读取字段）
        const frame = data as Record<string, unknown>
        const type = typeof frame.type === 'string' ? frame.type : ''
        switch (type) {
          case 'ping':
            // [CON-08 修复] 服务端心跳：收到 ping 立即回 pong
            // 浏览器 WebSocket API 不支持协议层 ping/pong，需 application-level
            if (ws.readyState === WebSocket.OPEN) {
              ws.send(JSON.stringify({ type: 'pong', ts: frame.ts }))
            }
            return
          case 'snapshot':
            dispatchRef.current({
              type: 'snapshot',
              payload: frame.payload as MeetingState,
            })
            break
          case 'replay.done':
            // 追踪最后事件序列号（用于增量回放重连）
            if (typeof frame.last_seq === 'number') {
              lastSeqRef.current = frame.last_seq
              setLastSeq(frame.last_seq)
            }
            dispatchRef.current({
              type: 'replay.done',
              events: typeof frame.events === 'number' ? frame.events : 0,
            })
            break
          case 'error':
            dispatchRef.current({
              type: 'error',
              message: typeof frame.message === 'string' ? frame.message : '未知错误',
            })
            break
          case 'control.ack':
            // 后端 WS 单独回执：可据此更新状态（reducer 对 control.signal 已处理，此处忽略）
            break
          default: {
            // 其余视为 DomainEvent（type 即事件类型，如 agent.spoke / stage.changed 等）
            // rAF 批处理：累积到 pendingEvents，下一帧统一 dispatch，避免高频事件逐帧触发 re-render
            pendingEventsRef.current.push(frame as unknown as DomainEvent)
            if (rafIdRef.current === null) {
              rafIdRef.current = requestAnimationFrame(() => {
                rafIdRef.current = null
                const batch = pendingEventsRef.current
                pendingEventsRef.current = []
                // 批量 dispatch：每条事件仍然是独立 action，但集中在同一帧内，
                // React 18+ 会自动批处理同一事件回调内的多次 dispatch
                for (const evt of batch) {
                  dispatchRef.current({ type: 'event', event: evt })
                }
              })
            }
          }
        }
      }

      ws.onerror = () => {
        if (closedByUnmountRef.current) return
        setConnectionError('WebSocket 连接异常，请确认后端 127.0.0.1:8000 已启动')
      }

      ws.onclose = () => {
        if (closedByUnmountRef.current) return
        setConnected(false)
        wsRef.current = null
        // 自动重连（指数退避）
        const attempt = reconnectAttemptRef.current
        // [CON-08 修复] 最大重连次数：超过后停止重连，让用户手动刷新
        if (MAX_RECONNECT_ATTEMPTS > 0 && attempt >= MAX_RECONNECT_ATTEMPTS) {
          setConnectionError(
            `WebSocket 连续重连 ${MAX_RECONNECT_ATTEMPTS} 次失败，请手动刷新页面`,
          )
          return
        }
        reconnectAttemptRef.current += 1
        const delay = Math.min(
          RECONNECT_BASE_DELAY * Math.pow(2, attempt),
          RECONNECT_MAX_DELAY,
        )
        if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current)
        reconnectTimerRef.current = setTimeout(connect, delay)
      }
    }

    connect()

    return () => {
      closedByUnmountRef.current = true
      // 取消待处理的 rAF 批处理
      if (rafIdRef.current !== null) {
        cancelAnimationFrame(rafIdRef.current)
        rafIdRef.current = null
      }
      pendingEventsRef.current = []
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current)
        reconnectTimerRef.current = null
      }
      const ws = wsRef.current
      if (ws) {
        ws.onopen = null
        ws.onmessage = null
        ws.onerror = null
        ws.onclose = null
        if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) {
          ws.close()
        }
        wsRef.current = null
      }
    }
  }, [meetingId])

  // 发送控制信号（pause / resume / abort / inject / loan）
  const sendControl = useCallback(
    (signal: ControlRequest['signal'], payload: Record<string, unknown> = {}) => {
      const ws = wsRef.current
      if (!ws || ws.readyState !== WebSocket.OPEN) {
        setConnectionError('WebSocket 未连接，无法发送控制信号')
        return
      }
      ws.send(JSON.stringify({ type: 'control.signal', signal, payload }))
    },
    [],
  )

  // 发送借调三问（loan 控制信号，payload 为借调表单内容）
  const sendBorrow = useCallback(
    (payload: BorrowRequestPayload) => {
      sendControl('loan', payload as unknown as Record<string, unknown>)
    },
    [sendControl],
  )

  const approveBorrow = useCallback(
    (requestId: string) => {
      sendControl('approve_borrow', { request_id: requestId })
    },
    [sendControl],
  )

  const rejectBorrow = useCallback(
    (requestId: string, reason?: string) => {
      sendControl('reject_borrow', { request_id: requestId, reason: reason || '用户拒绝借调' })
    },
    [sendControl],
  )

  const freezeBorrow = useCallback(
    () => {
      sendControl('freeze_borrow', {})
    },
    [sendControl],
  )

  return { connected, connectionError, lastSeq, sendControl, sendBorrow, approveBorrow, rejectBorrow, freezeBorrow }
}
