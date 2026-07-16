/**
 * 剪贴板工具：优先 Clipboard API，失败回退 execCommand。
 * 设计模式：DRY（消除 4 处复制逻辑重复）+ 适配器（统一两代 API）
 */

/** 把文本写入剪贴板，成功返回 true。 */
export async function copyToClipboard(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    // 兜底：旧 API（非 HTTPS 或老浏览器）
    try {
      const ta = document.createElement('textarea')
      ta.value = text
      ta.style.position = 'fixed'
      ta.style.opacity = '0'
      document.body.appendChild(ta)
      ta.select()
      const ok = document.execCommand('copy')
      document.body.removeChild(ta)
      return ok
    } catch {
      return false
    }
  }
}
