import { useAuthStore } from '@/stores/auth-slice';
import type {
  Artifact,
  ArtifactListResponse,
  ArtifactLineageResponse,
  CreateIssueRequest,
  CreateProjectRequest,
  Issue,
  IssueListResponse,
  MergeExecuteResponse,
  MergePreviewResponse,
  Project,
  ProjectDetail,
  ProjectListResponse,
  UpdateIssueRequest,
  UpdateProjectRequest,
} from '@/types';
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

// ---- Projects / Issues 内存态 mock（ADR-017 Phase 2，仅演示模式使用） ----

interface DemoProject {
  id: string;
  slug: string;
  name: string;
  repo_url: string | null;
  default_branch: string;
  description: string | null;
  created_by: string;
  created_at: string;
  updated_at: string;
}

interface DemoIssue {
  id: string;
  project_id: string;
  title: string;
  body: string | null;
  source: string;
  source_meeting_id: string | null;
  status: string;
  priority: number;
  assigned_meeting_id: string | null;
  resolution_artifact_id: string | null;
  created_by: string;
  created_at: string;
  updated_at: string;
}

const demoProjects: DemoProject[] = [
  {
    id: 'demo-proj-conclave',
    slug: 'conclave',
    name: 'Conclave 多智能体平台',
    repo_url: 'https://github.com/example/conclave',
    default_branch: 'main',
    description: 'Git 驱动的多智能体协作决策平台',
    created_by: 'admin',
    created_at: '2026-08-20T09:00:00Z',
    updated_at: '2026-09-01T10:30:00Z',
  },
  {
    id: 'demo-proj-docs',
    slug: 'docs-site',
    name: '文档站重构',
    repo_url: null,
    default_branch: 'main',
    description: '纯文档型项目（无绑定仓库）',
    created_by: 'admin',
    created_at: '2026-08-28T14:00:00Z',
    updated_at: '2026-08-28T14:00:00Z',
  },
];

const demoIssues: DemoIssue[] = [
  {
    id: 'demo-issue-1',
    project_id: 'demo-proj-conclave',
    title: '产物 push 端点缺少重试机制',
    body: '网络抖动时 push 失败无自动重试，建议增加指数退避。',
    source: 'user',
    source_meeting_id: null,
    status: 'open',
    priority: 70,
    assigned_meeting_id: null,
    resolution_artifact_id: null,
    created_by: 'admin',
    created_at: '2026-09-02T08:00:00Z',
    updated_at: '2026-09-02T08:00:00Z',
  },
  {
    id: 'demo-issue-2',
    project_id: 'demo-proj-conclave',
    title: '测试沙箱执行超时阈值评估',
    body: null,
    source: 'meeting',
    source_meeting_id: 'demo-meeting-9',
    status: 'in_progress',
    priority: 50,
    assigned_meeting_id: 'demo-meeting-12',
    // 会议闭环凭证已挂、待合入 main（D11：合入式闭环，合入成功后才置 resolved）
    resolution_artifact_id: 'demo-artifact-88',
    created_by: 'admin',
    created_at: '2026-09-03T11:20:00Z',
    updated_at: '2026-09-04T09:00:00Z',
  },
  {
    id: 'demo-issue-3',
    project_id: 'demo-proj-docs',
    title: 'API 参考文档补齐议题池端点',
    body: null,
    source: 'user',
    source_meeting_id: null,
    status: 'resolved',
    priority: 40,
    assigned_meeting_id: 'demo-meeting-8',
    resolution_artifact_id: 'demo-artifact-77',
    created_by: 'admin',
    created_at: '2026-08-30T16:00:00Z',
    updated_at: '2026-09-01T10:30:00Z',
  },
];

// 与后端 issue_service.ALLOWED_TRANSITIONS 对齐（演示模式保持行为一致）
const DEMO_ALLOWED_TRANSITIONS: Record<string, string[]> = {
  open: ['scheduled', 'in_progress', 'wontfix'],
  scheduled: ['in_progress', 'open', 'wontfix'],
  in_progress: ['resolved', 'open', 'wontfix', 'conflict'],
  // 合入冲突交回用户处置（D11）：回池 / 重新绑会 / 重试合入成功闭环 / 放弃
  conflict: ['open', 'in_progress', 'resolved', 'wontfix'],
  resolved: [],
  wontfix: [],
};

// 允许发起合入的议题状态（镜像后端 merge_service.MERGEABLE_STATUSES）
const DEMO_MERGEABLE_STATUSES = ['in_progress', 'conflict'];

let demoIdSeq = 0;
function nextDemoId(prefix: string): string {
  demoIdSeq += 1;
  return `${prefix}-demo-${Date.now()}-${demoIdSeq}`;
}

function demoNow(): string {
  return new Date().toISOString();
}

/** Projects / Issues 演示模式路由分发（未覆盖的变更操作 → 501） */
function getProjectIssueMock<T>(path: string, method: string, body?: unknown): T | null {
  const cleanPath = path.split('?')[0];
  const query = new URLSearchParams(path.includes('?') ? path.split('?')[1] : '');

  // GET /api/projects —— 分页列表（附议题总数）
  if (method === 'GET' && cleanPath === '/api/projects') {
    const limit = Number(query.get('limit') ?? 50);
    const offset = Number(query.get('offset') ?? 0);
    const sorted = [...demoProjects].sort((a, b) => b.created_at.localeCompare(a.created_at));
    const items = sorted.slice(offset, offset + limit).map((p) => ({
      ...p,
      issue_total: demoIssues.filter((i) => i.project_id === p.id).length,
    }));
    return { items, total: sorted.length } as unknown as T;
  }

  // POST /api/projects —— 创建项目
  if (method === 'POST' && cleanPath === '/api/projects') {
    const payload = body as Partial<DemoProject>;
    if (demoProjects.some((p) => p.slug === payload.slug)) {
      throw new ApiError(`项目标识已存在: ${payload.slug}`, 409);
    }
    const project: DemoProject = {
      id: nextDemoId('proj'),
      slug: payload.slug ?? '',
      name: payload.name ?? '',
      repo_url: payload.repo_url ?? null,
      default_branch: payload.default_branch || 'main',
      description: payload.description ?? null,
      created_by: 'admin',
      created_at: demoNow(),
      updated_at: demoNow(),
    };
    demoProjects.push(project);
    return project as unknown as T;
  }

  // GET /api/projects/:id/issues —— 项目议题列表
  const projectIssuesMatch = cleanPath.match(/^\/api\/projects\/([^/]+)\/issues$/);
  if (projectIssuesMatch && method === 'GET') {
    const projectId = projectIssuesMatch[1];
    if (!demoProjects.some((p) => p.id === projectId)) throw new ApiError('项目不存在', 404);
    const statusFilter = query.get('status');
    const limit = Number(query.get('limit') ?? 50);
    const offset = Number(query.get('offset') ?? 0);
    const sorted = demoIssues
      .filter((i) => i.project_id === projectId && (!statusFilter || i.status === statusFilter))
      .sort((a, b) => b.created_at.localeCompare(a.created_at));
    return { items: sorted.slice(offset, offset + limit), total: sorted.length } as unknown as T;
  }

  // POST /api/projects/:id/issues —— 议题入池
  if (projectIssuesMatch && method === 'POST') {
    const projectId = projectIssuesMatch[1];
    if (!demoProjects.some((p) => p.id === projectId)) throw new ApiError('项目不存在', 404);
    const payload = body as Partial<DemoIssue>;
    if (payload.source === 'meeting' && !payload.source_meeting_id) {
      throw new ApiError('会议来源议题必须挂 source_meeting_id', 400);
    }
    const issue: DemoIssue = {
      id: nextDemoId('issue'),
      project_id: projectId,
      title: payload.title ?? '',
      body: payload.body ?? null,
      source: payload.source || 'user',
      source_meeting_id: payload.source_meeting_id ?? null,
      status: 'open',
      priority: payload.priority ?? 50,
      assigned_meeting_id: null,
      resolution_artifact_id: null,
      created_by: 'admin',
      created_at: demoNow(),
      updated_at: demoNow(),
    };
    demoIssues.push(issue);
    return issue as unknown as T;
  }

  // GET /api/projects/:id —— 项目详情（含议题状态分组统计）
  const projectDetailMatch = cleanPath.match(/^\/api\/projects\/([^/]+)$/);
  if (projectDetailMatch && method === 'GET') {
    const project = demoProjects.find((p) => p.id === projectDetailMatch[1]);
    if (!project) throw new ApiError('项目不存在', 404);
    const issues = demoIssues.filter((i) => i.project_id === project.id);
    const stats: Record<string, number> = { total: issues.length };
    for (const i of issues) stats[i.status] = (stats[i.status] ?? 0) + 1;
    return { ...project, issue_stats: stats } as unknown as T;
  }

  // PATCH /api/projects/:id —— 更新项目
  if (projectDetailMatch && method === 'PATCH') {
    const project = demoProjects.find((p) => p.id === projectDetailMatch[1]);
    if (!project) throw new ApiError('项目不存在', 404);
    const payload = body as Partial<DemoProject>;
    Object.assign(project, payload, { updated_at: demoNow() });
    return project as unknown as T;
  }

  // DELETE /api/projects/:id —— 删除项目（议题级联删）
  if (projectDetailMatch && method === 'DELETE') {
    const idx = demoProjects.findIndex((p) => p.id === projectDetailMatch[1]);
    if (idx < 0) throw new ApiError('项目不存在', 404);
    const [removed] = demoProjects.splice(idx, 1);
    for (let i = demoIssues.length - 1; i >= 0; i--) {
      if (demoIssues[i].project_id === removed.id) demoIssues.splice(i, 1);
    }
    return { deleted: removed.id } as unknown as T;
  }

  // GET /api/issues/:id
  const issueMatch = cleanPath.match(/^\/api\/issues\/([^/]+)$/);
  if (issueMatch && method === 'GET') {
    const issue = demoIssues.find((i) => i.id === issueMatch[1]);
    if (!issue) throw new ApiError('议题不存在', 404);
    return issue as unknown as T;
  }

  // PATCH /api/issues/:id —— 字段更新 / 状态机流转
  if (issueMatch && method === 'PATCH') {
    const issue = demoIssues.find((i) => i.id === issueMatch[1]);
    if (!issue) throw new ApiError('议题不存在', 404);
    const payload = body as Partial<DemoIssue>;
    const { status: target, resolution_artifact_id, ...fields } = payload;
    Object.assign(issue, fields);
    if (target !== undefined) {
      if (!(DEMO_ALLOWED_TRANSITIONS[issue.status] ?? []).includes(target)) {
        throw new ApiError(`非法流转: ${issue.status} → ${target}`, 409);
      }
      if (target === 'resolved' && !(resolution_artifact_id || issue.resolution_artifact_id)) {
        throw new ApiError('resolved 必须挂 resolution_artifact_id（闭环凭证）', 409);
      }
      issue.status = target;
      if (resolution_artifact_id) issue.resolution_artifact_id = resolution_artifact_id;
    } else if (resolution_artifact_id !== undefined) {
      issue.resolution_artifact_id = resolution_artifact_id;
    }
    issue.updated_at = demoNow();
    return issue as unknown as T;
  }

  // DELETE /api/issues/:id
  if (issueMatch && method === 'DELETE') {
    const idx = demoIssues.findIndex((i) => i.id === issueMatch[1]);
    if (idx < 0) throw new ApiError('议题不存在', 404);
    const [removed] = demoIssues.splice(idx, 1);
    return { deleted: removed.id } as unknown as T;
  }

  // POST /api/issues/:id/merge —— 合入 main（D11 两阶段确认，演示模拟）
  const issueMergeMatch = cleanPath.match(/^\/api\/issues\/([^/]+)\/merge$/);
  if (issueMergeMatch && method === 'POST') {
    const issue = demoIssues.find((i) => i.id === issueMergeMatch[1]);
    if (!issue) throw new ApiError('议题不存在', 404);
    const project = demoProjects.find((p) => p.id === issue.project_id);
    const payload = body as { confirm?: boolean };
    // 上下文校验（镜像后端 validate_merge_context 的拒绝路径）
    if (!DEMO_MERGEABLE_STATUSES.includes(issue.status)) {
      throw new ApiError(`议题当前状态 ${issue.status} 不可合入（仅 ${DEMO_MERGEABLE_STATUSES.join('/')}）`, 409);
    }
    if (!issue.assigned_meeting_id) {
      throw new ApiError('议题未绑定执行会议，无法定位合入源', 409);
    }
    if (!project?.repo_url) {
      throw new ApiError('项目未绑定仓库，无需合入', 409);
    }
    const branch = project.default_branch || 'main';
    const changedFiles = ['M\tREADME.md', 'A\tdocs/issue-notes.md'];
    if (!payload.confirm) {
      // 预览：干跑合并，不落状态
      return {
        mode: 'preview',
        issue_id: issue.id,
        project_id: project.id,
        meeting_id: issue.assigned_meeting_id,
        branch,
        source_committed: true,
        mergeable: true,
        changed_files: changedFiles,
        conflicts: [],
      } as unknown as T;
    }
    // 执行：闭环凭证红线（镜像后端 execute_merge）
    if (!issue.resolution_artifact_id) {
      throw new ApiError('缺少闭环凭证（resolution_artifact_id），拒绝合入', 409);
    }
    issue.status = 'resolved';
    issue.updated_at = demoNow();
    return {
      mode: 'execute',
      merged: true,
      issue_id: issue.id,
      project_id: project.id,
      meeting_id: issue.assigned_meeting_id,
      branch,
      merge_commit_sha: `demo${Date.now().toString(16).slice(-8)}`,
      pushed_to: `origin/${branch}`,
      changed_files: changedFiles,
      issue_status: 'resolved',
    } as unknown as T;
  }

  return null;
}

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
    // 兼容两种分页参数：page_size（旧）与 limit+offset（与后端一致），
    // 否则监控概览的 limit=200 会被忽略而只取默认 20 条。
    const pageSizeMatch = path.match(/[?&]page_size=(\d+)/);
    const limitMatch = path.match(/[?&]limit=(\d+)/);
    const limit = limitMatch ? parseInt(limitMatch[1], 10) : undefined;
    const pageSize = pageSizeMatch ? parseInt(pageSizeMatch[1], 10) : limit ?? 20;
    const offsetMatch = path.match(/[?&]offset=(\d+)/);
    const offset = offsetMatch ? parseInt(offsetMatch[1], 10) : 0;
    const page = pageSize > 0 && offset >= pageSize ? Math.floor(offset / pageSize) + 1 : 1;
    const statusMatch = path.match(/status=(\w+)/);
    const status = statusMatch ? statusMatch[1] : undefined;
    return mockApi.getMeetings({ page, pageSize, status }) as unknown as T;
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
    const host = hosts.find((h) => h.id === hostId) || hosts[0];
    const running = host?.containers?.running ?? 3;
    const containers = [
      { id: 'c-backend', name: 'conclave-backend', image: 'conclave/backend:latest', status: 'running', state: 'running', created: '2 days ago', ports: '0.0.0.0:8000->8000/tcp', cpu: '2.3%', memory: '312MiB' },
      { id: 'c-frontend', name: 'conclave-frontend', image: 'conclave/frontend:latest', status: 'running', state: 'running', created: '2 days ago', ports: '0.0.0.0:3000->80/tcp', cpu: '0.8%', memory: '48MiB' },
      { id: 'c-postgres', name: 'conclave-postgres', image: 'postgres:16-alpine', status: 'running', state: 'running', created: '2 days ago', ports: '5432/tcp', cpu: '1.2%', memory: '186MiB' },
      { id: 'c-redis', name: 'conclave-redis', image: 'redis:7-alpine', status: 'running', state: 'running', created: '2 days ago', ports: '6379/tcp', cpu: '0.3%', memory: '12MiB' },
      { id: 'c-qdrant', name: 'conclave-qdrant', image: 'qdrant/qdrant:latest', status: 'running', state: 'running', created: '2 days ago', ports: '6333/tcp', cpu: '0.5%', memory: '64MiB' },
    ];
    // Add stopped containers if host has them
    if ((host?.containers?.stopped ?? 0) > 0) {
      containers.push({ id: 'c-old-worker', name: 'conclave-worker-old', image: 'conclave/worker:v1', status: 'exited (0) 3 hours ago', state: 'exited', created: '5 days ago', ports: '', cpu: '0%', memory: '0B' });
    }
    // Trim to match running count + stopped
    return { containers: containers.slice(0, running + (host?.containers?.stopped ?? 0)) } as unknown as T;
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
      const health = mockApi.getSystemHealth();
      const healthComponents = (health.components as Record<string, unknown> | undefined) || health;
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
  // Projects / Issues（ADR-017 Phase 2，演示模式内存态 mock）
  // -----------------------------------------------------------------------

  if (path.startsWith('/api/projects') || path.startsWith('/api/issues')) {
    return getProjectIssueMock<T>(path, method, body);
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
  /** Authenticated multipart file upload with progress (XMLHttpRequest, fetch 不支持上传进度) */
  upload: <T = unknown>(
    path: string,
    file: File,
    options: { fieldName?: string; onProgress?: (percent: number) => void } = {},
  ): Promise<T> => {
    const { fieldName = 'file', onProgress } = options;
    return new Promise<T>((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open('POST', `${API_BASE}${path}`);
      xhr.withCredentials = true;

      const token = useAuthStore.getState().token;
      if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`);
      const csrf = getCsrfToken();
      if (csrf) xhr.setRequestHeader('X-CSRF-Token', csrf);

      if (onProgress) {
        xhr.upload.onprogress = (e) => {
          if (e.lengthComputable) onProgress(Math.round((e.loaded / e.total) * 100));
        };
      }

      xhr.onload = () => {
        let body: unknown = null;
        try {
          body = xhr.responseText ? JSON.parse(xhr.responseText) : null;
        } catch {
          /* 非 JSON 响应 */
        }
        if (xhr.status >= 200 && xhr.status < 300) {
          resolve(body as T);
        } else {
          reject(new ApiError(extractErrorMessage(body, xhr.status), xhr.status, body));
        }
      };
      xhr.onerror = () => reject(new ApiError('网络错误，上传失败', 0));
      xhr.ontimeout = () => reject(new ApiError('上传超时，请稍后重试', 0));

      const form = new FormData();
      form.append(fieldName, file, file.name);
      xhr.send(form);
    });
  },
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
  /** 带鉴权拉取图片并返回 object URL（用于操作回放截图等需 Bearer 头的 <img> 资源） */
  imageBlobUrl: async (path: string): Promise<string> => {
    if (isDemoMode()) return '';
    const token = useAuthStore.getState().token;
    const headers: Record<string, string> = {};
    if (token) headers['Authorization'] = `Bearer ${token}`;
    const res = await fetch(`${API_BASE}${path}`, { method: 'GET', headers, credentials: 'include' });
    if (!res.ok) {
      throw new ApiError(HTTP_STATUS_MESSAGES[res.status] || '加载截图失败', res.status);
    }
    const blob = await res.blob();
    return URL.createObjectURL(blob);
  },
  /** 临近话题推荐：创建会议时按议题文本检索相似历史会议 */
  relatedMeetings: (topic: string, limit = 5) =>
    request<{ meetings: Array<{ meeting_id: string; topic: string; status: string; deliverable_type?: string; score?: number }> }>(
      `/meetings/related${buildQueryString({ topic, limit })}`,
      { method: 'GET' },
    ),
  /** 某会议的相似历史会议（基于议题向量，排除自身） */
  meetingRelated: (id: string, limit = 5) =>
    request<{ meetings: Array<{ meeting_id: string; topic: string; status: string; deliverable_type?: string; score?: number }> }>(
      `/meetings/${id}/related${buildQueryString({ limit })}`,
      { method: 'GET' },
    ),
  /** 知识图谱：物化语义边（supports/contradicts）+ 节点 */
  graphOverview: (meetingId?: string) =>
    request<{ nodes: Array<Record<string, unknown>>; edges: Array<Record<string, unknown>> }>(
      `/graph/overview${buildQueryString(meetingId ? { meeting_id: meetingId } : {})}`,
      { method: 'GET' },
    ),
  /** 会议事件历史（审计/回放）。from_seq=0 返回全部，>0 返回增量（seq > from_seq） */
  getMeetingEvents: (meetingId: string, fromSeq = 0) =>
    request<{ meeting_id: string; from_seq: number; last_seq: number; count: number; events: Array<RawMeetingEvent> }>(
      `/meetings/${meetingId}/events${buildQueryString({ from_seq: fromSeq })}`,
      { method: 'GET' },
    ),
  /** 产物（ADR-017 Phase 1）：会议产出的一等公民实体 */
  artifacts: {
    /** 分页查询产物（可按会议/类型过滤，最新在上） */
    list: (params?: { meeting_id?: string; type?: string; limit?: number; offset?: number }) => {
      const query: Record<string, string | number> = {};
      if (params?.meeting_id) query.meeting_id = params.meeting_id;
      if (params?.type) query.type = params.type;
      if (params?.limit !== undefined) query.limit = params.limit;
      if (params?.offset !== undefined) query.offset = params.offset;
      return request<ArtifactListResponse>(`/artifacts${buildQueryString(query)}`, { method: 'GET' });
    },
    /** 单条产物详情 */
    get: (id: string) => request<Artifact>(`/artifacts/${id}`, { method: 'GET' }),
    /** 产物上游血缘图（深度上限防环） */
    lineage: (id: string) => request<ArtifactLineageResponse>(`/artifacts/${id}/lineage`, { method: 'GET' }),
  },
  /** 项目（ADR-017 Phase 2）：议题池的命名空间容器 */
  projects: {
    /** 分页查询项目（租户过滤，最新在上，附议题总数） */
    list: (params?: { limit?: number; offset?: number }) => {
      const query: Record<string, number> = {};
      if (params?.limit !== undefined) query.limit = params.limit;
      if (params?.offset !== undefined) query.offset = params.offset;
      return request<ProjectListResponse>(`/api/projects${buildQueryString(query)}`, { method: 'GET' });
    },
    /** 项目详情（含议题状态分组统计） */
    get: (id: string) => request<ProjectDetail>(`/api/projects/${id}`, { method: 'GET' }),
    /** 创建项目（slug 租户内唯一，冲突 → 409） */
    create: (data: CreateProjectRequest) =>
      request<Project>('/api/projects', { method: 'POST', body: JSON.stringify(data) }),
    /** 更新项目（白名单字段，只更新传入项） */
    update: (id: string, data: UpdateProjectRequest) =>
      request<Project>(`/api/projects/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
    /** 删除项目（议题级联删；会议/产物关联置 NULL） */
    delete: (id: string) => request<{ deleted: string }>(`/api/projects/${id}`, { method: 'DELETE' }),
    /** 项目议题列表（可按状态过滤，最新在上） */
    listIssues: (projectId: string, params?: { status?: string; limit?: number; offset?: number }) => {
      const query: Record<string, string | number> = {};
      if (params?.status) query.status = params.status;
      if (params?.limit !== undefined) query.limit = params.limit;
      if (params?.offset !== undefined) query.offset = params.offset;
      return request<IssueListResponse>(`/api/projects/${projectId}/issues${buildQueryString(query)}`, { method: 'GET' });
    },
    /** 议题入池（source=user 手动；source=meeting 须挂 source_meeting_id） */
    createIssue: (projectId: string, data: CreateIssueRequest) =>
      request<Issue>(`/api/projects/${projectId}/issues`, { method: 'POST', body: JSON.stringify(data) }),
  },
  /** 议题平铺端点（ADR-017 Phase 2）：创建走 projects.createIssue */
  issues: {
    /** 单条议题 */
    get: (id: string) => request<Issue>(`/api/issues/${id}`, { method: 'GET' }),
    /** 更新字段 / 状态流转（状态机校验，非法流转 → 409） */
    update: (id: string, data: UpdateIssueRequest) =>
      request<Issue>(`/api/issues/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
    /** 删除议题（会议侧关联外键 SET NULL） */
    delete: (id: string) => request<{ deleted: string }>(`/api/issues/${id}`, { method: 'DELETE' }),
    /**
     * 合入 main（ADR-017 D11 两阶段确认）：
     * confirm=false 干跑预览（返回变更/冲突清单，不落状态）；
     * confirm=true 正式合并 + push + 议题闭环 + D13 索引重摄。
     * 冲突 → 409（议题已置 conflict 态，冲突清单在 error.details.conflicts）。
     */
    merge: (id: string, confirm: boolean) =>
      request<MergePreviewResponse | MergeExecuteResponse>(`/api/issues/${id}/merge`, {
        method: 'POST',
        body: JSON.stringify({ confirm }),
      }),
  },
};

/** 后端 /events 端点返回的领域事件信封（tool.started/step/completed/failed 等） */
export type RawMeetingEvent = {
  type: string;
  meeting_id: string;
  payload: Record<string, unknown>;
  schema_version?: string;
  ts: string;
  trace_id?: string | null;
  seq: number;
};
