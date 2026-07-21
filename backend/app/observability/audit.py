"""审计日志系统

记录所有关键用户操作和系统事件，用于：
1. 实时问题定位（追踪事件流向、错误上下文）
2. 安全审计（谁在什么时候做了什么）
3. 行为分析（用户操作路径、功能使用频率）
4. 合规审计（完整的操作链路可追溯）

审计事件持久化到 PostgreSQL（audit_logs 表，ORM 模型见 app/db/models/observability.py）。
原 SQLite 实现（audit.db）已废弃，M1.7 迁移到 PostgreSQL。

设计说明：
- log() 保持同步接口（调用点分布在中间件/路由/事件总线，改成 async 波及面太大）
- 内部通过独立后台线程 + 专用事件循环执行 async PG 写入
- 写入失败不影响主流程（审计系统故障不应阻塞业务）
- 保留内存缓冲，后台线程批量 flush
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import threading
import time
from collections import deque
from datetime import datetime, timezone
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

# 后台 flush 间隔（秒）
_FLUSH_INTERVAL = 2.0
# 内存缓冲上限（超过则同步丢弃最旧记录，防止 OOM）
_BUFFER_MAX = 5000
# 单批 flush 最大条数
_BATCH_SIZE = 200
# audit_logs 表保留最大记录数
_MAX_RECORDS = 100000


class AuditLogger:
    """审计日志记录器（PostgreSQL 后端）

    事件写入内存缓冲，后台线程批量 flush 到 PostgreSQL audit_logs 表。
    写操作线程安全（使用 deque + lock），不影响主流程。
    """

    def __init__(self, max_records: int = _MAX_RECORDS) -> None:
        self._max_records = max_records
        self._buffer: deque[dict[str, Any]] = deque(maxlen=_BUFFER_MAX)
        self._buffer_lock = threading.Lock()
        self._flush_event = threading.Event()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._started = False
        # 查询用的同步缓存（stats 等同步方法用，避免起额外循环）
        self._last_stats: dict[str, Any] = {}

    def start(self) -> None:
        """启动后台 flush 线程。幂等。"""
        if self._started:
            return
        self._started = True
        self._thread = threading.Thread(
            target=self._flush_loop,
            name="audit-flush",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        """停止后台线程并 flush 剩余缓冲。"""
        if not self._started:
            return
        self._stop_event.set()
        self._flush_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
        self._started = False
        self._thread = None
        self._loop = None

    def _flush_loop(self) -> None:
        """后台线程：专用事件循环批量 flush 到 PG。"""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            while not self._stop_event.is_set():
                self._flush_event.wait(_FLUSH_INTERVAL)
                self._flush_event.clear()
                self._loop.run_until_complete(self._flush_batch())
            # 停止前 flush 剩余
            self._loop.run_until_complete(self._flush_batch())
        except Exception as e:
            print(f"[AuditLogger] 后台线程异常: {e}", flush=True)
        finally:
            self._loop.close()

    async def _flush_batch(self) -> None:
        """从缓冲取一批记录写入 PG。"""
        batch: list[dict[str, Any]] = []
        with self._buffer_lock:
            while len(batch) < _BATCH_SIZE and self._buffer:
                batch.append(self._buffer.popleft())
        if not batch:
            return
        try:
            await self._write_to_pg(batch)
        except Exception as e:
            print(f"[AuditLogger] flush 失败: {e}", flush=True)
            # 失败的记录丢弃（不回填缓冲，避免无限重试）

    async def _write_to_pg(self, batch: list[dict[str, Any]]) -> None:
        """批量写入 PostgreSQL audit_logs 表。"""
        from app.db.engine import async_session_factory
        from app.db.models.observability import AuditLogModel

        async with async_session_factory() as session:
            try:
                session.add_all([AuditLogModel(**record) for record in batch])
                await session.commit()
                # 定期清理旧记录（简易实现：每次 flush 后检查）
                # 用 raw SQL 避免加载 ORM
                from sqlalchemy import text

                await session.execute(
                    text(
                        "DELETE FROM audit_logs WHERE id IN "
                        "(SELECT id FROM audit_logs ORDER BY id DESC LIMIT -1 OFFSET :max)"
                    ),
                    {"max": self._max_records},
                )
                await session.commit()
            except Exception:
                await session.rollback()
                raise

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
        """记录一条审计事件（同步接口，写入内存缓冲）。"""
        category = AUDIT_CATEGORIES.get(action, "其他")
        now = datetime.now(timezone.utc).isoformat()

        uid = user_id or get_user_id() or "-"
        uname = username or get_username() or "-"
        urole = user_role or get_user_role() or ""
        mid = meeting_id or get_meeting_id() or "-"
        rid = get_request_id() or "-"

        details_json = json.dumps(details or {}, ensure_ascii=False, default=str)

        record = {
            "timestamp": now,
            "category": category,
            "action": action,
            "user_id": uid,
            "username": uname,
            "user_role": urole,
            "meeting_id": mid,
            "request_id": rid,
            "ip": ip,
            "status": status,
            "details": details_json,
            "duration_ms": duration_ms,
        }

        with self._buffer_lock:
            self._buffer.append(record)
        # 触发后台 flush（非阻塞）
        self._flush_event.set()

    async def query(
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
        """查询审计日志（异步，从 PG 读取）。"""
        from sqlalchemy import select

        from app.db.engine import async_session_factory
        from app.db.models.observability import AuditLogModel

        async with async_session_factory() as session:
            stmt = select(AuditLogModel).order_by(AuditLogModel.id.desc())
            if action:
                stmt = stmt.where(AuditLogModel.action == action)
            if username:
                stmt = stmt.where(AuditLogModel.username == username)
            if meeting_id:
                stmt = stmt.where(AuditLogModel.meeting_id == meeting_id)
            if category:
                stmt = stmt.where(AuditLogModel.category == category)
            if status:
                stmt = stmt.where(AuditLogModel.status == status)
            if since:
                stmt = stmt.where(AuditLogModel.timestamp >= since)
            if until:
                stmt = stmt.where(AuditLogModel.timestamp <= until)
            stmt = stmt.limit(limit).offset(offset)
            result = await session.execute(stmt)
            rows: list[dict[str, Any]] = []
            for row in result.scalars():
                record = {
                    "id": row.id,
                    "timestamp": row.timestamp,
                    "category": row.category,
                    "action": row.action,
                    "user_id": row.user_id,
                    "username": row.username,
                    "user_role": row.user_role,
                    "meeting_id": row.meeting_id,
                    "request_id": row.request_id,
                    "ip": row.ip,
                    "status": row.status,
                    "duration_ms": row.duration_ms,
                }
                try:
                    record["details"] = json.loads(row.details or "{}")
                except Exception:
                    record["details"] = {}
                rows.append(record)
            return rows

    async def stats(self, since_minutes: int = 60) -> dict[str, Any]:
        """获取审计统计信息（异步，从 PG 聚合）。"""
        from datetime import timedelta

        from sqlalchemy import func, select

        from app.db.engine import async_session_factory
        from app.db.models.observability import AuditLogModel

        since_ts = (datetime.now(timezone.utc) - timedelta(minutes=since_minutes)).isoformat()
        async with async_session_factory() as session:
            total = (
                await session.execute(
                    select(func.count()).select_from(AuditLogModel)
                )
            ).scalar() or 0
            errors = (
                await session.execute(
                    select(func.count()).select_from(AuditLogModel).where(
                        AuditLogModel.status == "error"
                    )
                )
            ).scalar() or 0
            by_action_result = await session.execute(
                select(AuditLogModel.action, func.count().label("cnt"))
                .where(AuditLogModel.timestamp >= since_ts)
                .group_by(AuditLogModel.action)
                .order_by(func.count().desc())
                .limit(20)
            )
            by_user_result = await session.execute(
                select(AuditLogModel.username, func.count().label("cnt"))
                .where(AuditLogModel.username != "-")
                .group_by(AuditLogModel.username)
                .order_by(func.count().desc())
                .limit(10)
            )
            return {
                "total_records": total,
                "error_count": errors,
                "top_actions": [{"action": a, "count": c} for a, c in by_action_result],
                "top_users": [{"username": u, "count": c} for u, c in by_user_result],
            }

    def close(self) -> None:
        """停止后台线程。"""
        self.stop()


# 进程级单例
_audit_logger: AuditLogger | None = None
_init_lock = threading.Lock()


def get_audit_logger() -> AuditLogger:
    global _audit_logger
    if _audit_logger is None:
        with _init_lock:
            if _audit_logger is None:
                _audit_logger = AuditLogger()
                _audit_logger.start()
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
