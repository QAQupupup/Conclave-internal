// 轻量客户端路由：基于 History API，无第三方依赖
// 路由：/ → 封面页，/board → 任务看板，/dashboard → 运维面板，/meeting/:id → 会议视图
// 所有 navigate 调用通过订阅机制通知监听者，popstate 也触发通知

type Listener = () => void

const listeners = new Set<Listener>()

function notify(): void {
  listeners.forEach((l) => l())
}

/** 编程式导航：pushState + 通知所有订阅者 */
export function navigate(to: string, replace?: boolean): void {
  const currentUrl = window.location.pathname + window.location.search
  if (to === currentUrl) return
  if (replace) {
    window.history.replaceState({}, '', to)
  } else {
    window.history.pushState({}, '', to)
  }
  notify()
}

/** 订阅路由变化，返回取消订阅函数 */
export function subscribe(listener: Listener): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

/** 取当前 path */
export function getPath(): string {
  return window.location.pathname
}

/** 判断当前是否在会议路由，返回 meetingId 或 null */
export function getMeetingIdFromPath(): string | null {
  const match = window.location.pathname.match(/^\/meeting\/(.+)$/)
  return match ? decodeURIComponent(match[1]) : null
}

/** 判断当前是否在封面页 */
export function isLandingPath(): boolean {
  return window.location.pathname === '/'
}

/** 判断当前是否在看板页 */
export function isBoardPath(): boolean {
  return window.location.pathname === '/board'
}

/** 判断当前是否在运维面板 */
export function isDashboardPath(): boolean {
  return window.location.pathname === '/dashboard'
}

/** 判断当前是否在模型管理页 */
export function isModelsPath(): boolean {
  return window.location.pathname === '/models'
}

/** 获取URL query参数 */
export function getSearchParams(): URLSearchParams {
  return new URLSearchParams(window.location.search)
}

/** 带query参数导航 */
export function navigateWithQuery(to: string, params?: Record<string, string>): void {
  let url = to
  if (params && Object.keys(params).length > 0) {
    const search = new URLSearchParams(params).toString()
    url = `${to}?${search}`
  }
  navigate(url)
}
