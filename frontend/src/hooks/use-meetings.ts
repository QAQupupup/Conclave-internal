import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { extractArray } from '@/lib/extract';
import { ROLE_LABELS, normalizeStageId } from '@/lib/constants';
import type { Meeting, PaginatedResponse, MeetingStatus, StageId, AgentRole, AgentState, MeetingMessage } from '@/types';

// === Backend Response Types ===
interface BackendMeetingItem {
  meeting_id: string;
  topic: string;
  stage: string;
  status: string;
  created_at: string;
  is_running: boolean;
  summary?: string;
  message_count?: number;
  agents?: Array<{ id: string; name: string; role: string; state?: string }>;
  tags?: string[];
}

interface BackendMeetingsResponse {
  meetings: BackendMeetingItem[];
  total: number;
  concurrent_limit?: number;
  running_count?: number;
}

// 会议详情接口返回格式
interface BackendMeetingDetail {
  meeting_id: string;
  topic: string;
  stage: string;
  status: string;
  clarified_topic?: string;
  key_questions?: string[];
  team_config?: Record<string, unknown>;
  role_configs?: Array<{ id: string; name: string; role: string; description?: string }>;
  claims?: unknown[];
  conflicts?: unknown[];
  evidence_set?: unknown[];
  decision_record?: unknown;
  artifact?: Record<string, unknown>;
  messages?: unknown[];
  intervention_messages?: unknown[];
  created_at?: string;
}

// === Normalization ===
// NOTE: snake_case fields (message_count, created_at, etc.) are marked @deprecated
// in the Meeting type. They are populated here ONLY for legacy component compatibility.
// New components must use the camelCase versions (messageCount, createdAt, etc.).
// Plan: remove snake_case fields once all legacy components are migrated.
function normalizeMeeting(raw: BackendMeetingItem): Meeting {
  return {
    id: raw.meeting_id,
    title: raw.topic || '未命名讨论',
    topic: raw.topic,
    status: (raw.status || 'pending') as MeetingStatus,
    stage: normalizeStageId(raw.stage || 'pending') as StageId,
    created_at: raw.created_at,
    createdAt: raw.created_at ? Date.parse(raw.created_at) : undefined,
    summary: raw.summary,
    message_count: raw.message_count,
    messageCount: raw.message_count,
    agents: Array.isArray(raw.agents)
      ? raw.agents.map((a) => ({
          id: a.id,
          name: a.name,
          role: a.role as AgentRole,
          state: (a.state || 'idle') as AgentState,
        }))
      : [],
    metadata: { is_running: raw.is_running, tags: raw.tags },
  };
}

function normalizeMeetingDetail(raw: BackendMeetingDetail): Meeting {
  const agents = Array.isArray(raw.role_configs)
    ? raw.role_configs.map((rc) => ({
        id: rc.id,
        name: rc.name,
        role: rc.role as AgentRole,
        state: 'idle' as AgentState,
      }))
    : [];
  const messageCount = Array.isArray(raw.messages) ? raw.messages.length : undefined;
  return {
    id: raw.meeting_id,
    title: raw.clarified_topic || raw.topic || '未命名讨论',
    topic: raw.topic,
    status: (raw.status || 'pending') as MeetingStatus,
    stage: normalizeStageId(raw.stage || 'pending') as StageId,
    created_at: raw.created_at,
    createdAt: raw.created_at ? Date.parse(raw.created_at) : undefined,
    messageCount,
    message_count: messageCount,
    agents,
    summary: raw.artifact?.summary as string | null | undefined,
    metadata: {
      key_questions: raw.key_questions,
      artifact: raw.artifact,
      team_config: raw.team_config,
    },
  };
}

// === Query Keys ===
export const meetingKeys = {
  all: ['meetings'] as const,
  lists: () => [...meetingKeys.all, 'list'] as const,
  list: (params: Record<string, unknown>) => [...meetingKeys.lists(), params] as const,
  details: () => [...meetingKeys.all, 'detail'] as const,
  detail: (id: string) => [...meetingKeys.details(), id] as const,
  messages: (id: string) => [...meetingKeys.detail(id), 'messages'] as const,
};

// === Queries ===
export function useMeetings(params: { page?: number; pageSize?: number; status?: string; q?: string } = {}) {
  const page = params.page ?? 1;
  const pageSize = params.pageSize ?? 20;
  const offset = (page - 1) * pageSize;
  return useQuery({
    queryKey: meetingKeys.list(params),
    queryFn: async () => {
      const queryParams = new URLSearchParams();
      queryParams.set('limit', String(pageSize));
      queryParams.set('offset', String(offset));
      if (params.status) queryParams.set('status', params.status);
      if (params.q) queryParams.set('q', params.q);
      const res = await api.get<BackendMeetingsResponse | PaginatedResponse<Meeting>>(
        `/meetings?${queryParams.toString()}`
      );
      // 兼容两种格式：后端 { meetings: [...] } 和 前端 { items: [...] }
      const rawMeetings = extractArray<BackendMeetingItem | Meeting>(res, ['meetings', 'items']);
      const meetings = rawMeetings.map((m) => {
        // 如果已经有 id 字段（前端格式），直接返回
        if ((m as Meeting).id) return m as Meeting;
        // 否则从后端格式规范化
        return normalizeMeeting(m as BackendMeetingItem);
      });
      return {
        items: meetings,
        total: (res as unknown as Record<string, unknown>)?.total as number ?? meetings.length,
        page,
        pageSize,
      } as PaginatedResponse<Meeting>;
    },
  });
}

/** 监控看板概览：会议列表 + 并发上限 + 运行中计数 */
export interface MeetingsOverview {
  meetings: Meeting[];
  total: number;
  concurrentLimit: number;
  runningCount: number;
}

/**
 * 会议监控概览（并发会话总览）。
 * 后端 /meetings 返回 { meetings, total, concurrent_limit, running_count }；
 * demo 模式下 running_count 兜底从列表本地计算。
 * pollMs 为 0 时不轮询（单次拉取）。
 */
export function useMeetingsOverview(pollMs = 3000) {
  return useQuery({
    queryKey: ['meetings', 'overview'],
    queryFn: async (): Promise<MeetingsOverview> => {
      const res = await api.get<BackendMeetingsResponse>(`/meetings?limit=200&offset=0`);
      const rawMeetings = extractArray<BackendMeetingItem | Meeting>(res, ['meetings', 'items']);
      const meetings = rawMeetings.map((m) => {
        if ((m as Meeting).id) return m as Meeting;
        return normalizeMeeting(m as BackendMeetingItem);
      });
      // running_count 口径统一为「正在运行」：后端值取自 _running_tasks（paused 已释放 task），
      // 兜底也只统计 running，避免与并发槽位/运行中卡片口径不一致。
      const runningCount =
        typeof (res as unknown as Record<string, unknown>)?.running_count === 'number'
          ? Number((res as unknown as Record<string, unknown>).running_count)
          : meetings.filter((m) => m.status === 'running').length;
      return {
        meetings,
        total: (res as unknown as Record<string, unknown>)?.total as number ?? meetings.length,
        concurrentLimit:
          typeof (res as unknown as Record<string, unknown>)?.concurrent_limit === 'number'
            ? Number((res as unknown as Record<string, unknown>).concurrent_limit)
            : 0,
        runningCount,
      };
    },
    staleTime: pollMs > 0 ? pollMs : 30_000,
    refetchInterval: pollMs > 0 ? pollMs : false,
  });
}

export function useMeeting(id: string | null | undefined) {
  return useQuery({
    queryKey: meetingKeys.detail(id!),
    queryFn: async () => {
      const raw = await api.get<BackendMeetingDetail | Meeting>(`/meetings/${id}`);
      // 如果已经是前端格式（有 id + title），直接返回
      if ((raw as Meeting).id && (raw as Meeting).agents) return raw as Meeting;
      // 否则从后端详情格式规范化
      return normalizeMeetingDetail(raw as BackendMeetingDetail);
    },
    enabled: !!id,
  });
}

/** 原始会议详情（含 conflicts / evidence_set / decision_record，供可观测性面板） */
export function useMeetingDetailRaw(id: string | null | undefined) {
  return useQuery({
    queryKey: [...meetingKeys.detail(id!), 'raw'],
    queryFn: () => api.get<BackendMeetingDetail>(`/meetings/${id}`),
    enabled: !!id,
  });
}

/** 后端消息行（messages 表） */
interface BackendMessageRow {
  id: string;
  meeting_id: string;
  agent_role: string;
  stage: string;
  content: string;
  claim_refs?: unknown[];
  evidence_refs?: unknown[];
  created_at: string;
}

export function useMeetingMessages(
  id: string | null | undefined,
  params: { before?: number; limit?: number } = {}
) {
  return useQuery({
    queryKey: [...meetingKeys.messages(id!), params],
    queryFn: async () => {
      const res = await api.get<{ messages: BackendMessageRow[] } | BackendMessageRow[]>(
        `/meetings/${id}/messages?limit=${params.limit ?? 500}${
          params.before ? `&before=${params.before}` : ''
        }`
      );
      // 标准化：兼容 { messages: [...] } 和裸数组 [...] 两种格式
      const rows: BackendMessageRow[] = Array.isArray(res)
        ? res
        : res && typeof res === 'object' && Array.isArray(res.messages)
          ? res.messages
          : [];
      // 映射为前端 MeetingMessage 结构（REST 历史兜底）
      return rows.map((r) => ({
        id: r.id,
        meeting_id: r.meeting_id,
        agentRole: r.agent_role as MeetingMessage['agentRole'],
        agentName: ROLE_LABELS[r.agent_role] || r.agent_role,
        stage: r.stage as MeetingMessage['stage'],
        content: r.content,
        timestamp: r.created_at ? Date.parse(r.created_at) : Date.now(),
        isUser: r.agent_role === 'user',
      }));
    },
    enabled: !!id,
  });
}

// === Mutations ===
/** 创建会议参数：与 backend CreateMeetingRequest 对齐 */
export interface StartMeetingPayload {
  topic: string;
  deliverable_type?: string;
  flow_plan?: string;
  debate_depth?: string;
  role_ids?: string[];
  reference_meeting_ids?: string[];
  /** ADR-017 Phase 2：从议题发起会议（仅 open/scheduled 可绑定，后端驱动状态机 → in_progress） */
  issue_id?: string;
  model?: string;
  auto_iterate?: boolean;
  max_iterations?: number;
}

export function useStartMeeting() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: StartMeetingPayload) =>
      api.post<{ meeting_id: string }>('/meetings', data),
    onSuccess: () => qc.invalidateQueries({ queryKey: meetingKeys.lists() }),
  });
}

/** 启动会议运行（POST /meetings 只创建不运行，必须显式调用 /run） */
export function useRunMeeting() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.post(`/meetings/${id}/run`),
    onSuccess: (_data, id) => {
      qc.invalidateQueries({ queryKey: meetingKeys.lists() });
      qc.invalidateQueries({ queryKey: meetingKeys.detail(id) });
    },
  });
}

/** 上传会议参考文档（真实 multipart，含进度回调） */
export function useUploadMeetingDocument() {
  return useMutation({
    mutationFn: ({
      meetingId,
      file,
      onProgress,
    }: {
      meetingId: string;
      file: File;
      onProgress?: (percent: number) => void;
    }) =>
      api.upload<{ document_id?: string; chunk_count?: number }>(
        `/meetings/${meetingId}/documents`,
        file,
        { onProgress },
      ),
  });
}

/** 角色列表（创建会议时预选角色用） */
export interface AgentRoleItem {
  id: string;
  display_name: string;
  perspective?: string;
  is_active?: boolean;
  is_builtin?: boolean;
}

export function useAgentRoles() {
  return useQuery({
    queryKey: ['agent-roles', 'list'],
    queryFn: async () => {
      const res = await api.get<{ roles: AgentRoleItem[] }>('/agent-roles');
      return Array.isArray(res?.roles) ? res.roles : [];
    },
    staleTime: 60_000,
  });
}

export function useControlMeeting() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, signal, payload }: { id: string; signal: string; payload?: Record<string, unknown> }) =>
      api.post(`/meetings/${id}/control`, { signal, payload }),
    onSuccess: (_data, vars) => qc.invalidateQueries({ queryKey: meetingKeys.detail(vars.id) }),
  });
}

export function useApproveBorrow() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ meetingId, decision, requestId, reason }: {
      meetingId: string;
      decision: 'approve' | 'reject';
      requestId: string;
      reason?: string;
    }) =>
      api.post(`/meetings/${meetingId}/control`, {
        signal: decision === 'approve' ? 'approve_borrow' : 'reject_borrow',
        payload: { request_id: requestId, ...(reason ? { reason } : {}) },
      }),
    onSuccess: (_data, vars) => qc.invalidateQueries({ queryKey: meetingKeys.detail(vars.meetingId) }),
  });
}

export function useDeleteMeeting() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete(`/meetings/${id}`),
    onSuccess: (_data, id) => {
      qc.invalidateQueries({ queryKey: meetingKeys.lists() });
      qc.removeQueries({ queryKey: meetingKeys.detail(id) });
    },
  });
}
