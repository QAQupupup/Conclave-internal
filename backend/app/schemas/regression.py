# 回归测试相关 DTO + VO
from __future__ import annotations

from pydantic import BaseModel, Field


class BaselineRequest(BaseModel):
    """创建基线请求"""
    meeting_id: str = Field(..., description="会议 ID")


class BaselineSummary(BaseModel):
    """基线摘要（列表项）"""
    baseline_id: str
    created_at: str
    meeting_id: str
    topic: str
    stages_completed: int
