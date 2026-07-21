/**
 * 格式化工具：纯函数，无副作用，便于测试与复用。
 * 设计模式：单一职责（每个函数只做一件事）+ DRY（统一时间/JSON 格式化入口）
 */

const TZ_STORAGE_KEY = 'conclave_user_timezone'

/** 获取用户配置的时区（默认浏览器时区，回退到 Asia/Shanghai） */
export function getUserTimezone(): string {
  if (typeof window === 'undefined') return 'Asia/Shanghai'
  return localStorage.getItem(TZ_STORAGE_KEY)
    || Intl.DateTimeFormat().resolvedOptions().timeZone
    || 'Asia/Shanghai'
}

/** ISO 时间字符串 → HH:MM:SS（按用户配置的时区） */
export function formatTime(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const tz = getUserTimezone()
  const formatter = new Intl.DateTimeFormat('zh-CN', {
    timeZone: tz,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  })
  // Intl.DateTimeFormat 输出格式为 "HH:MM:SS"，直接取最后部分
  const parts = formatter.formatToParts(d)
  const h = parts.find(p => p.type === 'hour')?.value ?? '00'
  const m = parts.find(p => p.type === 'minute')?.value ?? '00'
  const s = parts.find(p => p.type === 'second')?.value ?? '00'
  return `${h}:${m}:${s}`
}

/** ISO 时间字符串 → 本地化完整时间（按用户配置的时区） */
export function formatDateTime(ts: string): string {
  if (!ts) return ''
  try {
    const tz = getUserTimezone()
    return new Date(ts).toLocaleString('zh-CN', { timeZone: tz })
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
