# 认证相关 DTO + VO
from __future__ import annotations

from typing import Any

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
    user: dict[str, Any]


class MeResponse(BaseModel):
    """当前用户信息 VO

    [P0-2 修复] 补全前端 UserInfo 接口所需的全部字段：
    id/tenant_id/tenants/email/avatar_url。uid 保留向后兼容。
    """

    id: str | None = None
    uid: int | None = None  # 向后兼容
    username: str
    role: str
    display_name: str
    tenant_id: str = ""
    tenants: list[dict[str, Any]] = Field(default_factory=list)
    email: str | None = None
    avatar_url: str | None = None
