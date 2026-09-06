# 产物相关 DTO + VO（ADR-017 Phase 1）
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ArtifactResponse(BaseModel):
    """单条产物"""

    id: str
    tenant_id: int | None = None
    meeting_id: str
    project_id: str | None = None
    type: str
    title: str | None = None
    summary: str | None = None
    content: dict[str, Any] | None = None
    content_ref: str | None = None
    version: int
    parent_id: str | None = None
    source_artifact_ids: list[str] = Field(default_factory=list)
    created_by: str | None = None
    created_at: str | None = None


class ArtifactListResponse(BaseModel):
    """产物分页列表（最新在上）"""

    items: list[ArtifactResponse]
    total: int


class LineageNode(BaseModel):
    """血缘图节点（depth=0 为查询起点）"""

    id: str
    type: str
    title: str | None = None
    version: int | None = None
    meeting_id: str | None = None
    created_at: str | None = None
    depth: int


class LineageEdge(BaseModel):
    """血缘图边：child 消费 parent（下游产物 → 上游产物）"""

    child_id: str
    parent_id: str


class ArtifactLineageResponse(BaseModel):
    """产物上游血缘（沿 source_artifact_ids 递归，深度有上限防环）"""

    root_id: str
    depth_limit: int
    truncated: bool = Field(description="是否因深度上限截断")
    nodes: list[LineageNode]
    edges: list[LineageEdge]


class ArtifactPushRequest(BaseModel):
    """产物推送请求（ADR-017 Phase 3，D8/I13：进入共享空间的 git 操作需显式确认）"""

    confirm: bool = Field(default=False, description="false=dry-run 返回 diff 摘要；true=执行 push")


class ArtifactPushDiff(BaseModel):
    """push dry-run 变更摘要"""

    is_git_repo: bool = False
    changed_files: list[str] = Field(default_factory=list, description="未提交变更（≤100 条）")
    unpushed_commits: int = 0
    remote: str | None = None


class ArtifactPushResponse(BaseModel):
    """产物推送响应：dry_run 返回摘要供 UI 展示；pushed 返回推送结果"""

    mode: str = Field(description="dry_run | pushed")
    message: str
    diff: ArtifactPushDiff | None = None
    pushed_to: str | None = None
    commit_sha: str | None = None
