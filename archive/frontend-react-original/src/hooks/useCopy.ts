/**
 * useCopy hook：封装"复制 → 已复制提示 → 恢复"完整流程。
 * 设计模式：DRY + 单一职责（组件不再关心 clipboard 细节、toast 计时）
 *
 * 用法：
 *   const { copied, copy } = useCopy()
 *   <button onClick={() => copy('hello')}>{copied ? '已复制' : '复制'}</button>
 *
 * @param tipMs 已复制提示的持续时间，默认 2000ms
 */
import { useCallback, useRef, useState } from 'react'
import { copyToClipboard } from '../lib/clipboard.ts'

export function useCopy(tipMs = 2000) {
  const [copied, setCopied] = useState(false)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const copy = useCallback(
    async (text: string) => {
      const ok = await copyToClipboard(text)
      if (ok) {
        setCopied(true)
        if (timerRef.current) clearTimeout(timerRef.current)
        timerRef.current = setTimeout(() => setCopied(false), tipMs)
      }
      return ok
    },
    [tipMs],
  )

  return { copied, copy }
}
