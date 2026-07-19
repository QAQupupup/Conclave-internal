"""审计日志系统

记录所有关键用户操作和系统事件，用于：
1. 实时问题定位（追踪事件流向、错误上下文）
2. 安全审计（谁在什么时候做了什么）
3. 行为分析（用户操作路径、功能使用频率）
4. 合规审计（完整的操作链路可追溯）

审计事件持久化到 SQLite 数据库（独立表），同时通过 log_bus 输出到日志。
"""

from __future__ import annotations

import contextlib
import json
import os
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.context import get_meeting_id, get_request_id, get_user_id, get_user_role, get_username

# 审计事件类型分类
AUDIT_CATEGORIES = {
    # 认证相关
    "auth.login": "认证",
    "auth.logout": "认证",
    "auth.login_failed": "认证",
    "auth.token_refresh": "认证",
    # 会议生命周期
    "meeting.created": "会议",
    "meeting.started": "会议",
    "meeting.paused": "会议",
    "meeting.resumed": "会议",
    "meeting.aborted": "会议",
    "meeting.deleted": "会议",
    "meeting.viewed": "会议",
    # 会议控制
    "meeting.intervened": "控制",
    "meeting.borrow_requested": "控制",
    "meeting.borrow_approved": "控制",
    "meeting.borrow_rejected": "控制",
    "meeting.stage_changed": "控制",
    # 沙箱/部署
    "sandbox.command_executed": "沙箱",
    "sandbox.service_deployed": "沙箱",
    "sandbox.service_stopped": "沙箱",
    "sandbox.file_read": "沙箱",
    "sandbox.file_write": "沙箱",
    # 系统管理
    "admin.user_created": "管理",
    "admin.user_deleted": "管理",
    "admin.config_changed": "管理",
    "admin.key_saved": "管理",
    # 安全事件
    "security.rate_limited": "安全",
    "security.unauthorized_access": "安全",
    "security.ssrf_blocked": "安全",
    "security.sandbox_escape_attempt": "安全",
    "security.path_traversal_blocked": "安全",
    # 系统事件
    "system.error": "系统",
    "system.ws_connected": "系统",
    "system.ws_disconnected": "系统",
    "system.llm_error": "系统",
    "system.llm_circuit_tripped": "系统",
}


class AuditLogger:
    """审计日志记录器

    事件写入 SQLite（自动建表），保留最近 N 条记录，支持按时间/用户/类别/会议查询。
    写操作使用线程锁保证并发安全，使用 WAL 模式提高写入性能。
    """

    def __init__(self, db_path: str | None = None, max_records: int = 100000) -> None:
        self._db_path = db_path or os.environ.get(
            "CONCLAVE_AUDIT_DB",
            str(Path(os.environ.get("CONCLAVE_DB_PATH", "/app/data/conclave.db")).parent / "audit.db"),
        )
        self._max_records = max_records
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None
        self._init_db()

    def _init_db(self) -> None:
        try:
            db_dir = os.path.dirname(self._db_path)
            if db_dir:
                os.makedirs(db_dir, exist_ok=True)
            self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    category TEXT NOT NULL,
                    action TEXT NOT NULL,
                    user_id TEXT DEFAULT '-',
                    username TEXT DEFAULT '-',
                    user_role TEXT DEFAULT '',
                    meeting_id TEXT DEFAULT '-',
                    request_id TEXT DEFAULT '-',
                    ip TEXT DEFAULT '',
                    status TEXT DEFAULT 'success',
                    details TEXT DEFAULT '{}',
                    duration_ms INTEGER DEFAULT 0
                )
            """)
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_time ON audit_log(timestamp)")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_log(username)")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_meeting ON audit_log(meeting_id)")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log(action)")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_category ON audit_log(category)")
            self._conn.commit()
        except Exception as e:
            # 审计系统故障不应影响主流程
            print(f"[AuditLogger] 初始化失败: {e}", flush=True)
            self._conn = None

    def log(
        self,
        action: str,
        status: str = "success",
        details: dict[str, Any] | None = None,
        duration_ms: int = 0,
        ip: str = "",
        username: str | None = None,
        user_id: str | None = None,
        user_role: str | None = None,
        meeting_id: str | None = None,
    ) -> None:
        """记录一条审计事件"""
        if not self._conn:
            return

        category = AUDIT_CATEGORIES.get(action, "其他")
        now = datetime.now(timezone.utc).isoformat()

        uid = user_id or get_user_id() or "-"
        uname = username or get_username() or "-"
        urole = user_role or get_user_role() or ""
        mid = meeting_id or get_meeting_id() or "-"
        rid = get_request_id() or "-"

        details_json = json.dumps(details or {}, ensure_ascii=False, default=str)

        try:
            with self._lock:
                self._conn.execute(
                    """INSERT INTO audit_log
                    (timestamp, category, action, user_id, username, user_role, meeting_id,
                     request_id, ip, status, details, duration_ms)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (now, category, action, uid, uname, urole, mid, rid, ip, status, details_json, duration_ms),
                )
                self._conn.commit()

                # 定期清理旧记录（超过 max_records 时删除最旧的）
                # 使用子查询避免全表扫描
                self._conn.execute(
                    "DELETE FROM audit_log WHERE id IN (SELECT id FROM audit_log ORDER BY id DESC LIMIT -1 OFFSET ?)",
                    (self._max_records,),
                )
                self._conn.commit()
        except Exception as e:
            print(f"[AuditLogger] 写入失败: {e}", flush=True)

    def query(
        self,
        limit: int = 100,
        offset: int = 0,
        action: str | None = None,
        username: str | None = None,
        meeting_id: str | None = None,
        category: str | None = None,
        status: str | None = None,
        since: str | None = None,
        until: str | None = None,
    ) -> list[dict[str, Any]]:
        """查询审计日志"""
        if not self._conn:
            return []

        conditions = []
        params: list[Any] = []
        if action:
            conditions.append("action = ?")
            params.append(action)
        if username:
            conditions.append("username = ?")
            params.append(username)
        if meeting_id:
            conditions.append("meeting_id = ?")
            params.append(meeting_id)
        if category:
            conditions.append("category = ?")
            params.append(category)
        if status:
            conditions.append("status = ?")
            params.append(status)
        if since:
            conditions.append("timestamp >= ?")
            params.append(since)
        if until:
            conditions.append("timestamp <= ?")
            params.append(until)

        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        sql = f"SELECT * FROM audit_log {where} ORDER BY id DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        try:
            with self._lock:
                cursor = self._conn.execute(sql, params)
                columns = [desc[0] for desc in cursor.description]
                rows = []
                for row in cursor.fetchall():
                    record = dict(zip(columns, row, strict=False))
                    try:
                        record["details"] = json.loads(record.get("details", "{}"))
                    except Exception:
                        record["details"] = {}
                    rows.append(record)
                return rows
        except Exception as e:
            print(f"[AuditLogger] 查询失败: {e}", flush=True)
            return []

    def stats(self, since_minutes: int = 60) -> dict[str, Any]:
        """获取审计统计信息（用于监控面板）"""
        if not self._conn:
            return {}
        datetime.now(timezone.utc).isoformat()
        # 简单统计
        try:
            with self._lock:
                total = self._conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
                errors = self._conn.execute("SELECT COUNT(*) FROM audit_log WHERE status = 'error'").fetchone()[0]
                by_action = self._conn.execute(
                    "SELECT action, COUNT(*) as cnt FROM audit_log GROUP BY action ORDER BY cnt DESC LIMIT 20"
                ).fetchall()
                by_user = self._conn.execute(
                    "SELECT username, COUNT(*) as cnt FROM audit_log WHERE username != '-' GROUP BY username ORDER BY cnt DESC LIMIT 10"
                ).fetchall()
            return {
                "total_records": total,
                "error_count": errors,
                "top_actions": [{"action": a, "count": c} for a, c in by_action],
                "top_users": [{"username": u, "count": c} for u, c in by_user],
            }
        except Exception:
            return {}

    def close(self) -> None:
        if self._conn:
            with contextlib.suppress(Exception):
                self._conn.close()
            self._conn = None


# 进程级单例
_audit_logger: AuditLogger | None = None
_init_lock = threading.Lock()


def get_audit_logger() -> AuditLogger:
    global _audit_logger
    if _audit_logger is None:
        with _init_lock:
            if _audit_logger is None:
                _audit_logger = AuditLogger()
    return _audit_logger


def audit(
    action: str,
    status: str = "success",
    details: dict[str, Any] | None = None,
    duration_ms: int = 0,
    **kwargs: Any,
) -> None:
    """便捷函数：记录审计事件"""
    with contextlib.suppress(Exception):
        get_audit_logger().log(action, status, details, duration_ms, **kwargs)


class AuditTimer:
    """审计计时器：with 语句自动记录操作耗时"""

    def __init__(self, action: str, details: dict[str, Any] | None = None, **kwargs: Any) -> None:
        self.action = action
        self.details = details or {}
        self.kwargs = kwargs
        self.start = 0.0

    def __enter__(self) -> AuditTimer:
        self.start = time.monotonic()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        duration = int((time.monotonic() - self.start) * 1000)
        status = "error" if exc_type else "success"
        if exc_val:
            self.details["error"] = str(exc_val)
        audit(self.action, status, self.details, duration_ms=duration, **self.kwargs)
