export interface ApiError {
  message: string;
  code?: string;
  status?: number;
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  pageSize: number;
  page_size?: number;
  totalPages?: number;
  total_pages?: number;
  hasMore?: boolean;
}

// ---------------------------------------------------------------------------
// 产物（ADR-017 Phase 1）
// ---------------------------------------------------------------------------

/** 产物：会议产出的一等公民实体（artifacts 表） */
export interface Artifact {
  id: string;
  tenant_id?: number | null;
  meeting_id: string;
  project_id?: string | null;
  type: string;
  title?: string | null;
  summary?: string | null;
  content?: Record<string, unknown> | null;
  content_ref?: string | null;
  version: number;
  parent_id?: string | null;
  source_artifact_ids: string[];
  created_by?: string | null;
  created_at?: string | null;
}

/** 产物分页列表响应（最新在上） */
export interface ArtifactListResponse {
  items: Artifact[];
  total: number;
}

/** 血缘图节点（depth=0 为查询起点） */
export interface ArtifactLineageNode {
  id: string;
  type: string;
  title?: string | null;
  version?: number | null;
  meeting_id?: string | null;
  created_at?: string | null;
  depth: number;
}

/** 血缘图边：child 消费 parent（下游产物 → 上游产物） */
export interface ArtifactLineageEdge {
  child_id: string;
  parent_id: string;
}

/** 产物上游血缘响应（深度上限防环） */
export interface ArtifactLineageResponse {
  root_id: string;
  depth_limit: number;
  truncated: boolean;
  nodes: ArtifactLineageNode[];
  edges: ArtifactLineageEdge[];
}

// ---------------------------------------------------------------------------
// 项目与议题池（ADR-017 Phase 2）
// ---------------------------------------------------------------------------

/** 议题状态（与后端 ISSUE_STATUS_VALUES 对齐） */
export type IssueStatus = 'open' | 'scheduled' | 'in_progress' | 'conflict' | 'resolved' | 'wontfix';

/** 项目（projects 表） */
export interface Project {
  id: string;
  tenant_id?: number | null;
  slug: string;
  name: string;
  repo_url?: string | null;
  default_branch: string;
  description?: string | null;
  created_by?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  /** 列表页附带的议题总数 */
  issue_total?: number | null;
}

/** 项目详情（含议题状态分组统计） */
export interface ProjectDetail extends Project {
  /** {"total": N, "open": n1, "in_progress": n2, ...} */
  issue_stats: Record<string, number>;
}

/** 项目分页列表响应（最新在上） */
export interface ProjectListResponse {
  items: Project[];
  total: number;
}

/** 创建项目请求（slug 租户内唯一） */
export interface CreateProjectRequest {
  slug: string;
  name: string;
  repo_url?: string | null;
  default_branch?: string;
  description?: string | null;
}

/** 更新项目请求（字段均可选，只更新传入项） */
export interface UpdateProjectRequest {
  slug?: string;
  name?: string;
  repo_url?: string | null;
  default_branch?: string;
  description?: string | null;
}

/** 议题（issues 表） */
export interface Issue {
  id: string;
  tenant_id?: number | null;
  project_id: string;
  title: string;
  body?: string | null;
  /** 入口：user 手动 | meeting 会议候选经确认 */
  source: 'user' | 'meeting' | string;
  source_meeting_id?: string | null;
  status: IssueStatus | string;
  /** 优先级 0-100，默认 50 */
  priority: number;
  assigned_meeting_id?: string | null;
  resolution_artifact_id?: string | null;
  created_by?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

/** 议题分页列表响应（最新在上） */
export interface IssueListResponse {
  items: Issue[];
  total: number;
}

/** 创建议题请求 */
export interface CreateIssueRequest {
  title: string;
  body?: string | null;
  source?: 'user' | 'meeting';
  source_meeting_id?: string | null;
  priority?: number;
}

/** 更新议题请求（传 status 走状态机校验；resolved 必须挂闭环凭证） */
export interface UpdateIssueRequest {
  title?: string;
  body?: string | null;
  priority?: number;
  status?: IssueStatus | string;
  resolution_artifact_id?: string | null;
}

/** 议题合入 main 请求（ADR-017 D11 两阶段确认：false=预览 / true=执行） */
export interface MergeIssueRequest {
  confirm: boolean;
}

/** 合入预览响应（confirm=false：干跑合并，不落状态） */
export interface MergePreviewResponse {
  mode: 'preview';
  issue_id: string;
  project_id: string;
  meeting_id: string;
  /** 合入目标分支（项目 default_branch） */
  branch: string;
  /** 会议仓库未提交变更是否已自动提交（D8：commit 可自动） */
  source_committed: boolean;
  /** 干跑合并是否可无冲突合入 */
  mergeable: boolean;
  /** 变更文件清单（"M\tpath" 格式，≤200 条） */
  changed_files: string[];
  /** 冲突文件清单（mergeable=false 时非空） */
  conflicts: string[];
}

/** 合入执行响应（confirm=true：合并 + push + 议题闭环 + D13 重摄挂钩） */
export interface MergeExecuteResponse {
  mode: 'execute';
  merged: boolean;
  issue_id: string;
  project_id: string;
  meeting_id: string;
  branch: string;
  /** 合并提交短 SHA（12 位） */
  merge_commit_sha: string;
  /** 推送目标（如 origin/main） */
  pushed_to: string;
  changed_files: string[];
  /** 闭环后议题状态（resolved） */
  issue_status: string;
}
