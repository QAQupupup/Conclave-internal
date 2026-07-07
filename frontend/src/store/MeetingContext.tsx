// 会议状态 Context：组装 reducer + WebSocket + REST API
// 对外暴露统一的会议上下文，组件通过 useMeeting() 消费
import { createContext, useContext, useMemo, useReducer, useState, useCallback, useEffect } from 'react'
import type { ReactNode } from 'react'
import { useWebSocket } from '../hooks/useWebSocket.ts'
import {
  controlMeeting as apiControlMeeting,
  createMeeting as apiCreateMeeting,
  getMeetingDetail,
  runMeeting as apiRunMeeting,
  uploadDocument as apiUploadDocument,
} from '../lib/api.ts'
import { getMeetingIdFromPath, navigate, subscribe } from '../lib/router.ts'
import { initialStore, meetingReducer } from './meetingReducer.ts'
import type { MeetingStore } from './meetingReducer.ts'
import type {
  BorrowRequestPayload,
  ControlRequest,
  CreateMeetingResponse,
  MeetingState,
  RunMeetingResponse,
  UploadDocumentResponse,
} from '../types/events.ts'

/** Context 暴露的完整能力 */
interface MeetingContextValue {
  store: MeetingStore
  meetingId: string | null
  connected: boolean
  connectionError: string | null
  /** 切换当前会议（设为 null 退回创建页） */
  selectMeeting: (meetingId: string | null) => void
  /** 重置全部状态 */
  reset: () => void
  // REST 能力
  createMeeting: (topic: string, deliverableType?: string) => Promise<CreateMeetingResponse>
  uploadDocument: (meetingId: string, file: File) => Promise<UploadDocumentResponse>
  runMeeting: (meetingId: string) => Promise<RunMeetingResponse>
  /** 控场信号 REST（pause/resume/abort，按钮调用） */
  controlMeeting: (
    meetingId: string,
    signal: ControlRequest['signal'],
    payload?: Record<string, unknown>,
  ) => Promise<void>
  /** GET 刷新完整状态并 hydrate */
  refreshMeeting: (meetingId: string) => Promise<void>
  // WS 能力
  /** 经 WS 发送控制信号 */
  sendControl: (signal: ControlRequest['signal'], payload?: Record<string, unknown>) => void
  /** 经 WS 发送借调请求 */
  sendBorrow: (payload: BorrowRequestPayload) => void
}

const MeetingContext = createContext<MeetingContextValue | null>(null)

/** Context Provider 组件 */
export function MeetingProvider({ children }: { children: ReactNode }) {
  const [store, dispatch] = useReducer(meetingReducer, initialStore)
  // meetingId 从 URL 派生：/meeting/:id → id，其他路由 → null
  const [meetingId, setMeetingId] = useState<string | null>(getMeetingIdFromPath)

  // 监听路由变化（navigate / popstate），同步 meetingId
  useEffect(() => {
    const update = () => {
      const newId = getMeetingIdFromPath()
      setMeetingId((prev) => {
        if (prev !== newId) {
          // 会议切换时 reset store，避免旧数据闪烁
          dispatch({ type: 'reset' })
        }
        return newId
      })
    }
    const unsub = subscribe(update)
    window.addEventListener('popstate', update)
    return () => {
      unsub()
      window.removeEventListener('popstate', update)
    }
  }, [])

  // WS 连接管理（meetingId 变化时重连）
  const { connected, connectionError, sendControl, sendBorrow } = useWebSocket(meetingId, dispatch)

  const selectMeeting = useCallback((id: string | null) => {
    if (id === null) {
      navigate('/board')
    } else {
      navigate(`/meeting/${id}`)
    }
    // 路由监听器会自动同步 meetingId + dispatch reset
    // 但如果 URL 没变（同一路径），监听器不会触发，所以手动更新
    setMeetingId((prev) => {
      if (prev !== id) {
        dispatch({ type: 'reset' })
      }
      return id
    })
  }, [])

  const reset = useCallback(() => {
    navigate('/board')
    setMeetingId((prev) => {
      if (prev !== null) {
        dispatch({ type: 'reset' })
      }
      return null
    })
  }, [])

  // 创建会议：REST，成功后 hydrate 初始字段
  const createMeeting = useCallback(async (topic: string, deliverableType?: string) => {
    const res = await apiCreateMeeting(topic, deliverableType)
    dispatch({
      type: 'hydrate',
      payload: { meeting_id: res.meeting_id, topic: res.topic, stage: res.stage, status: res.status },
    })
    return res
  }, [])

  // 上传 md 文档
  const uploadDocument = useCallback(async (id: string, file: File) => {
    return apiUploadDocument(id, file)
  }, [])

  // 触发运行：同步阻塞，结束后刷新完整状态（运行期间 WS 实时推送已逐条更新）
  const runMeeting = useCallback(async (id: string) => {
    const res = await apiRunMeeting(id)
    // 运行结束后拉取完整状态，确保 messages/conflicts/artifact 一致
    await refreshMeetingImpl(id)
    return res
  }, [])

  // 控场信号 REST：pause/resume/abort（持久化 + 发布 control.signal 事件，reducer 据此更新 status）
  const controlMeeting = useCallback(
    async (id: string, signal: ControlRequest['signal'], payload: Record<string, unknown> = {}) => {
      const res = await apiControlMeeting(id, signal, payload)
      // 用后端返回的最新 stage/status 合并
      dispatch({ type: 'hydrate', payload: { stage: res.stage, status: res.status } })
    },
    [],
  )

  // GET 刷新并 hydrate（实现，供 runMeeting 复用）
  const refreshMeetingImpl = useCallback(async (id: string) => {
    const detail = await getMeetingDetail(id)
    dispatch({ type: 'hydrate', payload: detail as Partial<MeetingState> })
  }, [])

  const refreshMeeting = refreshMeetingImpl

  // meetingId 变化时拉取会议详情（包括首次挂载和路由切换）
  useEffect(() => {
    if (meetingId) {
      refreshMeetingImpl(meetingId)
    }
  }, [meetingId, refreshMeetingImpl])

  const value = useMemo<MeetingContextValue>(
    () => ({
      store,
      meetingId,
      connected,
      connectionError,
      selectMeeting,
      reset,
      createMeeting,
      uploadDocument,
      runMeeting,
      controlMeeting,
      refreshMeeting,
      sendControl,
      sendBorrow,
    }),
    [
      store,
      meetingId,
      connected,
      connectionError,
      selectMeeting,
      reset,
      createMeeting,
      uploadDocument,
      runMeeting,
      controlMeeting,
      refreshMeeting,
      sendControl,
      sendBorrow,
    ],
  )

  return <MeetingContext.Provider value={value}>{children}</MeetingContext.Provider>
}

/** 消费会议上下文的 hook */
export function useMeeting(): MeetingContextValue {
  const ctx = useContext(MeetingContext)
  if (!ctx) {
    throw new Error('useMeeting 必须在 <MeetingProvider> 内部使用')
  }
  return ctx
}
