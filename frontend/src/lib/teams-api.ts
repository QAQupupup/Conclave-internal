/**
 * Team（工作空间）管理 API 封装。
 * 对应后端 /api/teams 和 /api/teams/{tid}/members 等端点。
 */
import { api } from './api';
import type {
  TeamDetail,
  TeamListResponse,
  TeamMember,
  TeamMemberListResponse,
  TeamRole,
  EffectiveConfig,
} from '@/types';

export interface ListMembersParams {
  page?: number;
  page_size?: number;
  search?: string;
  role?: TeamRole;
  include_banned?: boolean;
}

export type ListMembersResult = TeamMemberListResponse;

export const teamsApi = {
  // ========== Team CRUD ==========

  listMyTeams: () => api.get<TeamListResponse>('/api/teams'),

  getTeam: (tid: number) => api.get<TeamDetail & { my_role?: string }>(`/api/teams/${tid}`),

  createTeam: (data: { name: string; slug?: string; description?: string; settings?: Record<string, unknown> }) =>
    api.post<TeamDetail>('/api/teams', data),

  updateTeam: (tid: number, data: { name?: string; description?: string; settings?: Record<string, unknown> }) =>
    api.patch<TeamDetail>(`/api/teams/${tid}`, data),

  deleteTeam: (tid: number) => api.delete<{ success: boolean }>(`/api/teams/${tid}`),

  transferOwnership: (tid: number, targetUserId: number) =>
    api.post<{ success: boolean }>(`/api/teams/${tid}/transfer`, { target_user_id: targetUserId }),

  // ========== 成员管理 ==========

  listMembers: (tid: number, params: ListMembersParams = {}) => {
    const qs = new URLSearchParams();
    if (params.page) qs.set('page', String(params.page));
    if (params.page_size) qs.set('page_size', String(params.page_size));
    if (params.search) qs.set('search', params.search);
    if (params.role) qs.set('role', params.role);
    if (params.include_banned) qs.set('include_banned', 'true');
    const q = qs.toString();
    return api.get<ListMembersResult>(`/api/teams/${tid}/members${q ? `?${q}` : ''}`);
  },

  addMember: (tid: number, data: { username: string; role?: TeamRole }) =>
    api.post<{ user_id: number; username: string; role: TeamRole }>(`/api/teams/${tid}/members`, data),

  removeMember: (tid: number, userId: number) =>
    api.delete<{ success: boolean }>(`/api/teams/${tid}/members/${userId}`),

  updateMemberRole: (tid: number, userId: number, newRole: TeamRole) =>
    api.patch<{ success: boolean }>(`/api/teams/${tid}/members/${userId}`, { role: newRole }),

  banMember: (tid: number, userId: number, reason?: string) =>
    api.post<{ success: boolean }>(`/api/teams/${tid}/members/${userId}/ban`, { reason }),

  unbanMember: (tid: number, userId: number, newRole: TeamRole = 'member') =>
    api.post<{ success: boolean }>(`/api/teams/${tid}/members/${userId}/unban`, { role: newRole }),

  // ========== 用户搜索（邀请） ==========

  searchUsers: (keyword: string, teamId?: number, excludeMembers = true, limit = 10) => {
    const qs = new URLSearchParams({ q: keyword, limit: String(limit) });
    if (teamId) qs.set('team_id', String(teamId));
    if (excludeMembers) qs.set('exclude_team_members', 'true');
    return api.get<Array<Pick<TeamMember, 'user_id' | 'username' | 'display_name' | 'email'>>>(
      `/api/users/search?${qs.toString()}`
    );
  },
};

export const configApi = {
  getEffectiveConfig: () => api.get<EffectiveConfig>('/api/config/effective'),

  getPersonalConfig: () => api.get<Record<string, unknown>>('/api/config/personal'),

  setPersonalConfig: (key: string, value: unknown, valueType = 'string') =>
    api.put(`/api/config/personal/${key}`, { value, value_type: valueType }),

  deletePersonalConfig: (key: string) => api.delete(`/api/config/personal/${key}`),

  getTeamConfig: (tid: number) => api.get<Record<string, unknown>>(`/api/config/team/${tid}`),

  updateTeamConfig: (tid: number, patch: Record<string, unknown>) =>
    api.put(`/api/config/team/${tid}`, patch),

  getTeamPermissions: (tid: number) =>
    api.get<Record<string, Record<string, boolean>>>(`/api/config/team/${tid}/permissions`),

  updateTeamPermissions: (tid: number, permissions: Record<string, string[]>) =>
    api.put(`/api/config/team/${tid}/permissions`, { permissions }),

  getSystemConfig: () => api.get<Record<string, unknown>>('/api/config/system'),

  setSystemConfig: (key: string, value: unknown, valueType = 'string') =>
    api.put(`/api/config/system/${key}`, { value, value_type: valueType }),
};
