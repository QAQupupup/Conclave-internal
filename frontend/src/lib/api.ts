/* Conclave API Client — ported from app.html
 * 统一 HTTP 客户端：自动注入 JWT、401 处理、JSON 解析、超时、重试。 */
import { getToken, clearToken, commitLogin, commitLogout, updateAuthUser } from './auth';
import type { ConclaveUser, ConclaveTenant } from './auth';
import type { HealthCheckResult, DockerHostPreset, ContainerInfo, PreferenceValue } from '../types/meeting';

const API_BASE = ''; // 同源

/** 默认超时时间（毫秒） */
const DEFAULT_TIMEOUT = 30_000;
/** 长操作超时（会议创建/运行/健康检查等可能耗时较长的请求） */
const LONG_TIMEOUT = 120_000;
/** 幂等 GET 请求在网络错误时的重试次数 */
const NETWORK_RETRY_COUNT = 1;

/** 401 时触发（App 层注册为全局认证过期处理） */
let unauthorizedHandler: (() => void) | null = null;
export function onUnauthorized(fn: () => void): void {
  unauthorizedHandler = fn;
}

export interface ApiOptions extends RequestInit {
  headers?: Record<string, string>;
  /** 静默模式：401 时仍触发全局 authExpired，但不抛错（调用方 catch 后回退 mock） */
  silent?: boolean;
  /** 请求超时（毫秒），默认 30000 */
  timeout?: number;
  /** 网络错误时重试次数（仅 GET/HEAD 请求），默认 1 */
  retries?: number;
}

export async function api<T = Record<string, unknown>>(path: string, opts: ApiOptions = {}): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(opts.headers || {}),
  };
  const token = getToken();
  if (token) headers['Authorization'] = `Bearer ${token}`;

  const timeout = opts.timeout ?? DEFAULT_TIMEOUT;
  const maxRetries = opts.retries ?? (opts.method === 'POST' || opts.method === 'PUT' || opts.method === 'DELETE' || opts.method === 'PATCH' ? 0 : NETWORK_RETRY_COUNT);

  let lastError: Error | null = null;
  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeout);

    // 如果调用方传入了 signal，串联两个 signal
    if (opts.signal) {
      if (opts.signal.aborted) {
        clearTimeout(timer);
        throw new Error('请求已取消');
      }
      opts.signal.addEventListener('abort', () => controller.abort(), { once: true });
    }

    try {
      const res = await fetch(API_BASE + path, {
        ...opts,
        headers,
        signal: controller.signal,
      });
      clearTimeout(timer);

      if (res.status === 401) {
        clearToken();
        unauthorizedHandler?.();
        throw new Error('未登录或登录已过期');
      }
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      return (res.status === 204 ? null : await res.json()) as T;
    } catch (e: unknown) {
      const err = e instanceof Error ? e : new Error(String(e));
      clearTimeout(timer);
      lastError = err;

      // AbortError（超时/取消）不重试
      if (err.name === 'AbortError') {
        if (opts.signal?.aborted) throw new Error('请求已取消', { cause: e });
        throw new Error(`请求超时（${Math.round(timeout / 1000)}秒）`, { cause: e });
      }

      // 网络错误且还有重试次数时，短暂延迟后重试
      const isNetworkError = err.message === 'Failed to fetch' || err.message?.includes('network');
      if (isNetworkError && attempt < maxRetries) {
        await new Promise(r => setTimeout(r, 500 * (attempt + 1)));
        continue;
      }

      if (err.message === 'Failed to fetch') throw new Error('无法连接服务器，请检查后端是否启动', { cause: e });
      throw err;
    }
  }
  throw lastError!;
}

/* ═══ Auth API ═══ */
export async function apiLogin(username: string, password: string) {
  const data = await api<{ access_token: string; user: ConclaveUser }>(
    '/auth/login',
    { method: 'POST', body: JSON.stringify({ username, password }) },
  );
  commitLogin(data.access_token, data.user);
  return data;
}
export async function apiMe(): Promise<ConclaveUser | null> {
  try {
    const data = await api<{ user: ConclaveUser }>('/auth/me', { silent: true });
    return data?.user || null;
  } catch {
    return null;
  }
}
export function apiLogout(): void {
  commitLogout();
}

/* ═══ Meeting API ═══ */
export interface CreateMeetingOpts {
  flowPlan?: string;
  debateDepth?: string;
  roleIds?: string[];
  referenceMeetingIds?: string[];
  model?: string;
}
export async function apiCreateMeeting(topic: string, deliverableType: string, opts: CreateMeetingOpts = {}) {
  return api('/meetings', {
    method: 'POST',
    body: JSON.stringify({
      topic,
      deliverable_type: deliverableType,
      flow_plan: opts.flowPlan || 'standard',
      debate_depth: opts.debateDepth || 'standard',
      role_ids: opts.roleIds || [],
      reference_meeting_ids: opts.referenceMeetingIds || [],
      model: opts.model || '',
    }),
  });
}
export async function apiListMeetings(q = '', limit = 20, offset = 0, silent = false) {
  const params = new URLSearchParams();
  if (q) params.set('q', q);
  params.set('limit', String(limit));
  params.set('offset', String(offset));
  return api(`/meetings?${params}`, { silent });
}
export async function apiGetMeeting(meetingId: string) {
  return api(`/meetings/${meetingId}`);
}
export async function apiRunMeeting(meetingId: string) {
  return api(`/meetings/${meetingId}/run`, { method: 'POST', timeout: LONG_TIMEOUT });
}
export async function apiHealthCheckHost(id: number) {
  return api<HealthCheckResult>(`/docker-hosts/${id}/health-check`, { method: 'POST', timeout: LONG_TIMEOUT });
}
export async function apiHealthCheckAllHosts() {
  return api<{ checked: number; results: HealthCheckResult[] }>('/docker-hosts/health-check-all', { method: 'POST', timeout: LONG_TIMEOUT });
}
export async function apiGetProgress(meetingId: string) {
  return api(`/meetings/${meetingId}/progress`);
}
export async function apiControlMeeting(meetingId: string, signal: string, payload: Record<string, unknown> = {}) {
  return api(`/meetings/${meetingId}/control`, {
    method: 'POST',
    body: JSON.stringify({ signal, payload }),
  });
}
export async function apiIntervene(meetingId: string, content: string, replyToId: string | null = null) {
  return api(`/meetings/${meetingId}/intervene`, {
    method: 'POST',
    body: JSON.stringify({ content, reply_to_id: replyToId }),
  });
}
export async function apiGetReportLayout(meetingId: string, deliverableType?: string, silent = false) {
  const typeParam = deliverableType ? `?type=${deliverableType}` : '';
  return api(`/meetings/${meetingId}/report-layout${typeParam}`, { silent });
}
export async function apiGetTrace(meetingId: string) {
  return api(`/meetings/${meetingId}/trace`);
}
export async function apiDeleteMeeting(meetingId: string) {
  return api(`/meetings/${meetingId}`, { method: 'DELETE' });
}

/* ═══ Agent Roles API ═══ */
export async function apiListAgentRoles() {
  return api('/agent-roles');
}
export async function apiGenerateRoles(topic: string) {
  return api('/agent-roles/generate', { method: 'POST', body: JSON.stringify({ topic }) });
}

/* ═══ Metrics API ═══ */
export async function apiGetMetrics(silent = false) {
  return api('/metrics', { silent });
}
export async function apiGetMetricsHistory(minutes = 60) {
  return api(`/metrics/history?minutes=${minutes}`);
}
export async function apiGetHealth() {
  return api('/metrics/health');
}
export async function apiGetSecurityEvents(limit = 50) {
  return api(`/audit/security-events?limit=${limit}`);
}

/* ═══ Preferences API ═══ */
export async function apiGetPreferences(silent = false) {
  return api('/preferences/', { silent });
}
export async function apiSetPreference(key: string, value: PreferenceValue) {
  return api(`/preferences/${encodeURIComponent(key)}`, { method: 'PUT', body: JSON.stringify({ value }) });
}
export async function apiDeletePreference(key: string) {
  return api(`/preferences/${encodeURIComponent(key)}`, { method: 'DELETE' });
}

/* ═══ LLM API ═══ */
export async function apiGetProviders(silent = false) {
  return api('/meetings/llm/providers', { silent });
}
export async function apiQueryModels(params: { provider?: string; api_key?: string; base_url?: string; refresh?: boolean } = {}, silent = false) {
  return api('/meetings/llm/models', {
    method: 'POST',
    body: JSON.stringify(params),
    silent,
  });
}
export async function apiQueryBalance(params: { provider?: string; api_key?: string; base_url?: string } = {}) {
  return api('/meetings/llm/balance', {
    method: 'POST',
    body: JSON.stringify(params),
  });
}
export async function apiGetModels(silent = false) {
  // 兼容旧调用：无参数查询默认模型列表
  return apiQueryModels({}, silent);
}
export async function apiGetKeys(silent = false) {
  return api<{ keys: LlmKey[] }>('/meetings/llm/keys', { silent });
}
export interface LlmKey {
  id: number;
  provider: string;
  name: string;
  key_masked: string;
  base_url: string;
  is_default: boolean;
  created_at?: string;
  updated_at?: string;
}
export async function apiSaveKey(provider: string, name: string, key: string, base_url = '', is_default = true) {
  return api('/meetings/llm/keys', {
    method: 'POST',
    body: JSON.stringify({ provider, name, key, base_url, is_default }),
  });
}
export async function apiDeleteKey(provider: string, name: string) {
  return api(`/meetings/llm/keys/${encodeURIComponent(provider)}/${encodeURIComponent(name)}`, {
    method: 'DELETE',
  });
}

/* ═══ Docker Hosts API ═══ */
export interface DockerHost {
  id: number;
  name: string;
  description: string;
  connection_type: string;
  docker_host: string;
  ssh_user: string;
  ssh_port: number;
  ssh_key_path: string;
  tls_cert_path: string;
  tls_verify: boolean;
  tags: string[];
  region: string;
  cpu_cores: number;
  memory_gb: number;
  max_containers: number;
  enabled: boolean;
  is_default: boolean;
  health_status: string;
  last_health_check: string | null;
  docker_version: string;
  running_containers: number;
  total_containers: number;
  last_error: string;
  deployed_meetings: string[];
  created_at: string;
  updated_at: string;
}

export interface DockerHostInput {
  name: string;
  description?: string;
  connection_type: string;
  docker_host?: string;
  ssh_user?: string;
  ssh_port?: number;
  ssh_key_path?: string;
  ssh_password?: string;
  ssh_key_content?: string;
  tls_cert_path?: string;
  tls_key_path?: string;
  tls_ca_path?: string;
  tls_verify?: boolean;
  tags?: string[];
  region?: string;
  cpu_cores?: number;
  memory_gb?: number;
  max_containers?: number;
  enabled?: boolean;
  is_default?: boolean;
}

export async function apiListDockerHosts() {
  return api<{ hosts: DockerHost[]; total: number }>('/docker-hosts');
}
export async function apiGetDockerHost(id: number) {
  return api<DockerHost>(`/docker-hosts/${id}`);
}
export async function apiCreateDockerHost(data: DockerHostInput) {
  return api<DockerHost>('/docker-hosts', { method: 'POST', body: JSON.stringify(data) });
}
export async function apiUpdateDockerHost(id: number, data: Partial<DockerHostInput>) {
  return api<DockerHost>(`/docker-hosts/${id}`, { method: 'PUT', body: JSON.stringify(data) });
}
export async function apiDeleteDockerHost(id: number) {
  return api(`/docker-hosts/${id}`, { method: 'DELETE' });
}
export async function apiGetDockerPresets() {
  return api<DockerHostPreset>('/docker-hosts/presets');
}
export async function apiGetDockerSetupScript() {
  return api<{ script: string; instructions: string[]; quick_install: string }>('/docker-hosts/setup-script');
}
export async function apiGetHostContainers(id: number) {
  return api<{ ok: boolean; containers: ContainerInfo[]; host: string }>(`/docker-hosts/${id}/containers`);
}
export async function apiSelectDeployTarget(requirements?: Record<string, unknown>, preferredHostId?: number, strategy?: string) {
  const params = new URLSearchParams();
  if (preferredHostId) params.set('preferred_host_id', String(preferredHostId));
  if (strategy) params.set('strategy', strategy);
  return api(`/docker-hosts/select-target?${params}`, {
    method: 'POST',
    body: requirements ? JSON.stringify(requirements) : undefined,
  });
}

/* ═══ Tenant API ═══ */
export interface TenantInfo extends ConclaveTenant {
  owner_id?: number;
  settings?: Record<string, unknown>;
  created_at?: string;
}
export interface TenantMember {
  user_id: number;
  username: string;
  display_name: string;
  email?: string;
  role: string;
  joined_at?: string;
}

export async function apiListTenants(): Promise<TenantInfo[]> {
  const data = await api<{ tenants: TenantInfo[]; current_tenant_id?: number | null }>('/api/tenants');
  return Array.isArray(data) ? data : (data?.tenants || []);
}
export async function apiCreateTenant(name: string, plan = 'free'): Promise<TenantInfo> {
  return api<TenantInfo>('/api/tenants', {
    method: 'POST',
    body: JSON.stringify({ name, plan }),
  });
}
export async function apiGetTenant(tenantId: number): Promise<TenantInfo> {
  return api<TenantInfo>(`/api/tenants/${tenantId}`);
}
export async function apiTenantMembers(tenantId: number): Promise<{ members: TenantMember[] }> {
  return api<{ members: TenantMember[] }>(`/api/tenants/${tenantId}/members`);
}
export async function apiSwitchTenant(tenantId: number): Promise<{ access_token: string; user: ConclaveUser }> {
  const data = await api<{ access_token: string; user: ConclaveUser }>('/api/tenants/switch', {
    method: 'POST',
    body: JSON.stringify({ tenant_id: tenantId }),
  });
  // 切换成功后更新 token 和用户信息（会通知订阅者）
  commitLogin(data.access_token, data.user);
  return data;
}

// ── 个人资料 / 密码 ──

export async function apiUpdateProfile(displayName: string): Promise<{ success: boolean; display_name: string }> {
  return api('/auth/profile', {
    method: 'PUT',
    body: JSON.stringify({ display_name: displayName }),
  });
}

export async function apiChangePassword(oldPassword: string, newPassword: string): Promise<{ success: boolean }> {
  return api('/auth/change-password', {
    method: 'POST',
    body: JSON.stringify({ old_password: oldPassword, new_password: newPassword }),
  });
}

// ── LLM 余额查询 ──

export async function apiQueryBalanceForKey(provider: string, apiKey: string, baseUrl?: string): Promise<{ balance?: number; error?: string; unit?: string }> {
  const params = new URLSearchParams({ provider, api_key: apiKey });
  if (baseUrl) params.set('base_url', baseUrl);
  return api(`/meetings/llm/balance?${params.toString()}`);
}

