// 日志 localStorage 持久化 hook
// 按会议 ID 分 key 存储，防抖批量写入，容量保护
import { useCallback, useEffect, useRef } from 'react'
import type { LogEntry } from '../types/events.ts'

const LOGS_PREFIX = 'conclave-logs-'
const LOGS_INDEX_KEY = 'conclave-logs-index'
const MAX_LOGS_PER_MEETING = 1000
const MAX_MEETINGS_WITH_LOGS = 15
const FLUSH_DEBOUNCE_MS = 500

function safeParseJSON<T>(str: string | null, fallback: T): T {
  if (!str) return fallback
  try {
    return JSON.parse(str) as T
  } catch {
    return fallback
  }
}

/** 读取 localStorage 中指定会议的日志 */
export function getStoredLogs(meetingId: string): LogEntry[] {
  if (!meetingId) return []
  const key = LOGS_PREFIX + meetingId
  return safeParseJSON<LogEntry[]>(localStorage.getItem(key), [])
}

/** 获取所有有日志存储的会议 ID 列表（按最近访问排序） */
export function getStoredLogMeetingIds(): string[] {
  return safeParseJSON<string[]>(localStorage.getItem(LOGS_INDEX_KEY), [])
}

/** 更新日志索引：把 meetingId 移到最前（最近使用） */
function updateIndex(meetingId: string): void {
  const ids = getStoredLogMeetingIds().filter((id) => id !== meetingId)
  ids.unshift(meetingId)
  // 裁剪到最大数量
  const trimmed = ids.slice(0, MAX_MEETINGS_WITH_LOGS)
  localStorage.setItem(LOGS_INDEX_KEY, JSON.stringify(trimmed))

  // 清理被裁剪掉的会议日志
  ids.slice(MAX_MEETINGS_WITH_LOGS).forEach((oldId) => {
    try {
      localStorage.removeItem(LOGS_PREFIX + oldId)
    } catch {
      // ignore
    }
  })
}

/** 写入日志到 localStorage（带容量保护） */
function writeLogs(meetingId: string, logs: LogEntry[]): void {
  if (!meetingId) return
  const key = LOGS_PREFIX + meetingId
  try {
    // 裁剪到最大条数
    const trimmed = logs.slice(-MAX_LOGS_PER_MEETING)
    localStorage.setItem(key, JSON.stringify(trimmed))
    updateIndex(meetingId)
  } catch (e) {
    // QuotaExceededError：裁剪一半后重试
    if (e instanceof DOMException && e.name === 'QuotaExceededError') {
      try {
        const half = logs.slice(-Math.floor(MAX_LOGS_PER_MEETING / 2))
        localStorage.setItem(key, JSON.stringify(half))
      } catch {
        // 仍然失败则放弃
        console.warn('[useMeetingLogs] localStorage quota exceeded, cannot persist logs')
      }
    }
  }
}

/** 清除指定会议的日志 */
export function clearLogs(meetingId: string): void {
  if (!meetingId) return
  try {
    localStorage.removeItem(LOGS_PREFIX + meetingId)
    const ids = getStoredLogMeetingIds().filter((id) => id !== meetingId)
    localStorage.setItem(LOGS_INDEX_KEY, JSON.stringify(ids))
  } catch {
    // ignore
  }
}

/**
 * 会议日志持久化 hook
 * 使用：const { hydrateLogs, persistLogs, flushLogs } = useMeetingLogs(meetingId)
 */
export function useMeetingLogs(meetingId: string | null) {
  const flushTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const pendingLogsRef = useRef<LogEntry[] | null>(null)

  // 防抖写入
  const scheduleFlush = useCallback((logs: LogEntry[]) => {
    pendingLogsRef.current = logs
    if (flushTimerRef.current) {
      clearTimeout(flushTimerRef.current)
    }
    flushTimerRef.current = setTimeout(() => {
      if (meetingId && pendingLogsRef.current) {
        writeLogs(meetingId, pendingLogsRef.current)
        pendingLogsRef.current = null
      }
      flushTimerRef.current = null
    }, FLUSH_DEBOUNCE_MS)
  }, [meetingId])

  // 立即写入（组件卸载时调用）
  const flushLogs = useCallback(() => {
    if (flushTimerRef.current) {
      clearTimeout(flushTimerRef.current)
      flushTimerRef.current = null
    }
    if (meetingId && pendingLogsRef.current) {
      writeLogs(meetingId, pendingLogsRef.current)
      pendingLogsRef.current = null
    }
  }, [meetingId])

  // 持久化日志（供外部调用：日志变化时触发）
  const persistLogs = useCallback((logs: LogEntry[]) => {
    if (!meetingId) return
    scheduleFlush(logs)
  }, [meetingId, scheduleFlush])

  // 读取历史日志（供外部调用：挂载时 hydrate）
  const hydrateLogs = useCallback((): LogEntry[] => {
    if (!meetingId) return []
    return getStoredLogs(meetingId)
  }, [meetingId])

  // 卸载时 flush
  useEffect(() => {
    return () => {
      flushLogs()
    }
  }, [flushLogs])

  return { hydrateLogs, persistLogs, flushLogs }
}

// 导出常量供 reducer 使用
export const LOG_CONSTANTS = {
  MAX_LOGS_PER_MEETING,
  MAX_MEETINGS_WITH_LOGS,
} as const
