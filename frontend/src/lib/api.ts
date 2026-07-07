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
export async function createMeeting(topic: string, deliverableType?: string): Promise<CreateMeetingResponse> {
  return request<CreateMeetingResponse>('/meetings', {
    method: 'POST',
    body: JSON.stringify({ topic, deliverable_type: deliverableType }),
  })
}

/** 取会议完整状态：GET /meetings/:id */
export async function getMeetingDetail(meetingId: string) {
  return request<Record<string, unknown>>(`/meetings/${encodeURIComponent(meetingId)}`, {
    method: 'GET',
  })
}

/** 会议列表项 */
export interface MeetingListItem {
  meeting_id: string
  topic: string
  stage: string
  status: string
  created_at?: string
  is_running?: boolean
  tags?: string[]
}

/** 列出会议（支持搜索、分页、标签过滤）
 *  GET /meetings?q=&limit=&offset=&tags=
 *  返回 { meetings, total, concurrent_limit, running_count } */
export async function listMeetings(params?: {
  q?: string
  limit?: number
  offset?: number
  tags?: string[]
}): Promise<{
  meetings: MeetingListItem[]
  total: number
  concurrent_limit: number
  running_count: number
}> {
  const qs = new URLSearchParams()
  if (params?.q) qs.set('q', params.q)
  if (params?.limit != null) qs.set('limit', String(params.limit))
  if (params?.offset != null) qs.set('offset', String(params.offset))
  if (params?.tags?.length) qs.set('tags', params.tags.join(','))
  const query = qs.toString()
  return request(`/meetings${query ? `?${query}` : ''}`, { method: 'GET' })
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

/** 删除会议：DELETE /meetings/:id?mode=soft|hard|restore
 * - soft（默认）：软删除，保留数据用于回归
 * - hard：永久删除，不可恢复
 * - restore：恢复软删除的会议
 */
export async function deleteMeeting(
  meetingId: string,
  mode: 'soft' | 'hard' | 'restore' = 'soft',
): Promise<{ meeting_id: string; deleted: boolean; mode: string }> {
  return request(`/meetings/${encodeURIComponent(meetingId)}?mode=${mode}`, {
    method: 'DELETE',
  })
}

// ---- 标签 API ----

/** 标签信息 */
export interface TagInfo {
  tag: string
  count: number
  last_used?: string
}

/** 列出所有标签：GET /meetings/tags */
export async function listTags(): Promise<{ tags: TagInfo[]; count: number }> {
  return request('/meetings/tags', { method: 'GET' })
}

/** 取会议标签：GET /meetings/:id/tags */
export async function getMeetingTags(meetingId: string): Promise<{ meeting_id: string; tags: string[] }> {
  return request(`/meetings/${encodeURIComponent(meetingId)}/tags`, { method: 'GET' })
}

/** 添加标签：POST /meetings/:id/tags body {tag} */
export async function addMeetingTag(
  meetingId: string,
  tag: string,
): Promise<{ meeting_id: string; tag: string; added: boolean }> {
  return request(`/meetings/${encodeURIComponent(meetingId)}/tags`, {
    method: 'POST',
    body: JSON.stringify({ tag }),
  })
}

/** 移除标签：DELETE /meetings/:id/tags/:tag */
export async function removeMeetingTag(
  meetingId: string,
  tag: string,
): Promise<{ meeting_id: string; tag: string; removed: boolean }> {
  return request(`/meetings/${encodeURIComponent(meetingId)}/tags/${encodeURIComponent(tag)}`, {
    method: 'DELETE',
  })
}

// ---- 批量操作 API ----

/** 批量删除会议：POST /meetings/batch-delete body {meeting_ids, mode} */
export async function batchDeleteMeetings(
  meetingIds: string[],
  mode: 'soft' | 'hard' = 'soft',
): Promise<{ deleted: string[]; failed: string[]; mode: string }> {
  return request('/meetings/batch-delete', {
    method: 'POST',
    body: JSON.stringify({ meeting_ids: meetingIds, mode }),
  })
}

// ---- Workspace API ----

/** 工作区文件项 */
export interface FileItem {
  name: string
  path: string
  type: 'file' | 'directory'
  size: number
  modified: number
}

/** 列出工作区文件：GET /workspace/files?path= */
export async function listFiles(path = ''): Promise<{
  path: string
  type: string
  items: FileItem[]
}> {
  const qs = path ? `?path=${encodeURIComponent(path)}` : ''
  return request(`/workspace/files${qs}`, { method: 'GET' })
}

/** 读取文件：GET /workspace/files/:path */
export async function readFile(filePath: string): Promise<{
  path: string
  content: string
  size: number
  language: string
}> {
  return request(`/workspace/files/${encodeURIComponent(filePath)}`, { method: 'GET' })
}

/** 写入文件：POST /workspace/files body {path, content} */
export async function writeFile(path: string, content: string): Promise<{
  path: string
  size: number
  saved: boolean
}> {
  return request('/workspace/files', {
    method: 'POST',
    body: JSON.stringify({ path, content }),
  })
}

/** 删除文件：DELETE /workspace/files/:path */
export async function deleteFile(filePath: string): Promise<{
  path: string
  deleted: boolean
}> {
  return request(`/workspace/files/${encodeURIComponent(filePath)}`, {
    method: 'DELETE',
  })
}

/** 执行命令：POST /workspace/exec body {command, cwd} */
export async function execCommand(command: string, cwd = ''): Promise<{
  command: string
  exit_code: number
  stdout: string
  stderr: string
  sandboxed: boolean
  image: string
  fallback_reason: string
  duration_hint: string
}> {
  return request('/workspace/exec', {
    method: 'POST',
    body: JSON.stringify({ command, cwd }),
  })
}

/** 运行代码：POST /workspace/run body {code, language} */
export async function runCode(code: string, language = 'python'): Promise<{
  language: string
  exit_code: number
  stdout: string
  stderr: string
  sandboxed: boolean
  image: string
  fallback_reason: string
  duration_hint: string
}> {
  return request('/workspace/run', {
    method: 'POST',
    body: JSON.stringify({ code, language }),
  })
}

/** 沙箱状态：GET /workspace/sandbox/status */
export async function sandboxStatus(): Promise<{
  mode: string
  docker_available: boolean
  image: string
  mem_limit: string
  cpu_limit: string
  active: boolean
}> {
  return request('/workspace/sandbox/status', { method: 'GET' })
}

/** 工作区信息：GET /workspace/info */
export async function workspaceInfo(): Promise<{
  root: string
  exists: boolean
  cmd_timeout: number
  code_timeout: number
  max_output: number
  python: string
  python_version: string
  sandbox: {
    mode: string
    docker_available: boolean
    image: string
    mem_limit: string
    cpu_limit: string
    active: boolean
  }
}> {
  return request('/workspace/info', { method: 'GET' })
}
