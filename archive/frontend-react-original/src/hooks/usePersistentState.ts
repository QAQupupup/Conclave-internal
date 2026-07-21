/**
 * usePersistentState hook：useState + localStorage 持久化。
 * 设计模式：DRY（消除 App.tsx/MeetingContext 中 3 处重复的 try/catch 序列化）+ 单一职责
 *
 * @param key localStorage 键
 * @param initial 默认值（也用于序列化为字符串）
 * @returns [value, setValue] — setValue 接受新值或更新函数
 *
 * 自动序列化：boolean → '1'/'0'；string → 原样；object → JSON.stringify
 */
import { useCallback, useState } from 'react'

function readStored<T>(key: string, initial: T): T {
  try {
    const raw = localStorage.getItem(key)
    if (raw === null) return initial
    // boolean 用 '1'/'0' 编码
    if (typeof initial === 'boolean') return (raw === '1') as unknown as T
    // string 原样
    if (typeof initial === 'string') return raw as unknown as T
    // 其它走 JSON
    return JSON.parse(raw) as T
  } catch {
    return initial
  }
}

function writeStored<T>(key: string, value: T): void {
  try {
    if (typeof value === 'boolean') localStorage.setItem(key, value ? '1' : '0')
    else if (typeof value === 'string') localStorage.setItem(key, value)
    else localStorage.setItem(key, JSON.stringify(value))
  } catch {
    /* noop */
  }
}

export function usePersistentState<T>(key: string, initial: T) {
  const [value, setValue] = useState<T>(() => readStored(key, initial))

  const setAndPersist = useCallback(
    (next: T | ((prev: T) => T)) => {
      setValue(prev => {
        const resolved =
          typeof next === 'function' ? (next as (p: T) => T)(prev) : next
        writeStored(key, resolved)
        return resolved
      })
    },
    [key],
  )

  return [value, setAndPersist] as const
}
