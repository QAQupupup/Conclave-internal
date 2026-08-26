"""FastAPI 权限依赖：require_permission / require_system_admin。"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException, Request

from app.observability.audit import audit
from app.rbac.enforcer import SYSTEM_DOMAIN, get_enforcer

logger = logging.getLogger(__name__)


def _get_auth_user(request: Request) -> dict[str, Any]:
    """从 request.state 获取认证用户信息。"""
    user: dict[str, Any] | None = getattr(request.state, "auth_user", None)
    if not user:
        raise HTTPException(status_code=401, detail="未授权")
    return user


async def _check_permission(
    request: Request,
    obj: str,
    act: str,
) -> dict[str, Any]:
    """核心权限检查逻辑。"""
    user = _get_auth_user(request)

    uid = str(user.get("uid") or user.get("user_id") or "")
    dom = user.get("domain", "")
    system_role = user.get("system_role", user.get("role", ""))

    # 系统级用户在 system domain 自动通过系统域权限检查
    if system_role in ("system_owner", "system_admin", "admin"):
        # system_owner 拥有所有权限（通配）
        if dom == SYSTEM_DOMAIN or obj.startswith("system:"):
            return user
        # system_admin 在非系统域不自动通过，需要显式角色
        if system_role == "system_admin" and dom == SYSTEM_DOMAIN:
            return user

    if not uid or not dom:
        audit("authz.denied", "failure", {"sub": uid, "dom": dom, "obj": obj, "act": act, "reason": "missing_context"})
        raise HTTPException(status_code=403, detail="权限不足")

    enforcer = get_enforcer()
    allowed = await enforcer.enforce(uid, dom, obj, act)
    if not allowed:
        audit(
            "authz.denied",
            "failure",
            {"sub": uid, "dom": dom, "obj": obj, "act": act},
            username=user.get("username", ""),
        )
        raise HTTPException(status_code=403, detail=f"权限不足：{obj}:{act}")

    return user


def require_permission(obj: str, act: str):
    """Casbin 权限检查依赖工厂。

    用法::

        @router.get("/api/tenants/{tid}/members")
        async def list_members(
            tid: int,
            user=Depends(require_permission("team:members", "list"))
        ):
            ...
    """

    async def _dep(request: Request) -> dict[str, Any]:
        return await _check_permission(request, obj, act)

    return _dep


def require_system_admin():
    """要求系统管理员角色（system_owner 或 system_admin/admin）。"""

    async def _dep(request: Request) -> dict[str, Any]:
        user = _get_auth_user(request)
        system_role = user.get("system_role", user.get("role", ""))
        if system_role not in ("system_owner", "system_admin", "admin"):
            audit(
                "authz.denied",
                "failure",
                {"obj": "system", "act": "admin", "reason": "not_system_admin"},
                username=user.get("username", ""),
            )
            raise HTTPException(status_code=403, detail="需要系统管理员权限")
        return user

    return _dep


def get_current_user():
    """获取当前登录用户（仅检查认证，不检查权限）。"""

    async def _dep(request: Request) -> dict[str, Any]:
        return _get_auth_user(request)

    return _dep
