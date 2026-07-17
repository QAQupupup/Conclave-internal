/* Conclave API Client — ported from app.html
 * 统一 HTTP 客户端：自动注入 JWT、401 处理、JSON 解析。 */
import { getToken, clearToken, commitLogin, commitLogout } from './auth';
import type { ConclaveUser } from './auth';

const API_BASE = ''; // 同源

/** 401 时触发（App 层注册为全局认证过期处理） */
let unauthorizedHandler: (() => void) | null = null;
export function onUnauthorized(fn: () => void): void {
  unauthorizedHandler = fn;
}

export interface ApiOptions extends RequestInit {
  headers?: Record<string, string>;
  /** 静默模式：401 时仍触发全局 authExpired，但不抛错（调用方 catch 后回退 mock） */
  silent?: boolean;
}

export async function api<T = any>(path: string, opts: ApiOptions = {}): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(opts.headers || {}),
  };
  const token = getToken();
  if (token) headers['Authorization'] = `Bearer ${token}`;
  try {
    const res = await fetch(API_BASE + path, { ...opts, headers });
    if (res.status === 401) {
      clearToken();
      // 全局 401 拦截器总是触发（token 过期是全局事件，与 silent 无关）
      // AppContext 的 handler 内部有去重，并发 401 只触发一次
      unauthorizedHandler?.();
      throw new Error('未登录或登录已过期');
    }
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    return (res.status === 204 ? null : await res.json()) as T;
  } catch (e: any) {
    if (e.message === 'Failed to fetch') throw new Error('无法连接服务器，请检查后端是否启动');
    throw e;
  }
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
    return await api<ConclaveUser>('/auth/me', { silent: true });
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
  return api(`/meetings/${meetingId}/run`, { method: 'POST' });
}
export async function apiGetProgress(meetingId: string) {
  return api(`/meetings/${meetingId}/progress`);
}
export async function apiControlMeeting(meetingId: string, signal: string, payload: any = {}) {
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

/* ═══ Preferences API ═══ */
export async function apiGetPreferences(silent = false) {
  return api('/preferences/', { silent });
}
export async function apiSetPreference(key: string, value: any) {
  return api(`/preferences/${key}`, { method: 'PUT', body: JSON.stringify({ value }) });
}

/* ═══ LLM API ═══ */
export async function apiGetProviders(silent = false) {
  return api('/meetings/llm/providers', { silent });
}
export async function apiGetModels(silent = false) {
  return api('/meetings/llm/models', { silent });
}
export async function apiGetKeys(silent = false) {
  return api('/meetings/llm/keys', { silent });
}
export async function apiSaveKey(provider: string, name: string, key: string) {
  return api('/meetings/llm/keys', {
    method: 'POST',
    body: JSON.stringify({ provider, name, key }),
  });
}
