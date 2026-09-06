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
export type IssueStatus = 'open' | 'scheduled' | 'in_progress' | 'resolved' | 'wontfix';

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
