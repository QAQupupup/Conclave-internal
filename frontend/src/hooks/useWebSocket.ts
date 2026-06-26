// WebSocket 钩子：连接会议 WS、接收回放与实时事件、分发到 reducer、发送控制信号
// 协议：
//   连接 → 收到 {type:'snapshot', payload} → 历史事件 DomainEvent → {type:'replay.done', events}
//   之后实时推送 DomainEvent（agent.spoke / stage.changed / evidence.attached / artifact.generated / control.signal / control.ack / error）
import { useEffect, useRef, useState, useCallback } from 'react'
import type { Dispatch } from 'react'
import type { MeetingAction } from '../store/meetingReducer.ts'
import type {
  BorrowRequestPayload,
  ControlRequest,
  DomainEvent,
  MeetingState,
} from '../types/events.ts'

interface UseWebSocketResult {
  /** 是否已连接 */
  connected: boolean
  /** 连接错误信息（便于 UI 提示） */
  connectionError: string | null
  /** 向后端发送控制信号（经 WS 转发给 Orchestrator） */
  sendControl: (signal: ControlRequest['signal'], payload?: Record<string, unknown>) => void
  /** 发送借调请求（loan 控制信号，payload 为借调三问） */
  sendBorrow: (payload: BorrowRequestPayload) => void
}

/**
 * 根据当前页面地址推导 WS 地址，利用 vite proxy 转发到后端，避免 CORS
 * 形如 ws://<host>/ws/meetings/<meeting_id>
 */
function buildWsUrl(meetingId: string): string {
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${window.location.host}/ws/meetings/${meetingId}`
}

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
  const wsRef = useRef<WebSocket | null>(null)
  // dispatch 引用稳定（来自 useReducer），但用 ref 规避闭包陈旧问题
  const dispatchRef = useRef(dispatch)
  dispatchRef.current = dispatch

  useEffect(() => {
    if (!meetingId) {
      setConnected(false)
      return
    }
    let closed = false
    const url = buildWsUrl(meetingId)
    const ws = new WebSocket(url)
    wsRef.current = ws

    ws.onopen = () => {
      if (closed) return
      setConnected(true)
      setConnectionError(null)
    }

    ws.onmessage = (ev: MessageEvent) => {
      if (closed) return
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
        case 'snapshot':
          dispatchRef.current({
            type: 'snapshot',
            payload: frame.payload as MeetingState,
          })
          break
        case 'replay.done':
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
        default:
          // 其余视为 DomainEvent（type 即事件类型，如 agent.spoke / stage.changed 等）
          dispatchRef.current({ type: 'event', event: frame as unknown as DomainEvent })
      }
    }

    ws.onerror = () => {
      if (closed) return
      setConnectionError('WebSocket 连接异常，请确认后端 127.0.0.1:8000 已启动')
    }

    ws.onclose = () => {
      if (closed) return
      setConnected(false)
    }

    return () => {
      closed = true
      ws.onopen = null
      ws.onmessage = null
      ws.onerror = null
      ws.onclose = null
      if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) {
        ws.close()
      }
      wsRef.current = null
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

  return { connected, connectionError, sendControl, sendBorrow }
}
