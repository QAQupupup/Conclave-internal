"""
认证路由：登录、获取当前用户信息
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request

from app.auth import JWT_EXPIRE_SECONDS, authenticate_user, create_access_token, get_user_by_username
from app.context import set_user_id, set_user_role, set_username
from app.middleware import client_ip, record_auth_failure, reset_auth_failures
from app.observability.audit import audit
from app.schemas.auth import LoginRequest, LoginResponse, MeResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["认证"])


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

    return LoginResponse(
        access_token=token,
        expires_in=JWT_EXPIRE_SECONDS,
        user={
            "username": user["username"],
            "role": user.get("role", "user"),
            "display_name": user.get("display_name", user["username"]),
            "uid": user.get("id"),
        },
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
    return MeResponse(
        username=user["username"],
        role=user.get("role", "user"),
        display_name=user.get("display_name", user["username"]),
        uid=user.get("id"),
    )
