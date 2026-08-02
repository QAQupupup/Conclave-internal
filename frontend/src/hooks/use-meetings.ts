import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { extractArray } from '@/lib/extract';
import type { Meeting, PaginatedResponse, MeetingStatus, StageId, AgentRole, AgentState } from '@/types';

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

// === Normalization ===
function normalizeMeeting(raw: BackendMeetingItem): Meeting {
  return {
    id: raw.meeting_id,
    title: raw.topic || '未命名讨论',
    topic: raw.topic,
    status: (raw.status || 'pending') as MeetingStatus,
    stage: (raw.stage || 'pending') as StageId,
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
export function useMeetings(params: { page?: number; pageSize?: number; status?: string } = {}) {
  return useQuery({
    queryKey: meetingKeys.list(params),
    queryFn: async () => {
      const res = await api.get<BackendMeetingsResponse | PaginatedResponse<Meeting>>(
        `/meetings?page=${params.page ?? 1}&page_size=${params.pageSize ?? 20}${
          params.status ? `&status=${params.status}` : ''
        }`
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
        page: params.page ?? 1,
        pageSize: params.pageSize ?? 20,
      } as PaginatedResponse<Meeting>;
    },
  });
}

export function useMeeting(id: string | null | undefined) {
  return useQuery({
    queryKey: meetingKeys.detail(id!),
    queryFn: () => api.get<Meeting>(`/meetings/${id}`),
    enabled: !!id,
  });
}

export function useMeetingMessages(
  id: string | null | undefined,
  params: { before?: number; limit?: number } = {}
) {
  return useQuery({
    queryKey: [...meetingKeys.messages(id!), params],
    queryFn: async () => {
      const res = await api.get<{ messages: any[] } | any[]>(
        `/meetings/${id}/messages?limit=${params.limit ?? 50}${
          params.before ? `&before=${params.before}` : ''
        }`
      );
      // 标准化：兼容 { messages: [...] } 和裸数组 [...] 两种格式
      if (Array.isArray(res)) return res;
      if (res && typeof res === 'object' && Array.isArray(res.messages)) return res.messages;
      return [];
    },
    enabled: !!id,
  });
}

// === Mutations ===
export function useStartMeeting() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { topic: string; agents?: string[]; deliverable_type?: string }) =>
      api.post<{ meeting_id: string }>('/meetings', data),
    onSuccess: () => qc.invalidateQueries({ queryKey: meetingKeys.lists() }),
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
    onSuccess: () => qc.invalidateQueries({ queryKey: meetingKeys.lists() }),
  });
}
