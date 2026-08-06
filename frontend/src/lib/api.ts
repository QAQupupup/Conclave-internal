import { useAuthStore } from '@/stores';
import { isDemoMode, mockApi } from './mock-data';

const API_BASE = '';

// ---------------------------------------------------------------------------
// CSRF
// ---------------------------------------------------------------------------

/** 从 document.cookie 中读取 csrf_token（由后端 HttpOnly 响应中的 Set-Cookie 写入） */
function getCsrfToken(): string | null {
  if (typeof document === 'undefined') return null;
  const match = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : null;
}

// ---------------------------------------------------------------------------
// Token 自动刷新 —— 并发请求队列
// ---------------------------------------------------------------------------

let isRefreshing = false;
let refreshPromise: Promise<string> | null = null;

/** 等待刷新中的请求：(resolve, reject) 对 */
type PendingRequest = {
  resolve: (token: string) => void;
  reject: (err: unknown) => void;
};
const pendingRequests: PendingRequest[] = [];

/**
 * 调用 /auth/refresh 用 refresh_token（HttpOnly cookie）换取新的 access_token。
 * - 并发场景下只发一次刷新请求，其余请求排队等待结果
 * - 刷新成功：更新 store token，重新 fetchUser，resolve 所有排队请求
 * - 刷新失败：reject 所有排队请求，触发 logout
 */
async function refreshAccessToken(): Promise<string> {
  if (isRefreshing && refreshPromise) {
    // 已有刷新在进行中，排队等待
    return new Promise<string>((resolve, reject) => {
      pendingRequests.push({ resolve, reject });
    });
  }

  isRefreshing = true;
  refreshPromise = (async (): Promise<string> => {
    try {
      // 刷新请求不走 request() 本身，避免 401 死循环；直接 fetch
      const headers: Record<string, string> = { 'Content-Type': 'application/json' };
      // POST /auth/refresh 需要 CSRF token（Cookie 认证路径）
      const csrfToken = getCsrfToken();
      if (csrfToken) headers['X-CSRF-Token'] = csrfToken;
      const res = await fetch(`${API_BASE}/auth/refresh`, {
        method: 'POST',
        headers,
        credentials: 'include',
      });

      if (!res.ok) {
        throw new ApiError('刷新认证失败，请重新登录', res.status);
      }

      const data = (await res.json()) as { access_token?: string };
      const newToken = data.access_token;
      if (!newToken) {
        throw new ApiError('刷新响应缺少 access_token', 500);
      }

      // 更新 store 中的 token
      useAuthStore.setState({ token: newToken });

      // 用新 token 拉取最新用户信息（失败不影响 token 刷新本身）
      try {
        await useAuthStore.getState().fetchUser();
      } catch {
        /* fetchUser 内部已处理失败场景 */
      }

      // resolve 所有排队请求
      for (const req of pendingRequests) {
        req.resolve(newToken);
      }
      pendingRequests.length = 0;

      return newToken;
    } catch (err) {
      // 刷新失败：reject 所有排队请求，然后登出
      for (const req of pendingRequests) {
        req.reject(err);
      }
      pendingRequests.length = 0;

      // 触发登出（硬跳转）
      useAuthStore.getState().logout();
      throw err;
    } finally {
      isRefreshing = false;
      refreshPromise = null;
    }
  })();

  return refreshPromise;
}

// ---------------------------------------------------------------------------
// ApiError
// ---------------------------------------------------------------------------

export class ApiError extends Error {
  status: number;
  detail?: unknown;
  constructor(message: string, status: number, detail?: unknown) {
    super(message);
    this.status = status;
    this.detail = detail;
    this.name = 'ApiError';
  }
}

// ---------------------------------------------------------------------------
// Demo mode mock responses
// ---------------------------------------------------------------------------

// Check if we should use mock data for this path
function getMockResponse<T>(path: string, method: string, body?: unknown): T | null {
  if (!isDemoMode()) return null;

  // -----------------------------------------------------------------------
  // Auth
  // -----------------------------------------------------------------------

  // Auth/me - return demo user
  if (method === 'GET' && path === '/auth/me') {
    return {
      user: {
        id: 'demo-user-001',
        username: 'admin',
        display_name: '演示管理员',
        email: 'admin@conclave.demo',
        role: 'admin',
        tenant_id: 'tenant-default',
        tenants: [
          { id: 'tenant-default', name: '默认组织', role: 'owner' },
          { id: 'tenant-research', name: '研究团队', role: 'admin' },
        ],
      },
    } as unknown as T;
  }

  // Auth/refresh - return new demo token
  if (method === 'POST' && path === '/auth/refresh') {
    return { access_token: 'demo-token-' + Date.now(), token_type: 'bearer' } as unknown as T;
  }

  // Logout
  if (method === 'POST' && path === '/auth/logout') {
    return { success: true } as unknown as T;
  }

  // Switch tenant
  if (method === 'POST' && path.includes('/tenants/switch')) {
    return { success: true, access_token: 'demo-token-' + Date.now() } as unknown as T;
  }

  // -----------------------------------------------------------------------
  // Meetings
  // -----------------------------------------------------------------------

  // Meetings list
  if (method === 'GET' && path.startsWith('/meetings') && !path.includes('/messages') && !path.includes('/control')) {
    const match = path.match(/\/meetings\?.*page_size=(\d+)/);
    const pageSize = match ? parseInt(match[1]) : 20;
    const statusMatch = path.match(/status=(\w+)/);
    const status = statusMatch ? statusMatch[1] : undefined;
    return mockApi.getMeetings({ pageSize, status }) as unknown as T;
  }

  // Single meeting
  if (method === 'GET' && /^\/meetings\/[^/]+$/.test(path)) {
    const id = path.split('/').pop()!;
    return mockApi.getMeeting(id) as unknown as T;
  }

  // Meeting messages
  if (method === 'GET' && path.includes('/messages')) {
    const id = path.split('/meetings/')[1]?.split('/')[0];
    if (id) return mockApi.getMeetingMessages(id) as unknown as T;
  }

  // Meeting summary
  if (method === 'GET' && path.includes('/summary')) {
    const id = path.split('/meetings/')[1]?.split('/')[0];
    const meeting = mockApi.getMeeting(id);
    return { summary: meeting?.summary || '讨论已完成，以下是要点总结...' } as unknown as T;
  }

  // Meeting report layout
  if (method === 'GET' && path.includes('/report-layout')) {
    const id = path.split('/meetings/')[1]?.split('/')[0];
    const meeting = mockApi.getMeeting(id);
    const reports = mockApi.getReports();
    const report = reports.find((r) => r.meeting_id === id) || reports[0];
    return {
      title: meeting?.title || '讨论报告',
      sections: report?.sections?.length ? report.sections : [
        { type: 'heading', level: 1, content: meeting?.title || '讨论报告' },
        { type: 'paragraph', content: meeting?.summary || '本次讨论已完成，各Agent充分交换了意见。' },
        { type: 'heading', level: 2, content: '核心观点' },
        { type: 'list', items: ['观点一：...', '观点二：...', '观点三：...'] },
      ],
    } as unknown as T;
  }

  // Meeting attachments
  if (method === 'GET' && path.includes('/attachments')) {
    const meetingId = path.match(/\/meetings\/([^/]+)\/attachments/)?.[1] || '';
    return { attachments: mockApi.getAttachments(meetingId) } as unknown as T;
  }

  // Metric history
  if (method === 'GET' && path.includes('/metrics/history')) {
    return mockApi.getMetricHistory() as unknown as T;
  }

  // Create meeting
  if (method === 'POST' && path === '/meetings' || (method === 'POST' && path.startsWith('/meetings?'))) {
    return mockApi.createMeeting(body as { topic: string }) as unknown as T;
  }

  // Delete meeting
  if (method === 'DELETE' && /^\/meetings\/[^/]+$/.test(path)) {
    const id = path.split('/').pop()!;
    return mockApi.deleteMeeting(id) as unknown as T;
  }

  // Control meeting
  if (method === 'POST' && path.includes('/control')) {
    const id = path.split('/meetings/')[1]?.split('/')[0];
    const payload = body as { signal?: string; payload?: Record<string, unknown> };
    return mockApi.controlMeeting(id, payload?.signal || '', payload?.payload) as unknown as T;
  }

  // -----------------------------------------------------------------------
  // Agents / Graph / Reports / Health
  // -----------------------------------------------------------------------

  // Agents list
  if (method === 'GET' && (path.startsWith('/agent-roles') || path === '/agents')) {
    return mockApi.getAgents() as unknown as T;
  }

  // Graph data
  if (method === 'GET' && (path.startsWith('/graph') || path.includes('/graph'))) {
    return mockApi.getGraphData() as unknown as T;
  }

  // Reports
  if (method === 'GET' && (path.startsWith('/reports') || (path.startsWith('/meetings') && path.includes('/report')))) {
    return { reports: mockApi.getReports() } as unknown as T;
  }

  // System health
  if (method === 'GET' && path === '/health') {
    return mockApi.getSystemHealth() as unknown as T;
  }

  // -----------------------------------------------------------------------
  // Docker hosts
  // -----------------------------------------------------------------------

  // Docker hosts - container list (GET /docker-hosts/:id/containers)
  if (method === 'GET' && /^\/docker-hosts\/[^/]+\/containers$/.test(path)) {
    const hostId = path.split('/')[2];
    const hosts = mockApi.getDockerHosts();
    const host = hosts.find((h: any) => h.id === hostId) || hosts[0];
    const running = (host as any)?.containers?.running ?? 3;
    const containers = [
      { id: 'c-backend', name: 'conclave-backend', image: 'conclave/backend:latest', status: 'running', state: 'running', created: '2 days ago', ports: '0.0.0.0:8000->8000/tcp', cpu: '2.3%', memory: '312MiB' },
      { id: 'c-frontend', name: 'conclave-frontend', image: 'conclave/frontend:latest', status: 'running', state: 'running', created: '2 days ago', ports: '0.0.0.0:3000->80/tcp', cpu: '0.8%', memory: '48MiB' },
      { id: 'c-postgres', name: 'conclave-postgres', image: 'postgres:16-alpine', status: 'running', state: 'running', created: '2 days ago', ports: '5432/tcp', cpu: '1.2%', memory: '186MiB' },
      { id: 'c-redis', name: 'conclave-redis', image: 'redis:7-alpine', status: 'running', state: 'running', created: '2 days ago', ports: '6379/tcp', cpu: '0.3%', memory: '12MiB' },
      { id: 'c-qdrant', name: 'conclave-qdrant', image: 'qdrant/qdrant:latest', status: 'running', state: 'running', created: '2 days ago', ports: '6333/tcp', cpu: '0.5%', memory: '64MiB' },
    ];
    // Add stopped containers if host has them
    if ((host as any)?.containers?.stopped > 0) {
      containers.push({ id: 'c-old-worker', name: 'conclave-worker-old', image: 'conclave/worker:v1', status: 'exited (0) 3 hours ago', state: 'exited', created: '5 days ago', ports: '', cpu: '0%', memory: '0B' });
    }
    // Trim to match running count + stopped
    return { containers: containers.slice(0, running + ((host as any)?.containers?.stopped ?? 0)) } as unknown as T;
  }

  // Docker hosts - create (POST /docker-hosts)
  if (method === 'POST' && path === '/docker-hosts') {
    const payload = body as { name?: string; host?: string };
    return {
      id: 'host-' + Date.now(),
      name: payload?.name || '新 Docker 主机',
      host: payload?.host || 'tcp://',
      status: 'connecting',
      is_default: false,
      os: 'unknown',
      arch: 'unknown',
      cpus: 0,
      memory: '0GB',
      docker_version: '',
      containers: { running: 0, paused: 0, stopped: 0 },
      images_count: 0,
      disk_usage: { total: '0GB', used: '0GB', available: '0GB' },
    } as unknown as T;
  }

  // Docker hosts - delete (DELETE /docker-hosts/:id)
  if (method === 'DELETE' && /^\/docker-hosts\/[^/]+$/.test(path)) {
    return { success: true } as unknown as T;
  }

  // Docker hosts - container action (POST)
  if (method === 'POST' && path.startsWith('/docker-hosts') && path.includes('/containers') && path.includes('/action')) {
    return { ok: true, action: (body as { action: string })?.action } as unknown as T;
  }

  // Docker hosts - GET endpoints
  if (method === 'GET' && path.startsWith('/docker-hosts')) {
    // System overview endpoint
    if (path.includes('/overview')) {
      const health = mockApi.getSystemHealth() as any;
      const healthComponents = health?.components || health || {};
      // Transform health data to match SystemOverview components format
      const typeMap: Record<string, string> = {
        postgres: 'database', redis: 'cache', qdrant: 'vector_db',
        docker: 'runtime', sandbox: 'runtime', llm: 'application',
      };
      const components: Record<string, { status: string; type: string }> = {};
      for (const [key, val] of Object.entries(healthComponents)) {
        const v = val as Record<string, unknown>;
        components[key] = {
          status: (v?.status as string) || 'healthy',
          type: typeMap[key] || 'application',
        };
      }
      // Add backend/frontend if not present
      if (!components.backend) components.backend = { status: 'healthy', type: 'application' };
      if (!components.frontend) components.frontend = { status: 'healthy', type: 'application' };
      if (!components.gitea) components.gitea = { status: 'healthy', type: 'git' };
      return {
        hosts: mockApi.getDockerHosts(),
        components,
        timestamp: new Date().toISOString(),
      } as unknown as T;
    }
    // Commands reference endpoint
    if (path.includes('/commands-reference')) {
      return {
        commands: [
          {
            category: '启动/停止',
            commands: [
              { label: '启动所有服务', cmd: 'docker compose up -d', description: '后台启动所有 compose 服务' },
              { label: '停止所有服务', cmd: 'docker compose down', description: '停止并移除所有容器（保留数据卷）' },
              { label: '重启后端', cmd: 'docker compose restart backend', description: '仅重启后端容器' },
              { label: '重新构建并启动', cmd: 'docker compose up -d --build', description: '重新构建镜像后启动' },
            ],
          },
          {
            category: '日志查看',
            commands: [
              { label: '查看后端日志', cmd: 'docker compose logs -f backend', description: '实时跟踪后端日志' },
              { label: '查看前端日志', cmd: 'docker compose logs -f frontend', description: '实时跟踪前端日志' },
              { label: '查看所有日志', cmd: 'docker compose logs -f', description: '实时跟踪所有服务日志' },
              { label: '最近 100 行', cmd: 'docker compose logs --tail=100 backend', description: '查看后端最近 100 行日志' },
            ],
          },
          {
            category: '健康检查',
            commands: [
              { label: '服务状态', cmd: 'docker compose ps', description: '查看所有服务运行状态' },
              { label: '健康详情', cmd: 'curl -s http://localhost:8000/health | python -m json.tool', description: '查看详细健康检查 JSON' },
              { label: '系统指标', cmd: 'curl -s http://localhost:8000/metrics | python -m json.tool', description: '查看系统运行指标' },
            ],
          },
          {
            category: '数据管理',
            commands: [
              { label: '查看数据卷', cmd: 'docker volume ls | grep conclave', description: '列出所有 Conclave 数据卷' },
              { label: '备份数据库', cmd: 'docker compose exec postgres pg_dump -U conclave conclave > backup.sql', description: '导出 PostgreSQL 数据库' },
              { label: '恢复数据库', cmd: 'cat backup.sql | docker compose exec -T postgres psql -U conclave conclave', description: '从 SQL 文件恢复数据库' },
              { label: '清理数据（危险）', cmd: 'docker compose down -v', description: '停止并删除所有数据卷（不可恢复！）' },
            ],
          },
          {
            category: '调试',
            commands: [
              { label: '进入后端容器', cmd: 'docker compose exec backend bash', description: '在后端容器内打开 Shell' },
              { label: '进入数据库', cmd: 'docker compose exec postgres psql -U conclave', description: '打开 psql 交互式终端' },
              { label: '查看容器资源', cmd: 'docker stats --no-stream', description: '查看所有容器的 CPU/内存使用' },
              { label: '检查网络', cmd: 'docker network inspect conclave-dev_conclave-internal', description: '查看内部网络详情' },
            ],
          },
        ],
      } as unknown as T;
    }
    // Default docker hosts list
    return { hosts: mockApi.getDockerHosts() } as unknown as T;
  }

  // -----------------------------------------------------------------------
  // Notifications
  // -----------------------------------------------------------------------

  if (method === 'GET' && path.startsWith('/notifications')) {
    return { notifications: mockApi.getNotifications() } as unknown as T;
  }

  // -----------------------------------------------------------------------
  // Admin
  // -----------------------------------------------------------------------

  // Admin sub-routes (must be before the catch-all /admin)
  if (method === 'GET' && path.startsWith('/admin/users')) {
    return { users: mockApi.getMockUsers() } as unknown as T;
  }

  if (method === 'GET' && path.startsWith('/admin/tenants')) {
    return { tenants: mockApi.getMockTenants() } as unknown as T;
  }

  if (method === 'GET' && path.startsWith('/admin/config')) {
    return mockApi.getMockSystemConfig() as unknown as T;
  }

  // Admin stats
  if (method === 'GET' && (path.startsWith('/admin') || path.startsWith('/metrics'))) {
    return mockApi.getAdminStats() as unknown as T;
  }

  // -----------------------------------------------------------------------
  // Tenants
  // -----------------------------------------------------------------------

  if (method === 'GET' && (path.startsWith('/tenants') || path.startsWith('/api/tenants'))) {
    return { tenants: mockApi.getTenants() } as unknown as T;
  }

  // -----------------------------------------------------------------------
  // Workspace (basic mock for demo)
  // -----------------------------------------------------------------------

  if (method === 'GET' && path.startsWith('/workspaces')) {
    return {
      workspaces: [
        { id: 'ws-default', name: '默认工作区', description: '演示用默认工作区', created_at: new Date().toISOString() },
      ],
    } as unknown as T;
  }

  if (method === 'POST' && path === '/workspaces') {
    const payload = body as { name?: string };
    return {
      id: 'ws-' + Date.now(),
      name: payload?.name || '新工作区',
      description: '',
      created_at: new Date().toISOString(),
    } as unknown as T;
  }

  if (method === 'DELETE' && /^\/workspaces\/[^/]+$/.test(path)) {
    return { success: true } as unknown as T;
  }

  // -----------------------------------------------------------------------
  // Catch-all:
  // GET → null (let it fall through to real fetch, which will 404 in demo)
  // POST/PUT/PATCH/DELETE → throw ApiError (no more fake success for unhandled mutations)
  // -----------------------------------------------------------------------
  if (method === 'POST' || method === 'PUT' || method === 'PATCH' || method === 'DELETE') {
    throw new ApiError(`演示模式：未实现的接口 ${method} ${path}`, 501);
  }

  return null;
}

// ---------------------------------------------------------------------------
// Core request function with CSRF + Bearer token + auto-refresh
// ---------------------------------------------------------------------------

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const method = (options.method || 'GET').toUpperCase();
  let body: unknown;
  if (options.body) {
    try { body = JSON.parse(options.body as string); } catch { /* ignore parse error, use raw body */ }
  }

  // Try mock data first in demo mode
  const mockResult = getMockResponse<T>(path, method, body);
  if (mockResult !== null) {
    // Add artificial delay for realism
    await new Promise((r) => setTimeout(r, 200 + Math.random() * 400));
    return mockResult;
  }

  // Inner function that performs the actual fetch with current auth headers
  const makeRequest = async (overrideToken?: string): Promise<Response> => {
    const token = overrideToken ?? useAuthStore.getState().token;
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      ...(options.headers as Record<string, string>),
    };

    // Bearer token
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }

    // CSRF token on non-GET/HEAD/OPTIONS requests
    if (method !== 'GET' && method !== 'HEAD' && method !== 'OPTIONS') {
      const csrf = getCsrfToken();
      if (csrf) {
        headers['X-CSRF-Token'] = csrf;
      }
    }

    return fetch(`${API_BASE}${path}`, {
      ...options,
      method,
      headers,
      credentials: 'include',
    });
  };

  // Auth paths that must NOT trigger token refresh (would cause infinite loop / wrong behavior)
  const isAuthRequest =
    path.startsWith('/auth/login') ||
    path.startsWith('/auth/refresh') ||
    path.startsWith('/auth/logout');

  try {
    let res = await makeRequest();

    // Handle 401 with auto-refresh
    if (res.status === 401 && !isAuthRequest) {
      try {
        const newToken = await refreshAccessToken();
        // Retry once with the new token
        res = await makeRequest(newToken);
      } catch {
        // refreshAccessToken already triggered logout; return hanging promise to avoid flash
        return new Promise<T>(() => {});
      }
    }

    // After potential refresh retry, handle remaining errors
    if (res.status === 401) {
      // Auth request 401 (login failed, etc.) — or retry also 401
      if (isAuthRequest) {
        useAuthStore.setState({ token: null, user: null, isAuthenticated: false, isLoading: false });
      } else {
        // Refresh + retry still 401 → force logout
        useAuthStore.getState().logout();
        return new Promise<T>(() => {});
      }
      const err = await safeParseJson(res);
      throw new ApiError(extractErrorMessage(err, 401) || '认证失败，请重新登录', 401, err);
    }

    if (!res.ok) {
      const err = await safeParseJson(res);
      const message = extractErrorMessage(err, res.status);
      throw new ApiError(message, res.status, err);
    }

    if (res.status === 204) return undefined as T;

    const text = await res.text();
    if (!text) return undefined as T;
    // Detect HTML response (nginx fallback or backend error page)
    if (text.startsWith('<!DOCTYPE') || text.startsWith('<html') || text.startsWith('<HTML')) {
      throw new ApiError('服务暂时不可用，请稍后重试', res.status, {});
    }
    return JSON.parse(text);
  } catch (err) {
    // If network error in demo mode, return mock fallback
    if (isDemoMode() && err instanceof TypeError) {
      const fallback = getMockResponse<T>(path, method, body);
      if (fallback !== null) return fallback;
    }
    // ApiError already has correct status/message, rethrow directly
    throw err;
  }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

async function safeParseJson(res: Response) {
  try {
    return await res.json();
  } catch {
    return null;
  }
}

/** HTTP 状态码 → 用户友好消息映射 */
const HTTP_STATUS_MESSAGES: Record<number, string> = {
  400: '请求参数有误，请检查输入',
  401: '登录已过期，请重新登录',
  403: '您没有权限执行此操作',
  404: '请求的资源不存在',
  409: '数据冲突，该资源可能已被修改',
  413: '文件过大，请压缩后重试',
  422: '输入数据有误，请检查后重试',
  429: '操作过于频繁，请稍后再试',
  500: '服务器内部错误，请稍后重试',
  502: '服务暂时不可用，请稍后重试',
  503: '服务正在维护，请稍后重试',
  504: '服务响应超时，请稍后重试',
};

/** 判断是否为应该直接展示给用户的业务错误消息 */
function isUserFacingMessage(msg: string): boolean {
  // 包含 Python 堆栈、SQL 错误、文件路径等技术特征的消息不直接展示
  const technicalPatterns = [
    /Traceback \(most recent call last\)/i,
    /File "[^"]+", line \d+/i,
    /\b(SyntaxError|TypeError|ValueError|KeyError|AttributeError|IndexError|NameError)\b/,
    /\b(OperationalError|IntegrityError|ProgrammingError|DatabaseError)\b/,
    /\b(EOFError|ConnectionError|TimeoutError)\b/,
    /psycopg2|sqlalchemy|asyncio|aiohttp|uvicorn/i,
    /^HTTP \d+$/,
    /<html|<!DOCTYPE/i,
  ];
  return !technicalPatterns.some((p) => p.test(msg)) && msg.length <= 200;
}

/** 从错误响应体中提取用户可见的错误消息 */
function extractErrorMessage(err: unknown, status: number): string {
  // 先尝试从响应体中提取消息
  let rawMessage = '';
  if (err && typeof err === 'object') {
    const e = err as Record<string, unknown>;
    // 后端自定义错误格式: {"error": {"code": ..., "message": "..."}}
    if (e.error && typeof e.error === 'object') {
      const errObj = e.error as Record<string, unknown>;
      if (typeof errObj.message === 'string' && errObj.message) rawMessage = errObj.message;
    }
    // FastAPI 标准格式: {"detail": "..."}
    if (!rawMessage && typeof e.detail === 'string' && e.detail) rawMessage = e.detail;
    // 通用格式: {"message": "..."}
    if (!rawMessage && typeof e.message === 'string' && e.message) rawMessage = e.message;
  }

  // 如果提取到的消息是用户友好的业务消息，直接展示
  if (rawMessage && isUserFacingMessage(rawMessage)) {
    return rawMessage;
  }

  // 否则返回 HTTP 状态码对应的友好消息
  return HTTP_STATUS_MESSAGES[status] || `操作失败（${status}），请稍后重试`;
}

/** 构建 query string */
function buildQueryString(params?: Record<string, string | boolean | number>): string {
  if (!params || Object.keys(params).length === 0) return '';
  const search = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    search.append(k, String(v));
  }
  return `?${search.toString()}`;
}

// ---------------------------------------------------------------------------
// Public API client
// ---------------------------------------------------------------------------

export const api = {
  get: <T>(path: string, params?: Record<string, string | boolean | number>) =>
    request<T>(`${path}${buildQueryString(params)}`, { method: 'GET' }),
  post: <T>(path: string, body?: unknown, params?: Record<string, string | boolean | number>) =>
    request<T>(`${path}${buildQueryString(params)}`, {
      method: 'POST',
      body: body ? JSON.stringify(body) : undefined,
    }),
  put: <T>(path: string, body?: unknown, params?: Record<string, string | boolean | number>) =>
    request<T>(`${path}${buildQueryString(params)}`, {
      method: 'PUT',
      body: body ? JSON.stringify(body) : undefined,
    }),
  patch: <T>(path: string, body?: unknown, params?: Record<string, string | boolean | number>) =>
    request<T>(`${path}${buildQueryString(params)}`, {
      method: 'PATCH',
      body: body ? JSON.stringify(body) : undefined,
    }),
  delete: <T>(path: string, params?: Record<string, string | boolean | number>) =>
    request<T>(`${path}${buildQueryString(params)}`, { method: 'DELETE' }),
  /** Authenticated file download - triggers browser download */
  download: async (path: string, filename?: string) => {
    if (isDemoMode()) {
      // In demo mode, show a toast instead
      const { toast } = await import('@/hooks/use-toast');
      toast({ title: '演示模式', description: '下载功能在演示模式下不可用' });
      return;
    }
    const token = useAuthStore.getState().token;
    const headers: Record<string, string> = {};
    if (token) headers['Authorization'] = `Bearer ${token}`;
    // GET 请求不携带 CSRF
    const res = await fetch(`${API_BASE}${path}`, { method: 'GET', headers, credentials: 'include' });
    if (!res.ok) throw new ApiError(HTTP_STATUS_MESSAGES[res.status] || '下载失败，请稍后重试', res.status);
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename || path.split('/').pop() || 'download';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  },
};
