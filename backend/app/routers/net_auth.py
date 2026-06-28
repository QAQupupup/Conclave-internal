# 网络授权审批 API
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.events import bus, make_event
from app.net_auth import (
    create_auth_request,
    expire_pending_requests,
    get_auth_request,
    get_pending_for_meeting,
    list_auth_requests,
    review_auth_request,
)

router = APIRouter(prefix="/net-auth", tags=["net-auth"])

# ---- 配置 ----

# 自动通过：CONCLAVE_NET_AUTH_AUTO=1 时所有申请自动通过
AUTO_APPROVE = os.environ.get("CONCLAVE_NET_AUTH_AUTO", "") == "1"

# 申请超时秒数：超时后降级为 expired
AUTH_TIMEOUT_SECONDS = int(os.environ.get("CONCLAVE_NET_AUTH_TIMEOUT", "120"))


# ---- 请求/响应模型 ----


class ReviewRequest(BaseModel):
    action: str  # approved / denied
    comment: str = ""


class AuthRequestSummary(BaseModel):
    id: str
    meeting_id: str
    stage: str
    requested_level: str
    detected_level: str
    failure_reason: str
    status: str
    created_at: str
    expires_at: str
    reviewed_at: str | None = None
    review_comment: str | None = None


# ---- 端点 ----


@router.get("/requests")
async def list_requests(
    meeting_id: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """列出网络授权申请单，可按会议和状态过滤"""
    return list_auth_requests(meeting_id=meeting_id, status=status)


@router.get("/requests/{request_id}")
async def get_request(request_id: str) -> dict[str, Any]:
    """取单条申请详情"""
    r = get_auth_request(request_id)
    if not r:
        raise HTTPException(404, "申请单不存在")
    return r


@router.get("/pending/{meeting_id}")
async def get_pending(meeting_id: str) -> list[dict[str, Any]]:
    """取某会议的 pending 申请"""
    return get_pending_for_meeting(meeting_id)


@router.post("/requests/{request_id}/review")
async def review_request(
    request_id: str, body: ReviewRequest
) -> dict[str, Any]:
    """批复申请单

    action: approved / denied
    comment: 可选批复意见
    """
    if body.action not in ("approved", "denied"):
        raise HTTPException(400, "action 必须是 approved 或 denied")

    result = review_auth_request(request_id, body.action, body.comment)
    if not result:
        raise HTTPException(404, "申请单不存在或已批复")

    # 发布批复事件，通知等待中的沙箱
    meeting_id = result["meeting_id"]
    await bus.publish(make_event(
        "net_auth.reviewed",
        meeting_id,
        {
            "request_id": request_id,
            "action": body.action,
            "comment": body.comment,
            "approved_level": result["requested_level"] if body.action == "approved" else None,
        },
    ))

    return {"status": "ok", "request_id": request_id, "action": body.action}


@router.post("/expire")
async def expire_overdue() -> dict[str, Any]:
    """手动触发过期检查（也可由后台定时调用）

    将超时未批复的申请标记为 expired。
    """
    expired = expire_pending_requests()
    return {"expired_count": len(expired), "expired_ids": [e["id"] for e in expired]}


@router.get("/config")
async def get_config() -> dict[str, Any]:
    """获取当前网络授权配置"""
    return {
        "auto_approve": AUTO_APPROVE,
        "timeout_seconds": AUTH_TIMEOUT_SECONDS,
    }
