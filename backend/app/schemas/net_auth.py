# 网络鉴权相关 DTO + VO
from __future__ import annotations

from pydantic import BaseModel


class ReviewRequest(BaseModel):
    """审批请求"""

    action: str  # approved / denied
    comment: str = ""


class AuthRequestSummary(BaseModel):
    """鉴权请求摘要 VO"""

    id: str
    meeting_id: str
    stage: str
    requested_level: str
    detected_level: str
    failure_reason: str
