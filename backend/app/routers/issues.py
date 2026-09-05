"""议题平铺端点（ADR-017 Phase 2）。

- GET /issues/{id}：单条（租户过滤，不存在/跨租户 → 404）
- PATCH /issues/{id}：更新字段 / 状态流转（状态机校验，非法流转 → 409）
- DELETE /issues/{id}：删除（会议侧 issue_id 外键 SET NULL）

创建议题走项目嵌套端点 POST /projects/{id}/issues（routers/projects.py）。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from app.dao import issue_dao
from app.schemas.issue import IssueResponse, UpdateIssueRequest
from app.services.issue_service import IssueTransitionError, transition_issue

router = APIRouter(prefix="/issues", tags=["issues"])


@router.get("/{issue_id}", response_model=IssueResponse)
async def get_issue_api(issue_id: str) -> dict[str, Any]:
    """取单条议题（不存在/跨租户 → 404）。"""
    issue = await issue_dao.get_issue(issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail="议题不存在")
    return issue


@router.patch("/{issue_id}", response_model=IssueResponse)
async def update_issue_api(issue_id: str, req: UpdateIssueRequest) -> dict[str, Any]:
    """更新议题：普通字段直更；status 走状态机校验。

    - 流转到 resolved 必须提供闭环凭证（本请求携带或议题已挂），否则 409；
    - 非法流转 / 议题不存在 / 并发竞争失败 → 409 / 404。
    """
    fields = req.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(status_code=400, detail="未提供任何待更新字段")

    target_status = fields.pop("status", None)
    resolution_artifact_id = fields.pop("resolution_artifact_id", None)

    updated: dict[str, Any] | None = None
    if fields:
        updated = await issue_dao.update_issue_fields(issue_id, fields)
        if updated is None:
            raise HTTPException(status_code=404, detail="议题不存在")

    if target_status is not None:
        try:
            updated = await transition_issue(issue_id, target_status, resolution_artifact_id)
        except IssueTransitionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    elif resolution_artifact_id is not None:
        # 不流转状态、仅预挂闭环凭证（为后续 resolved 做准备）
        updated = await issue_dao.update_issue_fields(issue_id, {"resolution_artifact_id": resolution_artifact_id})
        if updated is None:
            raise HTTPException(status_code=404, detail="议题不存在")

    if updated is None:
        # 只有 status/凭证之外的空更新场景不会出现（上方已拦空 fields）
        issue = await issue_dao.get_issue(issue_id)
        if issue is None:
            raise HTTPException(status_code=404, detail="议题不存在")
        updated = issue
    return updated


@router.delete("/{issue_id}")
async def delete_issue_api(issue_id: str) -> dict[str, Any]:
    """删除议题（会议侧关联外键 SET NULL，历史会议保留）。"""
    deleted = await issue_dao.delete_issue(issue_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="议题不存在")
    return {"deleted": issue_id}
