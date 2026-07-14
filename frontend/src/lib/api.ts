// REST API 封装：对接后端（前缀无 /api，直接根路径）
// 通过 vite proxy 转发到 http://127.0.0.1:8000，前端用相对路径即可
import type {
  ControlRequest,
  ControlResponse,
  CreateMeetingResponse,
  RunMeetingResponse,
  UploadDocumentResponse,
  AgentRole,
  AgentRoleListResponse,
  GenerateRolesResponse,
} from '../types/events.ts'

/** 后端返回的错误结构（FastAPI HTTPException） */
interface ApiError {
  detail?: string
}

/** 认证 token 缓存（从后端 dev/info 端点获取或 env 注入） */
let _authToken: string | null = null

/**
 * 初始化认证 token。
 *
 * 顺序：
 * 1. localStorage 缓存（用户已在 UI 输入过）
 * 2. URL 查询参数 ?api_token=xxx（首次访问自动保存）
 * 3. 后端 /debug/auth-info 端点（开发模式自动发现）
 *
 * 安全说明：
 * 不再从 import.meta.env.VITE_API_TOKEN 读取 token。
 * Vite 会在构建时将 env 变量内联到 JS bundle 中，任何能访问前端的用户
 * 都可以在浏览器 DevTools 中提取该 token，等同于密钥泄露。
 * 生产环境应通过 URL 参数或用户手动输入传递 token。
 */
export async function initAuthToken(): Promise<string | null> {
  if (_authToken) return _authToken

  // 1) localStorage
  if (typeof localStorage !== 'undefined') {
    const cached = localStorage.getItem('conclave.api_token')
    if (cached) {
      _authToken = cached
      return cached
    }
  }

  // 2) URL query
  if (typeof window !== 'undefined') {
    const urlToken = new URLSearchParams(window.location.search).get('api_token')
    if (urlToken) {
      _authToken = urlToken
      if (typeof localStorage !== 'undefined') {
        localStorage.setItem('conclave.api_token', urlToken)
      }
      return urlToken
    }
  }

  // 3) 后端 dev info（开发模式自动发现）
  try {
    const resp = await fetch('/debug/auth-info')
    if (resp.ok) {
      const data = (await resp.json()) as { token?: string }
      if (data.token) {
        _authToken = data.token
        if (typeof localStorage !== 'undefined') {
          localStorage.setItem('conclave.api_token', data.token)
        }
        return data.token
      }
    }
  } catch {
    // 后端可能未提供该端点，忽略
  }

  return null
}

/** 手动设置 token（用户在登录 UI 输入后调用） */
export function setAuthToken(token: string): void {
  _authToken = token
  if (typeof localStorage !== 'undefined') {
    localStorage.setItem('conclave.api_token', token)
  }
}

/** 清除 token（登出或 token 失效后） */
export function clearAuthToken(): void {
  _authToken = null
  if (typeof localStorage !== 'undefined') {
    localStorage.removeItem('conclave.api_token')
  }
}

/** 注入认证头：Bearer <token> */
function buildHeaders(init: RequestInit): Headers {
  const headers = new Headers(init.headers)
  if (_authToken && !headers.has('Authorization')) {
    headers.set('Authorization', `Bearer ${_authToken}`)
  }
  return headers
}

/** 统一请求封装：自动 JSON 化、注入认证、处理错误 */
export async function request<T>(url: string, init: RequestInit = {}): Promise<T> {
  const headers = buildHeaders(init)
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
    // 401 时清掉 token 强制重新初始化
    if (res.status === 401) {
      clearAuthToken()
    }
    throw new Error(message)
  }
  // 204 等无内容
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

/** 创建会议：POST /meetings body {topic, deliverable_type, reference_meeting_ids} */
export async function createMeeting(topic: string, deliverableType?: string, referenceMeetingIds?: string[]): Promise<CreateMeetingResponse> {
  return request<CreateMeetingResponse>('/meetings', {
    method: 'POST',
    body: JSON.stringify({ topic, deliverable_type: deliverableType, reference_meeting_ids: referenceMeetingIds ?? [] }),
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
  // [CON-11 修复] 新增字段：子节点数 + 展开状态（用于递归文件树）
  child_count?: number
  expanded?: boolean
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

// ---- Agent 角色 API ----

/** 列出所有角色：GET /agent-roles */
export async function listAgentRoles(activeOnly = false): Promise<AgentRoleListResponse> {
  const qs = activeOnly ? '?active_only=true' : ''
  return request(`/agent-roles${qs}`, { method: 'GET' })
}

/** 生成角色：POST /agent-roles/generate */
export async function generateRoles(topic: string): Promise<GenerateRolesResponse> {
  return request<GenerateRolesResponse>('/agent-roles/generate', {
    method: 'POST',
    body: JSON.stringify({ topic }),
  })
}

/** 创建角色：POST /agent-roles */
export async function createAgentRole(role: Partial<AgentRole> & { id: string; display_name: string }): Promise<{ role: AgentRole }> {
  return request('/agent-roles', {
    method: 'POST',
    body: JSON.stringify(role),
  })
}

/** 更新角色：PUT /agent-roles/:id */
export async function updateAgentRole(roleId: string, role: Partial<AgentRole> & { display_name: string }): Promise<{ role: AgentRole }> {
  return request(`/agent-roles/${encodeURIComponent(roleId)}`, {
    method: 'PUT',
    body: JSON.stringify(role),
  })
}

/** 删除角色：DELETE /agent-roles/:id */
export async function deleteAgentRole(roleId: string): Promise<{ role_id: string; deleted: boolean }> {
  return request(`/agent-roles/${encodeURIComponent(roleId)}`, { method: 'DELETE' })
}

// ---- Metrics API ----

/** 运维面板指标快照 */
export interface MetricsSnapshot {
  timestamp: number
  system: {
    cpu_percent: number
    memory_mb: number
    memory_percent: number
    uptime_seconds: number
  }
  conclave: {
    active_meetings: number
    browser_contexts: number
  }
  throughput: {
    api_requests_total: number
    api_requests_per_minute: number
    avg_latency_ms: number
  }
  llm: {
    total_tokens: number
    total_llm_tokens: number
    total_cost_usd: number
    total_calls: number
    llm_calls: number
    tool_calls: number
    error_count: number
    by_node: Record<string, { calls: number; cost_usd: number; tokens: number; latency_ms: number }>
    by_tool: Record<string, { calls: number; cost_usd: number; tokens: number; latency_ms: number }>
  }
  infrastructure: {
    status: string
    components: Record<string, { status: string; latency_ms?: number; message?: string; [key: string]: unknown }>
  }
}

/** 获取运维指标快照：GET /metrics */
export async function getMetrics(): Promise<MetricsSnapshot> {
  return request<MetricsSnapshot>('/metrics', { method: 'GET' })
}

/** [v2 修复] 获取基础设施连通性详情：GET /metrics/health
 *  用于"刷新"按钮调用的轻量级端点（比 /metrics 快，无 LLM/throughput 计算）
 */
export async function getMetricsHealth(): Promise<MetricsSnapshot['infrastructure']> {
  return request<MetricsSnapshot['infrastructure']>('/metrics/health', { method: 'GET' })
}

/** 时序数据点 */
export interface MetricPoint {
  ts: number
  cpu: number
  memory_mb: number
  memory_pct: number
  tokens: number
  cost_usd: number
  requests_total: number
  requests_per_min: number
  latency_ms: number
  meetings: number
  browser_ctx: number
}

/** 获取时序指标历史：GET /metrics/history?minutes=60 */
export async function getMetricsHistory(minutes = 60): Promise<{
  resolution_seconds: number
  points: MetricPoint[]
}> {
  return request(`/metrics/history?minutes=${minutes}`, { method: 'GET' })
}

// ---- 历史会议引用 API ----

/** 会议摘要（用于历史会议引用选择器） */
export interface MeetingSummary {
  meeting_id: string
  topic: string
  clarified_topic: string
  status: string
  stage: string
  created_at: string
  key_questions: string[]
  artifact_summary: string
  flow_plan: string
  decision_record: Record<string, unknown> | null
}

/** 获取会议摘要：GET /meetings/:id/summary */
export async function getMeetingSummary(meetingId: string): Promise<MeetingSummary> {
  return request<MeetingSummary>(`/meetings/${encodeURIComponent(meetingId)}/summary`, { method: 'GET' })
}

/** 注入历史会议引用：POST /meetings/:id/reference */
export async function injectMeetingReference(
  meetingId: string,
  referenceMeetingIds: string[]
): Promise<{ meeting_id: string; injected: number; total_references: number; message: string }> {
  return request(`/meetings/${encodeURIComponent(meetingId)}/reference`, {
    method: 'POST',
    body: JSON.stringify({ reference_meeting_ids: referenceMeetingIds }),
  })
}

// ---- 用户介入对话 API ----

/** 介入对话消息 */
export interface InterventionMessage {
  id: string
  sender: 'user' | 'moderator'
  content: string
  reply_to_id?: string
  timestamp: string
  processed?: boolean
}

/** 用户介入对话请求 */
export interface InterventionRequest {
  content: string
  reply_to_id?: string
}

/** 介入对话响应 */
export interface InterventionResponse {
  meeting_id: string
  message_id: string
  intervention_messages: InterventionMessage[]
}

/** 用户介入对话：POST /meetings/:id/intervene */
export async function interveneMeeting(
  meetingId: string,
  content: string,
  replyToId?: string,
): Promise<InterventionResponse> {
  const body: InterventionRequest = { content }
  if (replyToId) body.reply_to_id = replyToId
  return request<InterventionResponse>(`/meetings/${encodeURIComponent(meetingId)}/intervene`, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

// ---- LLM 模型管理 API ----

/** LLM 厂商信息 */
export interface LLMProvider {
  id: string
  name: string
  base_url: string
  has_key: boolean
  supports_balance: boolean
  supports_custom_key: boolean
  supports_models_list: boolean
  pricing_note: string
}

/** 模型信息 */
export interface LLMModel {
  id: string
  object?: string
  created?: number
  owned_by?: string
  // 附加字段（后端补充）
  pricing?: {
    input: number
    output: number
    currency: string
    tier: string
  }
}

/** 模型分类结果 */
export interface LLMModelCategories {
  recommended?: LLMModel[]
  free?: LLMModel[]
  reasoning?: LLMModel[]
  vision?: LLMModel[]
  embedding?: LLMModel[]
  chat?: LLMModel[]
  [key: string]: LLMModel[] | undefined
}

/** 模型列表响应 */
export interface LLMModelsResponse {
  models: LLMModel[]
  categories: LLMModelCategories
  recommended: Array<{ id: string; desc: string }>
  total: number
}

/** 余额响应 */
export interface LLMBalanceResponse {
  balance: number | null
  currency: string
  provider: string
  supported: boolean
  message?: string
  raw?: Record<string, unknown>
}

/** 会议模型配置 */
export interface MeetingModelConfig {
  meeting_id: string
  provider_id: string
  model: string
  has_custom_key: boolean
  base_url: string
}

/** 列出 LLM 厂商：GET /meetings/llm/providers */
export async function listLLMProviders(): Promise<{ providers: LLMProvider[] }> {
  return request('/meetings/llm/providers', { method: 'GET' })
}

/** 查询可用模型列表：GET /meetings/llm/models?provider=&refresh=&api_key=&base_url= */
export async function listLLMModels(params?: {
  provider?: string
  refresh?: boolean
  api_key?: string
  base_url?: string
}): Promise<LLMModelsResponse> {
  const qs = new URLSearchParams()
  if (params?.provider) qs.set('provider', params.provider)
  if (params?.refresh) qs.set('refresh', 'true')
  if (params?.api_key) qs.set('api_key', params.api_key)
  if (params?.base_url) qs.set('base_url', params.base_url)
  const query = qs.toString()
  return request(`/meetings/llm/models${query ? `?${query}` : ''}`, { method: 'GET' })
}

/** 查询余额：GET /meetings/llm/balance?provider=&api_key=&base_url= */
export async function getLLMBalance(params?: {
  provider?: string
  api_key?: string
  base_url?: string
}): Promise<LLMBalanceResponse> {
  const qs = new URLSearchParams()
  if (params?.provider) qs.set('provider', params.provider)
  if (params?.api_key) qs.set('api_key', params.api_key)
  if (params?.base_url) qs.set('base_url', params.base_url)
  const query = qs.toString()
  return request(`/meetings/llm/balance${query ? `?${query}` : ''}`, { method: 'GET' })
}

/** 设置会议模型：POST /meetings/:id/model */
export async function setMeetingModel(
  meetingId: string,
  config: {
    provider_id?: string
    model?: string
    api_key?: string
    base_url?: string
  },
): Promise<MeetingModelConfig> {
  return request(`/meetings/${encodeURIComponent(meetingId)}/model`, {
    method: 'POST',
    body: JSON.stringify(config),
  })
}

/** 获取会议模型配置：GET /meetings/:id/model */
export async function getMeetingModel(meetingId: string): Promise<MeetingModelConfig> {
  return request(`/meetings/${encodeURIComponent(meetingId)}/model`, { method: 'GET' })
}

// ---- CAPTCHA 值守 API ----

/** CAPTCHA 值守状态 */
export interface CaptchaStatus {
  guard_mode: boolean
  vnc_ready: boolean
  pending_count: number
  vnc_url: string | null
  vnc_port: number
  cdp_port: number
}

/** CAPTCHA 会话信息 */
export interface CaptchaSessionInfo {
  session_id: string
  url: string
  captcha_types: string[]
  page_title: string
  screenshot?: string
  created_at: number
  meeting_id: string | null
  status: string
  resolved_at: number | null
  vnc_url: string | null
  vnc_port: number
  timeout: number
  elapsed: number
}

/** captcha.pending 事件 payload */
export interface CaptchaPendingPayload {
  session_id: string
  url: string
  captcha_types: string[]
  page_title: string
  has_screenshot: boolean
  vnc_ready: boolean
  vnc_url: string | null
  timeout: number
}

/** captcha.resolved / captcha.timeout 事件 payload */
export interface CaptchaSessionEventPayload {
  session_id: string
}

/** 获取 CAPTCHA 值守状态：GET /api/captcha/status */
export async function getCaptchaStatus(): Promise<CaptchaStatus> {
  return request<CaptchaStatus>('/api/captcha/status', { method: 'GET' })
}

/** 切换值守模式：POST /api/captcha/guard-mode */
export async function setGuardMode(enabled: boolean): Promise<{ ok: boolean; guard_mode: boolean; vnc_ready: boolean }> {
  return request('/api/captcha/guard-mode', {
    method: 'POST',
    body: JSON.stringify({ enabled }),
  })
}

/** 获取验证码会话截图（返回 data:image/png;base64,... 格式）：GET /api/captcha/sessions/:id/screenshot */
export async function getCaptchaScreenshot(sessionId: string): Promise<{ session_id: string; screenshot: string }> {
  return request(`/api/captcha/sessions/${encodeURIComponent(sessionId)}/screenshot`, { method: 'GET' })
}

/** 通知后端验证码已解决：POST /api/captcha/resolve */
export async function resolveCaptcha(sessionId: string): Promise<{ ok: boolean; session_id: string }> {
  return request('/api/captcha/resolve', {
    method: 'POST',
    body: JSON.stringify({ session_id: sessionId }),
  })
}
