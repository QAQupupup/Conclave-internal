# 认证相关 DTO + VO
from __future__ import annotations

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    """登录请求"""
    username: str = Field(..., min_length=1, max_length=64, description="用户名")
    password: str = Field(..., min_length=1, max_length=128, description="密码")


class LoginResponse(BaseModel):
    """登录响应"""
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: dict


class MeResponse(BaseModel):
    """当前用户信息 VO"""
    username: str
    role: str
    display_name: str
    uid: int | None = None
