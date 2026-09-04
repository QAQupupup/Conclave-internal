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
