// REST API 封装：对接后端（前缀无 /api，直接根路径）
// 通过 vite proxy 转发到 http://127.0.0.1:8000，前端用相对路径即可
import type {
  ControlRequest,
  ControlResponse,
  CreateMeetingResponse,
  RunMeetingResponse,
  UploadDocumentResponse,
} from '../types/events.ts'

/** 后端返回的错误结构（FastAPI HTTPException） */
interface ApiError {
  detail?: string
}

/** 统一请求封装：自动 JSON 化、解析错误 */
async function request<T>(url: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  let body = init.body
  // 非 FormData 时默认 JSON
  if (body && !(body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  const res = await fetch(url, { ...init, headers, body })
  if (!res.ok) {
    let message = `HTTP ${res.status}`
    try {
      const err = (await res.json()) as ApiError
      message = err.detail ?? message
    } catch {
      // 忽略解析失败
    }
    throw new Error(message)
  }
  // 204 等无内容
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

/** 创建会议：POST /meetings body {topic} */
export async function createMeeting(topic: string): Promise<CreateMeetingResponse> {
  return request<CreateMeetingResponse>('/meetings', {
    method: 'POST',
    body: JSON.stringify({ topic }),
  })
}

/** 取会议完整状态：GET /meetings/:id */
export async function getMeetingDetail(meetingId: string) {
  return request<Record<string, unknown>>(`/meetings/${encodeURIComponent(meetingId)}`, {
    method: 'GET',
  })
}

/** 触发会议运行（同步阻塞到六阶段完成）：POST /meetings/:id/run */
export async function runMeeting(meetingId: string): Promise<RunMeetingResponse> {
  return request<RunMeetingResponse>(`/meetings/${encodeURIComponent(meetingId)}/run`, {
    method: 'POST',
  })
}

/** 控场信号：POST /meetings/:id/control body {signal, payload} */
export async function controlMeeting(
  meetingId: string,
  signal: ControlRequest['signal'],
  payload: Record<string, unknown> = {},
): Promise<ControlResponse> {
  return request<ControlResponse>(`/meetings/${encodeURIComponent(meetingId)}/control`, {
    method: 'POST',
    body: JSON.stringify({ signal, payload }),
  })
}

/** 上传 Markdown 文档：POST /meetings/:id/documents multipart field=file */
export async function uploadDocument(
  meetingId: string,
  file: File,
): Promise<UploadDocumentResponse> {
  const form = new FormData()
  form.append('file', file)
  return request<UploadDocumentResponse>(`/meetings/${encodeURIComponent(meetingId)}/documents`, {
    method: 'POST',
    body: form,
    // 不要手动设置 Content-Type，浏览器会自动带 boundary
  })
}

/** 健康检查：GET /health */
export async function healthCheck(): Promise<{ status: string }> {
  return request<{ status: string }>('/health', { method: 'GET' })
}
