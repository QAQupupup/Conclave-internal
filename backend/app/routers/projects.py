"""项目与议题池 API（ADR-017 Phase 2）。

项目端点（本文件，前缀 /api/projects）：
- POST /api/projects：创建项目（slug 租户内唯一，冲突 → 409）
- GET /api/projects：分页列表（租户过滤，最新在上，附议题总数）
- GET /api/projects/{id}：详情（含议题状态分组统计）
- PATCH /api/projects/{id}：更新（白名单字段）
- DELETE /api/projects/{id}：删除（议题级联删；会议/产物关联置 NULL）
- GET /api/projects/{id}/issues：项目议题列表
- POST /api/projects/{id}/issues：入池（source=user 手动；source=meeting
  会议候选经人工确认，须挂 source_meeting_id——ADR-017 D7）

议题平铺端点见 routers/issues.py（前缀 /api/issues）。

路径挂 /api 前缀的原因：裸路径 /projects 同时是前端 SPA 路由，
与 admin（/api/admin）同范式，避免 nginx/vite 路由冲突。

多租户隔离由 DAO 层 tenant_filter_expr 强制（docs/pitfalls.md P8）；
跨租户访问统一返回 404，不泄露资源存在性。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy.exc import IntegrityError

from app.dao import issue_dao, project_dao
from app.schemas.issue import CreateIssueRequest, IssueListResponse, IssueResponse
from app.schemas.project import (
    CreateProjectRequest,
    ProjectDetailResponse,
    ProjectListResponse,
    ProjectResponse,
    UpdateProjectRequest,
)

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.post("", response_model=ProjectResponse, status_code=201)
async def create_project_api(req: CreateProjectRequest, request: Request) -> dict[str, Any]:
    """创建项目（slug 租户内唯一）。"""
    from app.auth_guard import get_current_user

    # 应用层预检：系统租户模式下 tenant_id 为 NULL，PG 唯一约束
    # (tenant_id, slug) 对 NULL 不生效，需预检兜底（租户模式下与约束等价）
    if await project_dao.get_project_by_slug(req.slug) is not None:
        raise HTTPException(status_code=409, detail=f"项目标识已存在: {req.slug}")
    _uid, username, _role = get_current_user(request)
    try:
        return await project_dao.create_project(
            slug=req.slug,
            name=req.name,
            repo_url=req.repo_url,
            default_branch=req.default_branch,
            description=req.description,
            created_by=username,
        )
    except IntegrityError:
        raise HTTPException(status_code=409, detail=f"项目标识已存在: {req.slug}") from None


@router.get("", response_model=ProjectListResponse)
async def list_projects_api(
    limit: int = Query(default=50, ge=1, le=200, description="每页数量"),
    offset: int = Query(default=0, ge=0, description="偏移量"),
) -> dict[str, Any]:
    """分页查询项目（租户过滤，最新在上，附议题总数）。"""
    data = await project_dao.list_projects(limit=limit, offset=offset)
    counts = await issue_dao.bulk_get_by_project([p["id"] for p in data["items"]])
    for project in data["items"]:
        project["issue_total"] = counts.get(project["id"], 0)
    return data


@router.get("/{project_id}", response_model=ProjectDetailResponse)
async def get_project_detail(project_id: str) -> dict[str, Any]:
    """项目详情（不存在/跨租户 → 404；含议题状态分组统计）。"""
    project = await project_dao.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    project["issue_stats"] = await project_dao.count_issues(project_id)
    return project


@router.patch("/{project_id}", response_model=ProjectResponse)
async def update_project_api(project_id: str, req: UpdateProjectRequest) -> dict[str, Any]:
    """更新项目（白名单字段；slug 冲突 → 409；不存在/跨租户 → 404）。"""
    fields = req.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(status_code=400, detail="未提供任何待更新字段")
    # 应用层预检（同 create：系统租户下 NULL tenant_id 不触发唯一约束）
    new_slug = fields.get("slug")
    if new_slug is not None:
        existing = await project_dao.get_project_by_slug(new_slug)
        if existing is not None and existing["id"] != project_id:
            raise HTTPException(status_code=409, detail=f"项目标识已存在: {new_slug}")
    try:
        updated = await project_dao.update_project(project_id, fields)
    except IntegrityError:
        raise HTTPException(status_code=409, detail=f"项目标识已存在: {fields.get('slug')}") from None
    if updated is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    return updated


@router.delete("/{project_id}")
async def delete_project_api(project_id: str) -> dict[str, Any]:
    """删除项目（议题级联删除；会议/产物的 project_id 置 NULL）。"""
    deleted = await project_dao.delete_project(project_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="项目不存在")
    return {"deleted": project_id}


@router.get("/{project_id}/issues", response_model=IssueListResponse)
async def list_project_issues(
    project_id: str,
    status: str | None = Query(default=None, max_length=20, description="按状态过滤"),
    limit: int = Query(default=50, ge=1, le=200, description="每页数量"),
    offset: int = Query(default=0, ge=0, description="偏移量"),
) -> dict[str, Any]:
    """项目议题列表（租户过滤，最新在上）。"""
    project = await project_dao.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    return await issue_dao.list_issues(project_id=project_id, status=status, limit=limit, offset=offset)


@router.post("/{project_id}/issues", response_model=IssueResponse, status_code=201)
async def create_project_issue(project_id: str, req: CreateIssueRequest, request: Request) -> dict[str, Any]:
    """议题入池（ADR-017 D7：source=meeting 为会议候选经人工确认入口）。"""
    from app.auth_guard import get_current_user

    project = await project_dao.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    if req.source == "meeting" and not req.source_meeting_id:
        raise HTTPException(status_code=400, detail="会议来源议题必须挂 source_meeting_id")
    _uid, username, _role = get_current_user(request)
    return await issue_dao.create_issue(
        project_id=project_id,
        title=req.title,
        body=req.body,
        source=req.source,
        source_meeting_id=req.source_meeting_id,
        priority=req.priority,
        created_by=username,
    )
