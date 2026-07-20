# 网络授权审批：沙箱执行因网络限制失败时，生成申请单供用户批复
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from app.db.engine import async_session_factory
from app.tenants import current_tenant_id


async def init_auth_table() -> None:
    """初始化网络授权申请表"""
    ddl_statements = [
        """
        CREATE TABLE IF NOT EXISTS net_auth_requests (
            id TEXT PRIMARY KEY,
            tenant_id INTEGER,
            meeting_id TEXT NOT NULL,
            stage TEXT NOT NULL,
            code_snippet TEXT NOT NULL,
            requested_level TEXT NOT NULL,
            detected_level TEXT NOT NULL,
            failure_reason TEXT NOT NULL,
            stderr_output TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            review_action TEXT,
            review_comment TEXT,
            reviewed_at TEXT,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            resolved_at TEXT
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_auth_meeting ON net_auth_requests(meeting_id)",
        "CREATE INDEX IF NOT EXISTS idx_auth_status ON net_auth_requests(status)",
    ]
    async with async_session_factory() as session:
        for stmt in ddl_statements:
            await session.execute(text(stmt))
        # 确保 tenant_id 列存在（兼容旧表）
        await session.execute(text("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'net_auth_requests' AND column_name = 'tenant_id'
                ) THEN
                    ALTER TABLE net_auth_requests ADD COLUMN tenant_id INTEGER;
                END IF;
            END$$;
        """))
        # 创建 tenant_id 索引
        await session.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_auth_tenant ON net_auth_requests(tenant_id)
        """))
        await session.commit()


async def create_auth_request(
    request_id: str,
    meeting_id: str,
    stage: str,
    code_snippet: str,
    requested_level: str,
    detected_level: str,
    failure_reason: str,
    stderr_output: str,
    expires_at: datetime,
) -> None:
    """创建网络授权申请单"""
    now = datetime.now(timezone.utc)
    tid = current_tenant_id()
    async with async_session_factory() as session:
        await session.execute(
            text(
                """
                INSERT INTO net_auth_requests
                (id, tenant_id, meeting_id, stage, code_snippet, requested_level, detected_level,
                 failure_reason, stderr_output, status, created_at, expires_at)
                VALUES (:id, :tenant_id, :meeting_id, :stage, :code_snippet, :requested_level, :detected_level,
                        :failure_reason, :stderr_output, 'pending', :created_at, :expires_at)
                """
            ),
            {
                "id": request_id,
                "tenant_id": tid,
                "meeting_id": meeting_id,
                "stage": stage,
                "code_snippet": code_snippet[:2000],
                "requested_level": requested_level,
                "detected_level": detected_level,
                "failure_reason": failure_reason,
                "stderr_output": stderr_output[:4000],
                "created_at": now.isoformat(),
                "expires_at": expires_at.isoformat(),
            },
        )
        await session.commit()


async def get_auth_request(request_id: str) -> dict[str, Any] | None:
    """取单条申请（校验租户归属）"""
    tid = current_tenant_id()
    async with async_session_factory() as session:
        if tid is not None:
            result = await session.execute(
                text("SELECT * FROM net_auth_requests WHERE id = :request_id AND tenant_id = :tid"),
                {"request_id": request_id, "tid": tid},
            )
        else:
            result = await session.execute(
                text("SELECT * FROM net_auth_requests WHERE id = :request_id"),
                {"request_id": request_id},
            )
        row = result.mappings().first()
        return dict(row) if row else None


async def list_auth_requests(
    meeting_id: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """列出申请单，可按会议和状态过滤。自动按租户过滤。"""
    tid = current_tenant_id()
    async with async_session_factory() as session:
        sql = "SELECT * FROM net_auth_requests"
        params: dict[str, Any] = {}
        conditions: list[str] = []
        if tid is not None:
            conditions.append("tenant_id = :tid")
            params["tid"] = tid
        if meeting_id:
            conditions.append("meeting_id = :meeting_id")
            params["meeting_id"] = meeting_id
        if status:
            conditions.append("status = :status")
            params["status"] = status
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY created_at DESC"
        result = await session.execute(text(sql), params)
        rows = result.mappings().all()
        return [dict(r) for r in rows]


async def review_auth_request(
    request_id: str,
    action: str,
    comment: str = "",
) -> dict[str, Any] | None:
    """批复申请单：action=approved/denied（校验租户归属）"""
    now = datetime.now(timezone.utc)
    tid = current_tenant_id()
    async with async_session_factory() as session:
        if tid is not None:
            await session.execute(
                text(
                    """
                    UPDATE net_auth_requests
                    SET status = :status, review_action = :review_action, review_comment = :review_comment,
                        reviewed_at = :reviewed_at, resolved_at = :resolved_at
                    WHERE id = :request_id AND status = 'pending' AND tenant_id = :tid
                    """
                ),
                {
                    "status": action,
                    "review_action": action,
                    "review_comment": comment,
                    "reviewed_at": now.isoformat(),
                    "resolved_at": now.isoformat(),
                    "request_id": request_id,
                    "tid": tid,
                },
            )
        else:
            await session.execute(
                text(
                    """
                    UPDATE net_auth_requests
                    SET status = :status, review_action = :review_action, review_comment = :review_comment,
                        reviewed_at = :reviewed_at, resolved_at = :resolved_at
                    WHERE id = :request_id AND status = 'pending'
                    """
                ),
                {
                    "status": action,
                    "review_action": action,
                    "review_comment": comment,
                    "reviewed_at": now.isoformat(),
                    "resolved_at": now.isoformat(),
                    "request_id": request_id,
                },
            )
        await session.commit()
        if tid is not None:
            result = await session.execute(
                text("SELECT * FROM net_auth_requests WHERE id = :request_id AND tenant_id = :tid"),
                {"request_id": request_id, "tid": tid},
            )
        else:
            result = await session.execute(
                text("SELECT * FROM net_auth_requests WHERE id = :request_id"),
                {"request_id": request_id},
            )
        row = result.mappings().first()
        return dict(row) if row else None


async def expire_pending_requests() -> list[dict[str, Any]]:
    """将超时未批复的申请单标记为 expired（降级处理）

    返回刚过期的申请列表，供调用方做降级执行。
    注意：这是系统级维护操作，会处理所有租户的过期申请。
    """
    now = datetime.now(timezone.utc)
    async with async_session_factory() as session:
        result = await session.execute(
            text(
                """
                SELECT * FROM net_auth_requests
                WHERE status = 'pending' AND expires_at < :now
                """
            ),
            {"now": now.isoformat()},
        )
        rows = result.mappings().all()
        expired = [dict(r) for r in rows]
        if expired:
            await session.execute(
                text(
                    """
                    UPDATE net_auth_requests
                    SET status = 'expired', resolved_at = :now
                    WHERE status = 'pending' AND expires_at < :now
                    """
                ),
                {"now": now.isoformat()},
            )
            await session.commit()
        return expired


async def get_pending_for_meeting(meeting_id: str) -> list[dict[str, Any]]:
    """取某会议的 pending 申请（按租户过滤）"""
    tid = current_tenant_id()
    async with async_session_factory() as session:
        if tid is not None:
            result = await session.execute(
                text(
                    "SELECT * FROM net_auth_requests WHERE meeting_id = :meeting_id "
                    "AND status = 'pending' AND tenant_id = :tid"
                ),
                {"meeting_id": meeting_id, "tid": tid},
            )
        else:
            result = await session.execute(
                text(
                    "SELECT * FROM net_auth_requests WHERE meeting_id = :meeting_id AND status = 'pending'"
                ),
                {"meeting_id": meeting_id},
            )
        rows = result.mappings().all()
        return [dict(r) for r in rows]
