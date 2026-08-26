"""Team（组织/工作空间）REST API。

端点：
- GET    /api/teams                  当前用户的 Team 列表
- POST   /api/teams                  创建 Team
- GET    /api/teams/{tid}            Team 详情
- PATCH  /api/teams/{tid}            更新 Team 信息
- DELETE /api/teams/{tid}            删除 Team
- POST   /api/teams/{tid}/transfer   转让所有权

成员管理：
- GET    /api/teams/{tid}/members            成员列表（分页+搜索）
- POST   /api/teams/{tid}/members            添加成员
- DELETE /api/teams/{tid}/members/{uid}      移除成员
- PATCH  /api/teams/{tid}/members/{uid}      修改成员角色
- POST   /api/teams/{tid}/members/{uid}/ban      封禁成员
- POST   /api/teams/{tid}/members/{uid}/unban    解封成员

用户搜索：
- GET    /api/users/search          用户搜索（autocomplete）
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from app.rbac.enforcer import SYSTEM_DOMAIN
from app.services import team_service

router = APIRouter(prefix="/api", tags=["teams"])


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


def _get_auth(request: Request) -> dict[str, Any]:
    auth_user: dict[str, Any] | None = getattr(request.state, "auth_user", None)
    if not auth_user:
        raise HTTPException(status_code=401, detail="未登录")
    return auth_user


def _get_uid_int(auth_user: dict[str, Any]) -> int:
    uid = auth_user.get("uid_int")
    if uid is None:
        uid_str = str(auth_user.get("uid", 0))
        try:
            uid = int(uid_str)
        except (ValueError, TypeError):
            raise HTTPException(status_code=401, detail="无效用户") from None
    return int(uid)


def _get_current_role(auth_user: dict[str, Any], tid: int) -> str:
    """获取当前用户在指定 Team 中的角色。"""
    roles = auth_user.get("roles", ())
    # auth_user 中的 roles 是当前 tenant 下的角色
    # 系统管理员在 system domain，但可能不在该 team
    if auth_user.get("domain") == SYSTEM_DOMAIN:
        sys_role = auth_user.get("system_role", "")
        if sys_role == "system_owner":
            return "owner"  # system_owner 在任何 team 视为 owner
        if sys_role in ("system_admin", "admin"):
            return "maintainer"  # system_admin 在 team 中视为 maintainer
    if roles:
        return str(roles[0])
    return ""


def _handle_service_error(e: team_service.TeamServiceError) -> None:
    """将 service 异常转换为 HTTP 异常。"""
    if isinstance(e, team_service.PermissionDeniedError):
        raise HTTPException(status_code=403, detail=e.message)
    if isinstance(e, team_service.NotFoundError):
        raise HTTPException(status_code=404, detail=e.message)
    if isinstance(e, team_service.ValidationError):
        raise HTTPException(status_code=400, detail=e.message)
    if isinstance(e, team_service.ConflictError):
        raise HTTPException(status_code=409, detail=e.message)
    raise HTTPException(status_code=500, detail=e.message)


# ---------------------------------------------------------------------------
# Team CRUD
# ---------------------------------------------------------------------------


@router.get("/teams")
async def list_my_teams(request: Request) -> dict[str, Any]:
    """获取当前用户所在的所有 Team。"""
    auth = _get_auth(request)
    uid = _get_uid_int(auth)
    teams = await team_service.list_user_teams(uid)
    return {"items": teams}


@router.post("/teams")
async def create_team(request: Request, body: dict[str, Any]) -> dict[str, Any]:
    """创建新 Team。登录用户即可创建，创建者自动成为 owner。"""
    auth = _get_auth(request)
    uid = _get_uid_int(auth)

    name = (body.get("name") or "").strip()
    slug = (body.get("slug") or "").strip() or None
    description = (body.get("description") or "").strip()
    settings = body.get("settings")

    try:
        team = await team_service.create_team(
            name=name,
            owner_id=uid,
            slug=slug,
            description=description,
            settings=settings if isinstance(settings, dict) else None,
        )
    except team_service.TeamServiceError as e:
        _handle_service_error(e)

    return team


@router.get("/teams/{tid}")
async def get_team(tid: int, request: Request) -> dict[str, Any]:
    """获取 Team 详情。需要是 Team 成员。"""
    auth = _get_auth(request)
    _get_uid_int(auth)

    team = await team_service.get_team(tid)
    if not team:
        raise HTTPException(status_code=404, detail="Team 不存在")

    # 检查是否是成员（非系统管理员需验证）
    role = _get_current_role(auth, tid)
    if auth.get("domain") != SYSTEM_DOMAIN and not role:
        raise HTTPException(status_code=403, detail="无权访问该 Team")

    team["my_role"] = role
    return team


@router.patch("/teams/{tid}")
async def update_team(tid: int, request: Request, body: dict[str, Any]) -> dict[str, Any]:
    """更新 Team 信息。需要 owner 或 maintainer。"""
    auth = _get_auth(request)
    uid = _get_uid_int(auth)
    role = _get_current_role(auth, tid)

    try:
        team = await team_service.update_team(
            team_id=tid,
            operator_id=uid,
            operator_role=role,
            name=body.get("name"),
            description=body.get("description"),
            settings_patch=body.get("settings") if isinstance(body.get("settings"), dict) else None,
        )
    except team_service.TeamServiceError as e:
        _handle_service_error(e)

    return team


@router.delete("/teams/{tid}")
async def delete_team(tid: int, request: Request) -> dict[str, Any]:
    """删除 Team。仅 owner。"""
    auth = _get_auth(request)
    uid = _get_uid_int(auth)
    role = _get_current_role(auth, tid)

    try:
        await team_service.delete_team(tid, uid, role)
    except team_service.TeamServiceError as e:
        _handle_service_error(e)

    return {"deleted": True}


@router.post("/teams/{tid}/transfer")
async def transfer_ownership(tid: int, request: Request, body: dict[str, Any]) -> dict[str, Any]:
    """转让 Team 所有权。仅当前 owner。"""
    auth = _get_auth(request)
    uid = _get_uid_int(auth)
    target_uid = body.get("target_user_id")
    if not target_uid:
        raise HTTPException(status_code=400, detail="需要 target_user_id")
    try:
        target_uid = int(target_uid)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="无效的 target_user_id") from None

    try:
        await team_service.transfer_ownership(tid, uid, target_uid)
    except team_service.TeamServiceError as e:
        _handle_service_error(e)

    return {"transferred": True}


# ---------------------------------------------------------------------------
# 成员管理
# ---------------------------------------------------------------------------


@router.get("/teams/{tid}/members")
async def list_members(
    tid: int,
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    search: str = Query(""),
    role: str | None = Query(None),
    include_banned: bool = Query(False),
) -> dict[str, Any]:
    """分页获取 Team 成员列表。成员可访问。"""
    auth = _get_auth(request)
    my_role = _get_current_role(auth, tid)

    # 系统管理员或 Team 成员可查看
    if auth.get("domain") != SYSTEM_DOMAIN and not my_role:
        raise HTTPException(status_code=403, detail="无权查看该 Team 成员")

    try:
        result = await team_service.list_members(
            team_id=tid,
            page=page,
            page_size=page_size,
            search=search.strip(),
            role_filter=role,
            include_banned=include_banned,
        )
    except team_service.TeamServiceError as e:
        _handle_service_error(e)

    result["my_role"] = my_role
    return result


@router.post("/teams/{tid}/members")
async def add_member(tid: int, request: Request, body: dict[str, Any]) -> dict[str, Any]:
    """添加/邀请成员到 Team。需要 maintainer 以上。"""
    auth = _get_auth(request)
    uid = _get_uid_int(auth)
    role = _get_current_role(auth, tid)

    username = (body.get("username") or "").strip()
    new_role = (body.get("role") or "member").strip().lower()
    if not username:
        raise HTTPException(status_code=400, detail="需要 username")

    try:
        result = await team_service.add_member(
            team_id=tid,
            operator_id=uid,
            operator_role=role,
            username=username,
            role=new_role,
        )
    except team_service.TeamServiceError as e:
        _handle_service_error(e)

    return result


@router.delete("/teams/{tid}/members/{target_uid}")
async def remove_member(tid: int, target_uid: int, request: Request) -> dict[str, Any]:
    """移除成员。需要足够权限。"""
    auth = _get_auth(request)
    uid = _get_uid_int(auth)
    role = _get_current_role(auth, tid)

    try:
        await team_service.remove_member(
            team_id=tid,
            operator_id=uid,
            operator_role=role,
            target_user_id=target_uid,
        )
    except team_service.TeamServiceError as e:
        _handle_service_error(e)

    return {"removed": True}


@router.patch("/teams/{tid}/members/{target_uid}")
async def change_member_role(
    tid: int,
    target_uid: int,
    request: Request,
    body: dict[str, Any],
) -> dict[str, Any]:
    """修改成员角色。需要足够权限。"""
    auth = _get_auth(request)
    uid = _get_uid_int(auth)
    role = _get_current_role(auth, tid)

    new_role = (body.get("role") or "").strip().lower()
    if not new_role:
        raise HTTPException(status_code=400, detail="需要 role")

    try:
        result = await team_service.change_member_role(
            team_id=tid,
            operator_id=uid,
            operator_role=role,
            target_user_id=target_uid,
            new_role=new_role,
        )
    except team_service.TeamServiceError as e:
        _handle_service_error(e)

    return result


@router.post("/teams/{tid}/members/{target_uid}/ban")
async def ban_member(tid: int, target_uid: int, request: Request, body: dict[str, Any] | None = None) -> dict[str, Any]:
    """封禁成员。需要 maintainer 以上。"""
    auth = _get_auth(request)
    uid = _get_uid_int(auth)
    role = _get_current_role(auth, tid)
    reason = (body or {}).get("reason", "")

    try:
        await team_service.ban_member(
            team_id=tid,
            operator_id=uid,
            operator_role=role,
            target_user_id=target_uid,
            reason=reason,
        )
    except team_service.TeamServiceError as e:
        _handle_service_error(e)

    return {"banned": True}


@router.post("/teams/{tid}/members/{target_uid}/unban")
async def unban_member(
    tid: int, target_uid: int, request: Request, body: dict[str, Any] | None = None
) -> dict[str, Any]:
    """解封成员。需要 maintainer 以上。"""
    auth = _get_auth(request)
    uid = _get_uid_int(auth)
    role = _get_current_role(auth, tid)
    new_role = (body or {}).get("role", "member")

    try:
        await team_service.unban_member(
            team_id=tid,
            operator_id=uid,
            operator_role=role,
            target_user_id=target_uid,
            new_role=new_role,
        )
    except team_service.TeamServiceError as e:
        _handle_service_error(e)

    return {"unbanned": True}


# ---------------------------------------------------------------------------
# 用户搜索（autocomplete）
# ---------------------------------------------------------------------------


@router.get("/users/search")
async def search_users(
    request: Request,
    q: str = Query("", min_length=1),
    team_id: int | None = Query(None),
    exclude_team: bool = Query(True),
    limit: int = Query(10, ge=1, le=50),
) -> dict[str, Any]:
    """搜索用户（用于邀请成员等场景）。登录即可使用。"""
    _get_auth(request)
    users = await team_service.search_users(
        keyword=q,
        team_id=team_id,
        exclude_team_members=exclude_team,
        limit=limit,
    )
    return {"items": users}
