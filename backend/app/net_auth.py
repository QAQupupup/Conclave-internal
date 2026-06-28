# 网络授权审批：沙箱执行因网络限制失败时，生成申请单供用户批复
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any

from app.db import _connect, _lock


def init_auth_table() -> None:
    """初始化网络授权申请表"""
    with _lock:
        conn = _connect()
        try:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS net_auth_requests (
                    id TEXT PRIMARY KEY,
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
                );

                CREATE INDEX IF NOT EXISTS idx_auth_meeting ON net_auth_requests(meeting_id);
                CREATE INDEX IF NOT EXISTS idx_auth_status ON net_auth_requests(status);
                """
            )
            conn.commit()
        finally:
            conn.close()


def create_auth_request(
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
    with _lock:
        conn = _connect()
        try:
            conn.execute(
                """
                INSERT INTO net_auth_requests
                (id, meeting_id, stage, code_snippet, requested_level, detected_level,
                 failure_reason, stderr_output, status, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
                """,
                (
                    request_id, meeting_id, stage, code_snippet[:2000],
                    requested_level, detected_level,
                    failure_reason, stderr_output[:4000],
                    now.isoformat(), expires_at.isoformat(),
                ),
            )
            conn.commit()
        finally:
            conn.close()


def get_auth_request(request_id: str) -> dict[str, Any] | None:
    """取单条申请"""
    with _lock:
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT * FROM net_auth_requests WHERE id = ?", (request_id,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()


def list_auth_requests(
    meeting_id: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """列出申请单，可按会议和状态过滤"""
    with _lock:
        conn = _connect()
        try:
            sql = "SELECT * FROM net_auth_requests"
            params: list[str] = []
            conditions: list[str] = []
            if meeting_id:
                conditions.append("meeting_id = ?")
                params.append(meeting_id)
            if status:
                conditions.append("status = ?")
                params.append(status)
            if conditions:
                sql += " WHERE " + " AND ".join(conditions)
            sql += " ORDER BY created_at DESC"
            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()


def review_auth_request(
    request_id: str,
    action: str,
    comment: str = "",
) -> dict[str, Any] | None:
    """批复申请单：action=approved/denied"""
    now = datetime.now(timezone.utc)
    with _lock:
        conn = _connect()
        try:
            conn.execute(
                """
                UPDATE net_auth_requests
                SET status = ?, review_action = ?, review_comment = ?, reviewed_at = ?, resolved_at = ?
                WHERE id = ? AND status = 'pending'
                """,
                (action, action, comment, now.isoformat(), now.isoformat(), request_id),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM net_auth_requests WHERE id = ?", (request_id,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()


def expire_pending_requests() -> list[dict[str, Any]]:
    """将超时未批复的申请单标记为 expired（降级处理）

    返回刚过期的申请列表，供调用方做降级执行。
    """
    now = datetime.now(timezone.utc)
    with _lock:
        conn = _connect()
        try:
            # 查出已过期但 still pending 的
            rows = conn.execute(
                """
                SELECT * FROM net_auth_requests
                WHERE status = 'pending' AND expires_at < ?
                """,
                (now.isoformat(),),
            ).fetchall()
            expired = [dict(r) for r in rows]
            if expired:
                conn.execute(
                    """
                    UPDATE net_auth_requests
                    SET status = 'expired', resolved_at = ?
                    WHERE status = 'pending' AND expires_at < ?
                    """,
                    (now.isoformat(), now.isoformat()),
                )
                conn.commit()
            return expired
        finally:
            conn.close()


def get_pending_for_meeting(meeting_id: str) -> list[dict[str, Any]]:
    """取某会议的 pending 申请"""
    with _lock:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT * FROM net_auth_requests WHERE meeting_id = ? AND status = 'pending'",
                (meeting_id,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()
