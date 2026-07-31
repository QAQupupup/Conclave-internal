import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import type { Meeting, PaginatedResponse } from '@/types';

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
    queryFn: () =>
      api.get<PaginatedResponse<Meeting>>(
        `/meetings?page=${params.page ?? 1}&page_size=${params.pageSize ?? 20}${
          params.status ? `&status=${params.status}` : ''
        }`
      ),
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
    queryFn: () =>
      api.get<{ messages: any[] }>(
        `/meetings/${id}/messages?limit=${params.limit ?? 50}${
          params.before ? `&before=${params.before}` : ''
        }`
      ),
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
