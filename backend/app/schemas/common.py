# 通用响应模型（VO）
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ApiResponse(BaseModel):
    """统一 API 响应格式（code/data/message）"""
    code: int = Field(0, description="业务码：0=成功，非0=失败")
    data: Any | None = Field(None, description="业务数据")
    message: str = Field("success", description="提示信息")


class PaginatedResponse(BaseModel):
    """分页响应 VO"""
    items: list[Any] = Field(default_factory=list)
    total: int = 0
    limit: int = 20
    offset: int = 0
