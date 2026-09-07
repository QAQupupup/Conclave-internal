/**
 * 项目与议题池 hooks（ADR-017 Phase 2 前端接线）。
 *
 * 端点映射（挂 /api 前缀避免与 SPA 路由 /projects 冲突）：
 * - 项目 CRUD → /api/projects（routers/projects.py）
 * - 议题创建 → /api/projects/{id}/issues（嵌套端点）
 * - 议题读取/更新/删除 → /api/issues/{id}（平铺端点）
 *
 * 议题状态机与后端 issue_service.ALLOWED_TRANSITIONS 对齐，
 * UI 只暴露当前状态合法的流转目标（避免 409）。
 */
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import type {
  CreateIssueRequest,
  CreateProjectRequest,
  Issue,
  IssueStatus,
  MergeExecuteResponse,
  MergePreviewResponse,
  ProjectDetail,
  UpdateIssueRequest,
  UpdateProjectRequest,
} from '@/types';

// === 状态机元数据（与后端 issue_service 对齐） ===

export const ISSUE_STATUSES: IssueStatus[] = ['open', 'scheduled', 'in_progress', 'conflict', 'resolved', 'wontfix'];

export const ISSUE_STATUS_LABELS: Record<IssueStatus, string> = {
  open: '待处理',
  scheduled: '已排期',
  in_progress: '进行中',
  conflict: '合入冲突',
  resolved: '已闭环',
  wontfix: '不修复',
};

/**
 * 合法流转表：current → 允许的 target 集合（镜像后端校验，减少无效请求）。
 * 有意省略 in_progress → conflict：该流转仅由合入流程在冲突时系统置入，
 * 不是用户可发起的动作，UI 不暴露。
 */
export const ALLOWED_TRANSITIONS: Record<IssueStatus, IssueStatus[]> = {
  open: ['scheduled', 'in_progress', 'wontfix'],
  scheduled: ['in_progress', 'open', 'wontfix'],
  in_progress: ['resolved', 'open', 'wontfix'],
  // 合入冲突交回用户处置（D11）：回池 / 重新绑会 / 重试合入成功闭环 / 放弃
  conflict: ['open', 'in_progress', 'resolved', 'wontfix'],
  resolved: [],
  wontfix: [],
};

/** 可绑定会议发起的状态（后端 bind_meeting：open/scheduled/conflict → in_progress） */
export const BINDABLE_STATUSES: IssueStatus[] = ['open', 'scheduled', 'conflict'];

/** 可发起合入的状态（镜像后端 merge_service.MERGEABLE_STATUSES） */
export const MERGEABLE_STATUSES: IssueStatus[] = ['in_progress', 'conflict'];

export function allowedTransitions(status: string): IssueStatus[] {
  return ALLOWED_TRANSITIONS[status as IssueStatus] ?? [];
}

export function isBindable(status: string): boolean {
  return BINDABLE_STATUSES.includes(status as IssueStatus);
}

export function isMergeable(status: string): boolean {
  return MERGEABLE_STATUSES.includes(status as IssueStatus);
}

// === Query Keys ===

export const projectKeys = {
  all: ['projects'] as const,
  lists: () => [...projectKeys.all, 'list'] as const,
  list: (params: Record<string, unknown>) => [...projectKeys.lists(), params] as const,
  details: () => [...projectKeys.all, 'detail'] as const,
  detail: (id: string) => [...projectKeys.details(), id] as const,
  issues: (projectId: string, params: Record<string, unknown>) =>
    [...projectKeys.detail(projectId), 'issues', params] as const,
};

export const issueKeys = {
  all: ['issues'] as const,
  detail: (id: string) => [...issueKeys.all, 'detail', id] as const,
};

// === Queries ===

/** 项目分页列表（最新在上，附议题总数） */
export function useProjects(params: { limit?: number; offset?: number } = {}) {
  const limit = params.limit ?? 50;
  const offset = params.offset ?? 0;
  return useQuery({
    queryKey: projectKeys.list({ limit, offset }),
    queryFn: () => api.projects.list({ limit, offset }),
  });
}

/** 项目详情（含议题状态分组统计） */
export function useProject(id: string | null | undefined) {
  return useQuery({
    queryKey: projectKeys.detail(id!),
    queryFn: () => api.projects.get(id!),
    enabled: !!id,
  });
}

/** 项目议题列表（可按状态过滤，最新在上） */
export function useProjectIssues(
  projectId: string | null | undefined,
  params: { status?: string; limit?: number; offset?: number } = {},
) {
  const limit = params.limit ?? 50;
  const offset = params.offset ?? 0;
  return useQuery({
    queryKey: projectKeys.issues(projectId!, { status: params.status ?? '', limit, offset }),
    queryFn: () => api.projects.listIssues(projectId!, { status: params.status, limit, offset }),
    enabled: !!projectId,
  });
}

/** 单条议题（会议创建页 ?issue= 预填用） */
export function useIssue(id: string | null | undefined) {
  return useQuery({
    queryKey: issueKeys.detail(id!),
    queryFn: () => api.issues.get(id!),
    enabled: !!id,
  });
}

// === Mutations ===

function invalidateProjectScope(qc: ReturnType<typeof useQueryClient>, projectId?: string) {
  qc.invalidateQueries({ queryKey: projectKeys.lists() });
  if (projectId) {
    qc.invalidateQueries({ queryKey: projectKeys.detail(projectId) });
  }
}

export function useCreateProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: CreateProjectRequest) => api.projects.create(data),
    onSuccess: () => qc.invalidateQueries({ queryKey: projectKeys.lists() }),
  });
}

export function useUpdateProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: UpdateProjectRequest }) => api.projects.update(id, data),
    onSuccess: (_data, vars) => invalidateProjectScope(qc, vars.id),
  });
}

export function useDeleteProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.projects.delete(id),
    onSuccess: (_data, id) => {
      qc.invalidateQueries({ queryKey: projectKeys.lists() });
      qc.removeQueries({ queryKey: projectKeys.detail(id) });
    },
  });
}

export function useCreateIssue() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ projectId, data }: { projectId: string; data: CreateIssueRequest }) =>
      api.projects.createIssue(projectId, data),
    onSuccess: (_data, vars) => invalidateProjectScope(qc, vars.projectId),
  });
}

export function useUpdateIssue() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: UpdateIssueRequest }) => api.issues.update(id, data),
    onSuccess: (issue: Issue) => {
      qc.invalidateQueries({ queryKey: issueKeys.detail(issue.id) });
      invalidateProjectScope(qc, issue.project_id);
    },
  });
}

export function useDeleteIssue() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id }: { id: string; projectId: string }) => api.issues.delete(id),
    onSuccess: (_data, vars) => {
      qc.removeQueries({ queryKey: issueKeys.detail(vars.id) });
      invalidateProjectScope(qc, vars.projectId);
    },
  });
}

/**
 * 议题合入 main（ADR-017 D11 两阶段确认）。
 *
 * - confirm=false：预览（干跑合并，不落状态，无需失效缓存）；
 * - confirm=true：执行（合并 + push + 议题闭环），成功后失效议题详情与
 *   项目域缓存（议题状态 → resolved，统计随之变化）。
 */
export function useMergeIssue() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, confirm }: { id: string; confirm: boolean }) => api.issues.merge(id, confirm),
    onSuccess: (result: MergePreviewResponse | MergeExecuteResponse) => {
      if (result.mode === 'execute') {
        qc.invalidateQueries({ queryKey: issueKeys.detail(result.issue_id) });
        invalidateProjectScope(qc, result.project_id);
      }
    },
  });
}

/** 项目详情类型导出（视图层引用） */
export type { ProjectDetail };
