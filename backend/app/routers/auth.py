"""
认证路由：登录、获取当前用户信息
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from app.auth import JWT_EXPIRE_SECONDS, authenticate_user, create_access_token, get_user_by_username
from app.context import set_user_id, set_user_role, set_username
from app.middleware import client_ip, record_auth_failure, reset_auth_failures
from app.observability.audit import audit
from app.schemas.auth import LoginRequest, LoginResponse, MeResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["认证"])


async def _build_user_info(user: dict[str, Any]) -> dict[str, Any]:
    """构建完整的用户信息响应，匹配前端 UserInfo 接口。

    [P0-2 修复] 前端 UserInfo 期望 id/tenant_id/tenants 字段，
    原代码仅返回 uid（前端无法映射到 id），且缺少 tenant_id/tenants。
    """
    user_id = user.get("id")
    tenant_id = user.get("tenant_id")

    # 获取用户所属租户列表
    tenants_list: list[dict[str, Any]] = []
    if user_id:
        try:
            from app.tenants.service import list_user_tenants

            tenant_infos = await list_user_tenants(user_id)
            tenants_list = [
                {"id": str(t.id), "name": t.name, "role": t.role or ("owner" if t.owner_id == user_id else "member")}
                for t in tenant_infos
            ]
        except Exception:
            # 租户系统未初始化时降级为空列表
            logger.debug("Could not fetch user tenants for user_id=%s", user_id)

    # 如果无租户但用户有 tenant_id，至少返回当前租户
    if not tenants_list and tenant_id:
        tenants_list = [{"id": str(tenant_id), "name": "默认组织", "role": user.get("role", "member")}]

    return {
        "id": str(user_id) if user_id else None,
        "uid": user_id,  # 向后兼容
        "username": user["username"],
        "display_name": user.get("display_name") or user["username"],
        "role": user.get("role", "user"),
        "tenant_id": str(tenant_id) if tenant_id else "",
        "tenants": tenants_list,
        "email": user.get("email"),
        "avatar_url": user.get("avatar_url"),
    }


@router.post("/login", response_model=LoginResponse)
async def login(req: LoginRequest, request: Request):
    """用户登录，返回 JWT access token"""
    client_ip_str = client_ip(request)

    user = await authenticate_user(req.username, req.password)

    if not user:
        record_auth_failure(client_ip_str)
        logger.warning("Login failed for username=%s from %s", req.username, client_ip_str)
        # 审计：登录失败
        audit(
            "auth.login_failed",
            "failure",
            {
                "username_attempt": req.username,
                "reason": "invalid_credentials",
            },
            ip=client_ip_str,
        )
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    token = create_access_token(user)
    reset_auth_failures(client_ip_str)
    logger.info("User logged in: username=%s role=%s from %s", user["username"], user.get("role"), client_ip_str)

    # 设置用户上下文（用于后续请求的日志追踪）
    set_user_id(str(user.get("id", "")))
    set_username(user["username"])
    set_user_role(user.get("role", "user"))

    # 审计：登录成功
    audit(
        "auth.login",
        "success",
        {
            "role": user.get("role", "user"),
            "display_name": user.get("display_name", user["username"]),
        },
        ip=client_ip_str,
        username=user["username"],
        user_id=str(user.get("id", "")),
    )

    # [P0-2 修复] 返回完整用户信息（id/tenant_id/tenants），匹配前端 UserInfo 接口
    user_info = await _build_user_info(user)
    return LoginResponse(
        access_token=token,
        expires_in=JWT_EXPIRE_SECONDS,
        user=user_info,
    )


@router.get("/me", response_model=MeResponse)
async def me(request: Request):
    """获取当前登录用户信息"""
    auth_user = getattr(request.state, "auth_user", None)
    if not auth_user:
        raise HTTPException(status_code=401, detail="未登录")
    username = auth_user.get("username")
    user = get_user_by_username(username)
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在")
    # [P0-2 修复] 返回完整用户信息，匹配前端 UserInfo 接口
    user_info = await _build_user_info(user)
    return MeResponse(**user_info)
