import { useAuthStore } from '@/stores';
import { isDemoMode, mockApi } from './mock-data';

const API_BASE = '';

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

// Check if we should use mock data for this path
function getMockResponse<T>(path: string, method: string, body?: unknown): T | null {
  if (!isDemoMode()) return null;

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

  // Agents list
  if (method === 'GET' && path.startsWith('/agent-roles') || path === '/agents') {
    return mockApi.getAgents() as unknown as T;
  }

  // Graph data
  if (method === 'GET' && path.startsWith('/graph') || path.includes('/graph')) {
    return mockApi.getGraphData() as unknown as T;
  }

  // Reports
  if (method === 'GET' && path.startsWith('/reports') || path.startsWith('/meetings') && path.includes('/report')) {
    return { reports: mockApi.getReports() } as unknown as T;
  }

  // System health
  if (method === 'GET' && path === '/health') {
    return mockApi.getSystemHealth() as unknown as T;
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

  // Notifications
  if (method === 'GET' && path.startsWith('/notifications')) {
    return { notifications: mockApi.getNotifications() } as unknown as T;
  }

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
  if (method === 'GET' && path.startsWith('/admin') || path.startsWith('/metrics')) {
    return mockApi.getAdminStats() as unknown as T;
  }

  // Tenants
  if (method === 'GET' && path.startsWith('/tenants')) {
    return { tenants: mockApi.getTenants() } as unknown as T;
  }

  // Switch tenant - just return success in demo
  if (method === 'POST' && path.includes('/tenants/switch')) {
    return { success: true } as unknown as T;
  }

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

  // Logout
  if (method === 'POST' && path === '/auth/logout') {
    return { success: true } as unknown as T;
  }

  // Default: return empty success for unhandled mutation endpoints
  if (method === 'POST' || method === 'PUT' || method === 'PATCH' || method === 'DELETE') {
    return { success: true } as unknown as T;
  }

  return null;
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  // Try mock data first in demo mode
  const method = options.method || 'GET';
  let body: unknown;
  if (options.body) {
    try { body = JSON.parse(options.body as string); } catch { /* ignore parse error, use raw body */ }
  }

  const mockResult = getMockResponse<T>(path, method, body);
  if (mockResult !== null) {
    // Add artificial delay for realism
    await new Promise((r) => setTimeout(r, 200 + Math.random() * 400));
    return mockResult;
  }

  const token = useAuthStore.getState().token;
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string>),
  };
  if (token) headers['Authorization'] = `Bearer ${token}`;

  try {
    const res = await fetch(`${API_BASE}${path}`, {
      ...options,
      headers,
      credentials: 'include',
    });

    if (res.status === 401) {
      if (!path.startsWith('/auth/login') && !path.startsWith('/auth/me')) {
        useAuthStore.getState().logout();
      } else {
        useAuthStore.setState({ token: null, user: null, isAuthenticated: false, isLoading: false });
      }
      const err = await safeParseJson(res);
      throw new ApiError(err?.detail || '认证失败，请重新登录', 401, err);
    }

    if (!res.ok) {
      const err = await safeParseJson(res);
      const message = err?.detail || err?.message || `HTTP ${res.status}`;
      throw new ApiError(message, res.status, err);
    }

    if (res.status === 204) return undefined as T;

    const text = await res.text();
    if (!text) return undefined as T;
    return JSON.parse(text);
  } catch (err) {
    // If network error in demo mode, return mock fallback
    if (isDemoMode() && err instanceof TypeError) {
      const fallback = getMockResponse<T>(path, method, body);
      if (fallback !== null) return fallback;
    }
    throw err;
  }
}

async function safeParseJson(res: Response) {
  try {
    return await res.json();
  } catch {
    return null;
  }
}

export const api = {
  get: <T>(path: string) => request<T>(path, { method: 'GET' }),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'POST', body: body ? JSON.stringify(body) : undefined }),
  put: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'PUT', body: body ? JSON.stringify(body) : undefined }),
  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'PATCH', body: body ? JSON.stringify(body) : undefined }),
  delete: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
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
    const res = await fetch(`${API_BASE}${path}`, { method: 'GET', headers, credentials: 'include' });
    if (!res.ok) throw new ApiError(`下载失败: HTTP ${res.status}`, res.status);
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
