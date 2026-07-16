# CAPTCHA 值守 API 端点
#
# 提供值守模式开关、验证码会话查询/解决/截图等接口
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException

from app.schemas.captcha import GuardModeRequest, ResolveRequest
from app.tools.captcha_guard import get_captcha_guard

logger = logging.getLogger("app.routers.captcha")

router = APIRouter(prefix="/api/captcha", tags=["captcha"])


@router.get("/status")
async def get_captcha_status() -> dict[str, Any]:
    """获取CAPTCHA值守状态"""
    guard = await get_captcha_guard()
    return {
        "guard_mode": guard.guard_mode,
        "vnc_ready": guard.is_vnc_ready(),
        "pending_count": len(guard.get_pending_sessions()),
        "vnc_url": "/vnc/vnc.html?autoconnect=true&resize=scale" if guard.is_vnc_ready() else None,
        "vnc_port": 6080,
        "cdp_port": 9222,
    }


@router.post("/guard-mode")
async def set_guard_mode(req: GuardModeRequest) -> dict[str, Any]:
    """开启/关闭CAPTCHA值守模式

    开启后，当Web Search遇到验证码时会暂停等待人工介入。
    需要Xvfb/x11vnc/websockify支持（Docker镜像已预装）。
    """
    guard = await get_captcha_guard()
    guard.set_guard_mode(req.enabled)
    if req.enabled and not guard.is_vnc_ready():
        await guard.start_vnc()
    return {
        "ok": True,
        "guard_mode": guard.guard_mode,
        "vnc_ready": guard.is_vnc_ready(),
    }


@router.get("/sessions")
async def list_sessions() -> dict[str, Any]:
    """列出所有CAPTCHA会话（含已解决的）"""
    guard = await get_captcha_guard()
    # 清理过期会话
    guard.cleanup_old_sessions()
    return {
        "sessions": guard.get_all_sessions(),
        "pending": guard.get_pending_sessions(),
    }


@router.get("/sessions/{session_id}")
async def get_session(session_id: str) -> dict[str, Any]:
    """获取单个CAPTCHA会话详情"""
    guard = await get_captcha_guard()
    session = guard.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    return session.snapshot()


@router.get("/sessions/{session_id}/screenshot")
async def get_session_screenshot(session_id: str) -> dict[str, Any]:
    """获取会话最新截图（base64 PNG）"""
    guard = await get_captcha_guard()
    session = guard.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    screenshot = await guard.get_screenshot(session_id)
    if not screenshot:
        raise HTTPException(status_code=404, detail="截图不可用")
    return {"session_id": session_id, "screenshot": f"data:image/png;base64,{screenshot}"}


@router.post("/resolve")
async def resolve_captcha(req: ResolveRequest) -> dict[str, Any]:
    """标记验证码已解决，恢复自动化流程

    当用户在noVNC窗口中手动完成验证码后，点击前端的"已完成验证"按钮，
    调用此接口通知后端继续执行。
    """
    guard = await get_captcha_guard()
    ok = guard.resolve(req.session_id)
    if not ok:
        raise HTTPException(status_code=400, detail="会话不存在或已处理")
    return {"ok": True, "session_id": req.session_id}


@router.post("/start-vnc")
async def start_vnc() -> dict[str, Any]:
    """手动启动VNC环境（默认在首次遇到CAPTCHA时自动启动）"""
    guard = await get_captcha_guard()
    ok = await guard.start_vnc()
    return {"ok": ok, "vnc_ready": guard.is_vnc_ready()}
