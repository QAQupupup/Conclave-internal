/**
 * 格式化工具：纯函数，无副作用，便于测试与复用。
 * 设计模式：单一职责（每个函数只做一件事）+ DRY（统一时间/JSON 格式化入口）
 */

/** ISO 时间字符串 → HH:MM:SS（用于消息时间戳） */
export function formatTime(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

/** ISO 时间字符串 → 本地化完整时间（用于报告） */
export function formatDateTime(ts: string): string {
  if (!ts) return ''
  try {
    return new Date(ts).toLocaleString('zh-CN')
  } catch {
    return ts
  }
}

/** 尝试把内容解析并重新格式化为 2-space 缩进 JSON。失败返回原字符串。 */
export function tryFormatJson(content: string): string {
  const trimmed = content.trim()
  if (!trimmed.startsWith('{') && !trimmed.startsWith('[')) return content
  try {
    return JSON.stringify(JSON.parse(trimmed), null, 2)
  } catch {
    return content
  }
}

/** 截断字符串到 maxLen，超出加省略号 */
export function truncate(text: string, maxLen: number): string {
  return text.length > maxLen ? text.slice(0, maxLen) + '…' : text
}
