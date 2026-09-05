"""项目 CRUD（ADR-017 Phase 2）。

项目是仓库绑定的 namespace：议题、会议、产物的聚合根。
隔离键是稳定的 ``projects.id``（ADR-017 D5）；slug 仅作人类可读标识。

多租户：所有查询自动附加 tenant_id 过滤；写入时自动填充当前租户 ID
（对齐 artifact_dao.py 模式，见 docs/pitfalls.md P8）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, select

from app.db.engine import async_session_factory
from app.db.models import ProjectModel
from app.tenants import current_tenant_id
from app.tenants.dao import tenant_filter_expr

# 可更新字段白名单（update_project 只接受这些键，防越权改 id/tenant_id/created_at）
_UPDATABLE_FIELDS = ("slug", "name", "repo_url", "default_branch", "description")


def _iso(v: Any) -> Any:
    """datetime → ISO 字符串（保持与 artifact_dao 相同的返回契约）。"""
    return v.isoformat() if isinstance(v, datetime) else v


def _project_to_dict(row: ProjectModel) -> dict[str, Any]:
    """ORM 行 → dict（时间戳转 ISO 字符串）。"""
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "slug": row.slug,
        "name": row.name,
        "repo_url": row.repo_url,
        "default_branch": row.default_branch,
        "description": row.description,
        "created_by": row.created_by,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


async def create_project(
    slug: str,
    name: str,
    repo_url: str | None = None,
    default_branch: str = "main",
    description: str | None = None,
    created_by: str | None = None,
) -> dict[str, Any]:
    """创建一个项目。自动填充当前 tenant_id。

    Raises:
        IntegrityError: slug 在当前租户内已存在（由路由层转 409）。
    """
    tid = current_tenant_id()
    row = ProjectModel(
        slug=slug,
        name=name,
        repo_url=repo_url,
        default_branch=default_branch,
        description=description,
        created_by=created_by,
    )
    if tid is not None:
        row.tenant_id = tid
    async with async_session_factory() as session:
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return _project_to_dict(row)


async def get_project(project_id: str) -> dict[str, Any] | None:
    """取单个项目（自动租户过滤；跨租户访问返回 None）。"""
    cond = tenant_filter_expr(ProjectModel.tenant_id)
    async with async_session_factory() as session:
        result = await session.execute(select(ProjectModel).where(ProjectModel.id == project_id, cond))
        row = result.scalars().first()
        if row is None:
            return None
        return _project_to_dict(row)


async def get_project_by_slug(slug: str) -> dict[str, Any] | None:
    """按 slug 取项目（自动租户过滤；slug tenant 内唯一）。"""
    cond = tenant_filter_expr(ProjectModel.tenant_id)
    async with async_session_factory() as session:
        result = await session.execute(select(ProjectModel).where(ProjectModel.slug == slug, cond))
        row = result.scalars().first()
        if row is None:
            return None
        return _project_to_dict(row)


async def list_projects(limit: int = 50, offset: int = 0) -> dict[str, Any]:
    """分页查询项目（租户过滤，最新在上——UI 红线）。"""
    cond = tenant_filter_expr(ProjectModel.tenant_id)
    async with async_session_factory() as session:
        total = (await session.execute(select(func.count()).select_from(ProjectModel).where(cond))).scalar_one()
        result = await session.execute(
            select(ProjectModel).where(cond).order_by(ProjectModel.created_at.desc()).limit(limit).offset(offset)
        )
        rows = result.scalars().all()
        return {"items": [_project_to_dict(r) for r in rows], "total": int(total)}


async def update_project(project_id: str, fields: dict[str, Any]) -> dict[str, Any] | None:
    """更新项目字段（白名单过滤 + 租户过滤）。

    Returns:
        更新后的项目 dict；项目不存在/跨租户返回 None。
        fields 全部被白名单过滤掉时原样返回当前行。
    """
    updates = {k: v for k, v in fields.items() if k in _UPDATABLE_FIELDS}
    cond = tenant_filter_expr(ProjectModel.tenant_id)
    async with async_session_factory() as session:
        result = await session.execute(select(ProjectModel).where(ProjectModel.id == project_id, cond))
        row = result.scalars().first()
        if row is None:
            return None
        for key, value in updates.items():
            setattr(row, key, value)
        await session.commit()
        await session.refresh(row)
        return _project_to_dict(row)


async def delete_project(project_id: str) -> bool:
    """删除项目（租户过滤）。

    级联语义由外键承载：issues 级联删除；meetings/artifacts 的
    project_id 置 NULL（历史可追溯）。

    Returns:
        是否实际删除了记录（不存在/跨租户返回 False）。
    """
    cond = tenant_filter_expr(ProjectModel.tenant_id)
    async with async_session_factory() as session:
        result = await session.execute(select(ProjectModel).where(ProjectModel.id == project_id, cond))
        row = result.scalars().first()
        if row is None:
            return False
        await session.delete(row)
        await session.commit()
        return True


async def count_issues(project_id: str) -> dict[str, int]:
    """统计项目下议题数量（总数 + 按状态分组），供项目列表/详情展示。"""
    from app.db.models import IssueModel

    cond = tenant_filter_expr(IssueModel.tenant_id)
    async with async_session_factory() as session:
        rows = (
            await session.execute(
                select(IssueModel.status, func.count())
                .where(IssueModel.project_id == project_id, cond)
                .group_by(IssueModel.status)
            )
        ).all()
    by_status = {status: int(cnt) for status, cnt in rows}
    return {"total": sum(by_status.values()), **by_status}
