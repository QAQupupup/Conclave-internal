"""管理员路由（占位）。

管理后台功能将在后续迭代中实现：
- 系统级配置管理
- 全局反馈查看/处理
- 用户/租户管理
- 系统配额管理
- 审计日志查看
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/stats")
async def admin_stats() -> dict:
    """系统统计（占位，后续实现）。"""
    return {"status": "ok", "message": "Admin API placeholder"}
