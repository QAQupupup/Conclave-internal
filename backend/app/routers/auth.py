"""
认证路由：登录、获取当前用户信息
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.auth import authenticate_user, create_access_token, get_user_by_username

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["认证"])


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64, description="用户名")
    password: str = Field(..., min_length=1, max_length=128, description="密码")


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: dict


class MeResponse(BaseModel):
    username: str
    role: str
    display_name: str
    uid: int | None = None


@router.post("/login", response_model=LoginResponse)
async def login(req: LoginRequest, request: Request):
    """用户登录，返回 JWT access token"""
    from app.auth import JWT_EXPIRE_SECONDS
    import asyncio
    from app.middleware import record_auth_failure, reset_auth_failures, client_ip

    client_ip_str = client_ip(request)

    # 在线程池中执行密码验证（PBKDF2 计算较慢，避免阻塞事件循环）
    loop = asyncio.get_event_loop()
    user = await loop.run_in_executor(None, authenticate_user, req.username, req.password)

    if not user:
        # 记录失败（供限速使用）
        record_auth_failure(client_ip_str)
        logger.warning("Login failed for username=%s from %s", req.username, client_ip_str)
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    token = create_access_token(user)
    reset_auth_failures(client_ip_str)
    logger.info("User logged in: username=%s role=%s from %s",
                user["username"], user.get("role"), client_ip_str)

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
    # 从 request.state 中获取认证信息（由中间件注入）
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
