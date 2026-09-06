"""产物查询 API（ADR-017 Phase 1，T1.11）。

- GET /artifacts：分页列表（租户过滤，最新在上）
- GET /artifacts/{id}：单条（租户过滤，不存在/跨租户 → 404）
- GET /artifacts/{id}/lineage：上游血缘（沿 source_artifact_ids 递归，深度上限防环）
- POST /artifacts/{id}/push：工作区仓库推送（ADR-017 Phase 3，T3.6，
  confirm=false 返回 diff 摘要，confirm=true 执行推送）

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
    ArtifactPushRequest,
    ArtifactPushResponse,
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


@router.post("/{artifact_id}/push", response_model=ArtifactPushResponse)
async def push_artifact_repo(artifact_id: str, body: ArtifactPushRequest | None = None) -> dict[str, Any]:
    """推送产物所属会议工作区的仓库（ADR-017 Phase 3，T3.6/I13）。

    - ``confirm=false``（默认）：dry-run，返回变更摘要供 UI 展示，不推送
    - ``confirm=true``：先补齐提交（bot 身份）再推送（D8 显式确认红线）

    工作区非 git 仓库/无远端/推送失败 → 409；产物不存在/跨租户 → 404。
    """
    from app.services.git_service import (
        GitPushError,
        GitServiceError,
        commit_workspace,
        diff_summary,
        push_repo,
    )

    artifact = await artifact_dao.get_artifact(artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="产物不存在")
    meeting_id = str(artifact["meeting_id"])
    req = body or ArtifactPushRequest()

    if not req.confirm:
        try:
            diff = await diff_summary(meeting_id)
        except GitServiceError as e:
            raise HTTPException(status_code=409, detail=str(e)) from None
        return {
            "mode": "dry_run",
            "message": "变更摘要已就绪，确认推送请携带 confirm=true",
            "diff": diff,
        }

    try:
        commit_info = await commit_workspace(meeting_id, topic=f"artifact {artifact_id[:8]} push")
        result = await push_repo(meeting_id)
    except GitPushError as e:
        raise HTTPException(status_code=409, detail=str(e)) from None
    except GitServiceError as e:
        raise HTTPException(status_code=409, detail=str(e)) from None
    return {
        "mode": "pushed",
        "message": f"已推送到 {result['pushed_to']}",
        "pushed_to": result["pushed_to"],
        "commit_sha": commit_info.get("commit_sha"),
    }
