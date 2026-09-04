"""产物查询 API（ADR-017 Phase 1，T1.11）。

- GET /artifacts：分页列表（租户过滤，最新在上）
- GET /artifacts/{id}：单条（租户过滤，不存在/跨租户 → 404）
- GET /artifacts/{id}/lineage：上游血缘（沿 source_artifact_ids 递归，深度上限防环）

多租户隔离由 DAO 层 tenant_filter_expr 强制（docs/pitfalls.md P8）；
跨租户访问统一返回 404，不泄露产物存在性。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.dao import artifact_dao
from app.schemas.artifact import (
    ArtifactLineageResponse,
    ArtifactListResponse,
    ArtifactResponse,
)
from app.services.artifact_service import get_lineage

router = APIRouter(prefix="/artifacts", tags=["artifacts"])


@router.get("", response_model=ArtifactListResponse)
async def list_artifacts_api(
    meeting_id: str | None = Query(default=None, max_length=36, description="按会议 ID 过滤"),
    type: str | None = Query(default=None, max_length=50, description="按产物类型过滤"),
    limit: int = Query(default=50, ge=1, le=200, description="每页数量"),
    offset: int = Query(default=0, ge=0, description="偏移量"),
) -> dict[str, Any]:
    """分页查询产物（租户过滤，最新在上）。"""
    return await artifact_dao.list_artifacts(meeting_id=meeting_id, artifact_type=type, limit=limit, offset=offset)


@router.get("/{artifact_id}", response_model=ArtifactResponse)
async def get_artifact_detail(artifact_id: str) -> dict[str, Any]:
    """取单条产物（不存在/跨租户 → 404）。"""
    artifact = await artifact_dao.get_artifact(artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="产物不存在")
    return artifact


@router.get("/{artifact_id}/lineage", response_model=ArtifactLineageResponse)
async def get_artifact_lineage(artifact_id: str) -> dict[str, Any]:
    """查询产物上游血缘（深度上限防环，跨租户上游静默跳过）。"""
    lineage = await get_lineage(artifact_id)
    if lineage is None:
        raise HTTPException(status_code=404, detail="产物不存在")
    return lineage
