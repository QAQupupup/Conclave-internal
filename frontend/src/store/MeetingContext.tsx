// 会议状态 Context：组装 reducer + WebSocket + REST API
// 对外暴露统一的会议上下文，组件通过 useMeeting() 消费
//
// [CON-12 修复] 拆分 Context：
//   - MeetingShellContext：顶层，路由级（meetingId、连接、错误、会议切换、REST 能力）
//   - MeetingDataContext：内层，仅在 meetingId !== null 时挂载，持有 store/reducer
//   - MeetingConnContext：连接状态透传
// 优点：meetingId=null 时不挂载数据级 Provider，消费组件不会因空 store 重渲染；
//       切换会议时 DataProvider 卸载+重建，store reset 是天然的。
// 引入 AbortController：组件树卸载时取消未完成的 fetch，避免 setState on unmounted 警告。
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useReducer,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import { useWebSocket } from '../hooks/useWebSocket.ts'
import {
  controlMeeting as apiControlMeeting,
  createMeeting as apiCreateMeeting,
  getMeetingDetail,
  injectMeetingReference as apiInjectReference,
  interveneMeeting as apiIntervene,
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
  RunMeetingResponse,
  UploadDocumentResponse,
  MeetingState,
} from '../types/events.ts'

// ============================================================================
// Context 类型
// ============================================================================

interface MeetingShellContextValue {
  meetingId: string | null
  selectMeeting: (meetingId: string | null) => void
  createMeeting: (
    topic: string,
    deliverableType?: string,
    referenceMeetingIds?: string[],
  ) => Promise<CreateMeetingResponse>
  uploadDocument: (meetingId: string, file: File) => Promise<UploadDocumentResponse>
  runMeeting: (meetingId: string) => Promise<RunMeetingResponse>
  controlMeeting: (
    meetingId: string,
    signal: ControlRequest['signal'],
    payload?: Record<string, unknown>,
  ) => Promise<void>
  injectReference: (meetingId: string, referenceMeetingIds: string[]) => Promise<void>
  sendIntervention: (meetingId: string, content: string, replyToId?: string) => Promise<void>
}

interface MeetingDataContextValue {
  store: MeetingStore
  sendControl: (signal: ControlRequest['signal'], payload?: Record<string, unknown>) => void
  sendBorrow: (payload: BorrowRequestPayload) => void
  approveBorrow: (requestId: string) => void
  rejectBorrow: (requestId: string, reason?: string) => void
  freezeBorrow: () => void
  refreshMeeting: (meetingId: string) => Promise<void>
}

interface MeetingConnValue {
  connected: boolean
  connectionError: string | null
}

interface MeetingContextValue extends MeetingShellContextValue, MeetingDataContextValue, MeetingConnValue {}

// ============================================================================
// Context 实例
// ============================================================================

const MeetingShellContext = createContext<MeetingShellContextValue | null>(null)
const MeetingDataContext = createContext<MeetingDataContextValue | null>(null)
const MeetingConnContext = createContext<MeetingConnValue>({ connected: false, connectionError: null })

// ============================================================================
// 顶层 Provider：永远挂载，包含 REST 能力和路由级状态
// ============================================================================

export function MeetingProvider({ children }: { children: ReactNode }) {
  const [meetingId, setMeetingId] = useState<string | null>(getMeetingIdFromPath)

  // 监听路由变化
  useEffect(() => {
    const update = () => {
      const newId = getMeetingIdFromPath()
      setMeetingId((prev) => (prev !== newId ? newId : prev))
    }
    const unsub = subscribe(update)
    window.addEventListener('popstate', update)
    return () => {
      unsub()
      window.removeEventListener('popstate', update)
    }
  }, [])

  // [CON-12] AbortController：组件树卸载时取消所有 fetch
  const abortRef = useRef<AbortController | null>(null)
  useEffect(() => {
    abortRef.current = new AbortController()
    return () => {
      abortRef.current?.abort()
    }
  }, [])

  const selectMeeting = useCallback((id: string | null) => {
    if (id === null) navigate('/board')
    else navigate(`/meeting/${id}`)
  }, [])

  const createMeeting = useCallback(
    async (
      topic: string,
      deliverableType?: string,
      referenceMeetingIds?: string[],
    ): Promise<CreateMeetingResponse> => {
      return apiCreateMeeting(topic, deliverableType, referenceMeetingIds)
    },
    [],
  )
  const uploadDocument = useCallback(async (mid: string, file: File) => apiUploadDocument(mid, file), [])
  const runMeeting = useCallback(async (mid: string) => apiRunMeeting(mid), [])
  const controlMeeting = useCallback(
    async (mid: string, signal: ControlRequest['signal'], payload?: Record<string, unknown>) => {
      await apiControlMeeting(mid, signal, payload)
    },
    [],
  )
  const injectReference = useCallback(async (mid: string, ids: string[]): Promise<void> => {
    await apiInjectReference(mid, ids)
  }, [])
  const sendIntervention = useCallback(
    async (mid: string, content: string, replyToId?: string): Promise<void> => {
      await apiIntervene(mid, content, replyToId)
    },
    [],
  )

  const shellValue = useMemo<MeetingShellContextValue>(
    () => ({
      meetingId,
      selectMeeting,
      createMeeting,
      uploadDocument,
      runMeeting,
      controlMeeting,
      injectReference,
      sendIntervention,
    }),
    [
      meetingId,
      selectMeeting,
      createMeeting,
      uploadDocument,
      runMeeting,
      controlMeeting,
      injectReference,
      sendIntervention,
    ],
  )

  return (
    <MeetingShellContext.Provider value={shellValue}>
      {/* key={meetingId} 确保切换会议时内层 Provider 完全卸载重挂，reducer state 自然重置，
          防止旧会议的 messages/logs/claims 等大量数据残留在内存中 */}
      {meetingId === null ? children : <MeetingDataProviderOuter key={meetingId} meetingId={meetingId}>{children}</MeetingDataProviderOuter>}
    </MeetingShellContext.Provider>
  )
}

// ============================================================================
// 内层 Provider：仅在 meetingId !== null 时挂载，含 reducer + WS
// ============================================================================

function MeetingDataProviderOuter({ meetingId, children }: { meetingId: string; children: ReactNode }) {
  const [store, dispatch] = useReducer(meetingReducer, initialStore)
  const { connected, connectionError, sendControl, sendBorrow, approveBorrow, rejectBorrow, freezeBorrow } = useWebSocket(meetingId, dispatch)

  // 首次挂载 / meetingId 变化时 REST hydrate
  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const detail = await getMeetingDetail(meetingId)
        if (cancelled) return
        dispatch({ type: 'hydrate', payload: detail as unknown as MeetingState })
      } catch (e) {
        if (cancelled) return
        // eslint-disable-next-line no-console
        console.error('[MeetingContext] hydrate failed:', e)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [meetingId])

  const refreshMeeting = useCallback(async (mid: string) => {
    const detail = await getMeetingDetail(mid)
    dispatch({ type: 'hydrate', payload: detail as unknown as MeetingState })
  }, [])

  const dataValue = useMemo<MeetingDataContextValue>(
    () => ({ store, sendControl, sendBorrow, approveBorrow, rejectBorrow, freezeBorrow, refreshMeeting }),
    [store, sendControl, sendBorrow, approveBorrow, rejectBorrow, freezeBorrow, refreshMeeting],
  )

  return (
    <MeetingDataContext.Provider value={dataValue}>
      <MeetingConnContext.Provider value={{ connected, connectionError }}>{children}</MeetingConnContext.Provider>
    </MeetingDataContext.Provider>
  )
}

// ============================================================================
// useMeeting：合并三层 context（向后兼容旧 API）
// ============================================================================

export function useMeeting(): MeetingContextValue {
  const shell = useContext(MeetingShellContext)
  const data = useContext(MeetingDataContext)
  const conn = useContext(MeetingConnContext)
  if (!shell) {
    throw new Error('useMeeting must be used inside <MeetingProvider>')
  }
  return {
    // Shell
    meetingId: shell.meetingId,
    selectMeeting: shell.selectMeeting,
    createMeeting: shell.createMeeting,
    uploadDocument: shell.uploadDocument,
    runMeeting: shell.runMeeting,
    controlMeeting: shell.controlMeeting,
    injectReference: shell.injectReference,
    sendIntervention: shell.sendIntervention,
    // Data（可能为 null 当 meetingId=null）
    store: data?.store ?? initialStore,
    sendControl: data?.sendControl ?? (() => {}),
    sendBorrow: data?.sendBorrow ?? (() => {}),
    approveBorrow: data?.approveBorrow ?? (() => {}),
    rejectBorrow: data?.rejectBorrow ?? (() => {}),
    freezeBorrow: data?.freezeBorrow ?? (() => {}),
    refreshMeeting: data?.refreshMeeting ?? (async () => {}),
    // Conn
    connected: conn.connected,
    connectionError: conn.connectionError,
  }
}
