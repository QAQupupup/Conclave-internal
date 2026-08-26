"""通知 API：系统通知、会议状态通知、LLM 事件通知。

数据来源：
- meetings 表状态变化（completed/error/paused）
- events 表中的 LLM/系统事件
- 系统级事件（配置变更等）

前端期望字段：{id, type, level, title, message, meeting_id?, created_at, read}
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.auth_guard import get_current_user
from app.db.engine import async_session_factory

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/notifications", tags=["notifications"])

VALID_TYPES = {"meeting", "system", "llm", "admin"}
VALID_LEVELS = {"info", "success", "warning", "error"}


async def _ensure_table() -> None:
    """确保通知表存在。"""
    async with async_session_factory() as session:
        await session.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS notifications (
                    id BIGSERIAL PRIMARY KEY,
                    user_id BIGINT REFERENCES users(id) ON DELETE CASCADE,
                    type VARCHAR(32) NOT NULL DEFAULT 'system',
                    level VARCHAR(16) NOT NULL DEFAULT 'info',
                    title VARCHAR(256) NOT NULL,
                    message TEXT NOT NULL,
                    meeting_id BIGINT REFERENCES meetings(id) ON DELETE SET NULL,
                    is_read BOOLEAN NOT NULL DEFAULT FALSE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                CREATE INDEX IF NOT EXISTS idx_notifications_user_created
                    ON notifications(user_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_notifications_unread
                    ON notifications(user_id, is_read) WHERE is_read = FALSE;
                """
            )
        )
        await session.commit()


@router.get("")
async def list_notifications(
    request: Request,
    unread_only: bool = Query(default=False, description="仅返回未读"),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    """获取当前用户的通知列表。"""
    uid, username, _role = get_current_user(request)
    if not username or username == "anonymous":
        raise HTTPException(status_code=401, detail="未认证")
    if uid is None:
        return {"notifications": [], "unread_count": 0}

    # uid 在 auth 层为字符串（users.id 为 BIGINT），转 int 供 DB 精确比较
    try:
        user_id = int(uid)
    except ValueError:
        raise HTTPException(status_code=401, detail="无效用户") from None

    await _ensure_table()

    # 同步会议状态为通知（如果最近 7 天的会议有未同步的状态变更）
    await _sync_meeting_notifications(user_id)

    async with async_session_factory() as session:
        where = "n.user_id = :uid"
        params: dict[str, Any] = {"uid": user_id, "limit": limit}
        if unread_only:
            where += " AND n.is_read = FALSE"

        result = await session.execute(
            text(
                f"""
                SELECT n.id, n.type, n.level, n.title, n.message, n.meeting_id,
                       n.is_read, n.created_at, m.title as meeting_title
                FROM notifications n
                LEFT JOIN meetings m ON n.meeting_id = m.id
                WHERE {where}
                ORDER BY n.created_at DESC
                LIMIT :limit
                """
            ),
            params,
        )
        rows = result.mappings().all()

        unread_result = await session.execute(
            text("SELECT COUNT(*) as c FROM notifications WHERE user_id = :uid AND is_read = FALSE"),
            {"uid": user_id},
        )
        unread_count = unread_result.scalar() or 0

    notifications = []
    for row in rows:
        notifications.append(
            {
                "id": str(row["id"]),
                "type": row["type"],
                "level": row["level"],
                "title": row["title"],
                "message": row["message"],
                "meeting_id": str(row["meeting_id"]) if row["meeting_id"] else None,
                "meeting_title": row["meeting_title"],
                "read": row["is_read"],
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            }
        )

    return {"notifications": notifications, "unread_count": unread_count}


@router.post("/{notif_id}/read")
async def mark_as_read(notif_id: int, request: Request) -> dict[str, Any]:
    """标记单条通知为已读。"""
    uid, username, _role = get_current_user(request)
    if not username or username == "anonymous":
        raise HTTPException(status_code=401, detail="未认证")
    if uid is None:
        raise HTTPException(status_code=401, detail="未认证")

    await _ensure_table()

    async with async_session_factory() as session:
        await session.execute(
            text("UPDATE notifications SET is_read = TRUE WHERE id = :nid AND user_id = :uid"),
            {"nid": notif_id, "uid": uid},
        )
        await session.commit()

    return {"ok": True}


@router.post("/read-all")
async def mark_all_as_read(request: Request) -> dict[str, Any]:
    """标记所有通知为已读。"""
    uid, username, _role = get_current_user(request)
    if not username or username == "anonymous":
        raise HTTPException(status_code=401, detail="未认证")
    if uid is None:
        raise HTTPException(status_code=401, detail="未认证")

    await _ensure_table()

    async with async_session_factory() as session:
        await session.execute(
            text("UPDATE notifications SET is_read = TRUE WHERE user_id = :uid AND is_read = FALSE"),
            {"uid": uid},
        )
        await session.commit()

    return {"ok": True}


class CreateNotificationRequest(BaseModel):
    """服务端内部使用的通知创建请求。"""

    type: str = "system"
    level: str = "info"
    title: str = Field(min_length=1, max_length=256)
    message: str = Field(min_length=1)
    meeting_id: int | None = None
    user_id: int | None = None  # None 表示广播给所有用户


@router.post("")
async def create_notification(body: CreateNotificationRequest, request: Request) -> dict[str, Any]:
    """创建一条通知（管理员权限或内部调用）。"""
    _uid, _username, role = get_current_user(request)
    from app.auth_guard import is_admin

    if not is_admin(role):
        raise HTTPException(status_code=403, detail="需要管理员权限")

    if body.type not in VALID_TYPES:
        raise HTTPException(status_code=400, detail=f"无效 type: {body.type}")
    if body.level not in VALID_LEVELS:
        raise HTTPException(status_code=400, detail=f"无效 level: {body.level}")

    await _ensure_table()

    async with async_session_factory() as session:
        if body.user_id is not None:
            await session.execute(
                text(
                    "INSERT INTO notifications(user_id, type, level, title, message, meeting_id) "
                    "VALUES(:uid, :t, :l, :title, :msg, :mid)"
                ),
                {
                    "uid": body.user_id,
                    "t": body.type,
                    "l": body.level,
                    "title": body.title,
                    "msg": body.message,
                    "mid": body.meeting_id,
                },
            )
        else:
            # 广播给所有活跃用户
            users = (await session.execute(text("SELECT id FROM users WHERE is_active = TRUE"))).mappings().all()
            for u in users:
                await session.execute(
                    text(
                        "INSERT INTO notifications(user_id, type, level, title, message, meeting_id) "
                        "VALUES(:uid, :t, :l, :title, :msg, :mid)"
                    ),
                    {
                        "uid": u["id"],
                        "t": body.type,
                        "l": body.level,
                        "title": body.title,
                        "msg": body.message,
                        "mid": body.meeting_id,
                    },
                )
        await session.commit()

    return {"ok": True}


async def _sync_meeting_notifications(user_id: int) -> None:
    """将最近 7 天完成/出错的会议同步为通知（去重）。"""
    try:
        since = datetime.now(timezone.utc) - timedelta(days=7)
        async with async_session_factory() as session:
            # 找到该用户可见、最近 7 天完成/失败、且尚未生成通知的会议
            meetings = (
                (
                    await session.execute(
                        text(
                            """
                        SELECT m.id, m.title, m.status, m.updated_at
                        FROM meetings m
                        WHERE m.status IN ('completed', 'failed', 'error', 'paused')
                          AND m.updated_at > :since
                          AND m.tenant_id = (SELECT tenant_id FROM users WHERE id = :uid)
                          AND NOT EXISTS (
                              SELECT 1 FROM notifications n
                              WHERE n.user_id = :uid AND n.meeting_id = m.id
                              AND n.type = 'meeting'
                          )
                        ORDER BY m.updated_at DESC
                        LIMIT 20
                        """
                        ),
                        {"since": since, "uid": user_id},
                    )
                )
                .mappings()
                .all()
            )

            for m in meetings:
                status = m["status"]
                title_map = {
                    "completed": "会议完成",
                    "failed": "会议失败",
                    "error": "会议出错",
                    "paused": "会议暂停",
                }
                level_map = {
                    "completed": "success",
                    "failed": "error",
                    "error": "error",
                    "paused": "warning",
                }
                await session.execute(
                    text(
                        "INSERT INTO notifications(user_id, type, level, title, message, meeting_id) "
                        "VALUES(:uid, 'meeting', :level, :title, :msg, :mid)"
                    ),
                    {
                        "uid": user_id,
                        "level": level_map.get(status, "info"),
                        "title": title_map.get(status, "会议状态变更"),
                        "msg": f"会议 '{m['title']}' 状态变更为 {status}",
                        "mid": m["id"],
                    },
                )
            await session.commit()
    except Exception:
        logger.exception("Failed to sync meeting notifications for user %s", user_id)
