"""审计日志查询 API

提供审计日志查询、统计接口，供管理员查看操作记录、安全事件和系统异常。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

router = APIRouter(prefix="/audit", tags=["审计日志"])


@router.get("/logs")
async def query_audit_logs(
    request: Request,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    action: str | None = None,
    username: str | None = None,
    meeting_id: str | None = None,
    category: str | None = None,
    status: str | None = None,
    since: str | None = None,
    until: str | None = None,
) -> dict[str, Any]:
    """查询审计日志（需要管理员权限）"""
    auth_user = getattr(request.state, "auth_user", None)
    if not auth_user or auth_user.get("role") != "admin":
        # 非管理员只能查看自己的操作
        if auth_user:
            username = auth_user.get("username")
        else:
            raise HTTPException(status_code=403, detail="需要管理员权限")

    from app.observability.audit import get_audit_logger
    logger = get_audit_logger()
    logs = logger.query(
        limit=limit, offset=offset, action=action, username=username,
        meeting_id=meeting_id, category=category, status=status,
        since=since, until=until,
    )
    return {"logs": logs, "limit": limit, "offset": offset, "count": len(logs)}


@router.get("/stats")
async def audit_stats(
    request: Request,
    since_minutes: int = Query(60, ge=1, le=10080),
) -> dict[str, Any]:
    """审计统计信息（管理员）"""
    auth_user = getattr(request.state, "auth_user", None)
    if not auth_user or auth_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")

    from app.observability.audit import get_audit_logger
    logger = get_audit_logger()
    return logger.stats(since_minutes=since_minutes)


@router.get("/security-events")
async def security_events(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    """查询安全事件（管理员）：未授权访问、限流、SSRF 阻断等"""
    auth_user = getattr(request.state, "auth_user", None)
    if not auth_user or auth_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")

    from app.observability.audit import get_audit_logger
    logger = get_audit_logger()
    # 查询安全类别的事件
    events = logger.query(limit=limit, category="安全")
    # 也包含 system.error
    errors = logger.query(limit=limit, category="系统", status="error")
    return {
        "security_events": events,
        "system_errors": errors,
        "total": len(events) + len(errors),
    }
