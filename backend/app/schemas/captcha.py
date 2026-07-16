# 验证码相关 DTO
from __future__ import annotations

from pydantic import BaseModel


class GuardModeRequest(BaseModel):
    """验证码守卫模式切换请求"""
    enabled: bool


class ResolveRequest(BaseModel):
    """验证码解决请求"""
    session_id: str
