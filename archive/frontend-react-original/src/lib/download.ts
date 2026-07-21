/**
 * 下载工具：把文本内容作为文件下载到本地。
 * 设计模式：DRY（消除 ReportViewer 等多处下载逻辑重复）+ 单一职责
 */

/** 触发浏览器下载文本文件 */
export function downloadFile(filename: string, content: string, mime = 'text/markdown'): void {
  const blob = new Blob([content], { type: mime })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}
