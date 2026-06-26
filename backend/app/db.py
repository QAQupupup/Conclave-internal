# SQLite 持久化：meetings 与 messages 两张表，用标准库 sqlite3，无需 ORM
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config import settings

# 线程锁，保证 SQLite 写入安全（SQLite 默认串行化）
_lock = threading.Lock()


def _connect() -> sqlite3.Connection:
    """建立 SQLite 连接，开启外键与 WAL"""
    conn = sqlite3.connect(settings.sqlite_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def init_db() -> None:
    """初始化两张表"""
    Path(settings.sqlite_path).parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        conn = _connect()
        try:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS meetings (
                    id TEXT PRIMARY KEY,
                    topic TEXT NOT NULL,
                    status TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    meeting_id TEXT NOT NULL,
                    agent_role TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    content TEXT NOT NULL,
                    claim_refs TEXT NOT NULL,
                    evidence_refs TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (meeting_id) REFERENCES meetings(id)
                );

                CREATE INDEX IF NOT EXISTS idx_messages_meeting ON messages(meeting_id);
                """
            )
            conn.commit()
        finally:
            conn.close()


def save_meeting(
    meeting_id: str,
    topic: str,
    status: str,
    stage: str,
    created_at: datetime,
    payload: dict[str, Any],
) -> None:
    """upsert 会议记录，payload 存 JSON"""
    with _lock:
        conn = _connect()
        try:
            conn.execute(
                """
                INSERT INTO meetings (id, topic, status, stage, created_at, payload)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    topic=excluded.topic,
                    status=excluded.status,
                    stage=excluded.stage,
                    payload=excluded.payload
                """,
                (
                    meeting_id,
                    topic,
                    status,
                    stage,
                    created_at.isoformat(),
                    json.dumps(payload, ensure_ascii=False, default=str),
                ),
            )
            conn.commit()
        finally:
            conn.close()


def get_meeting(meeting_id: str) -> dict[str, Any] | None:
    """取单条会议记录"""
    with _lock:
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT * FROM meetings WHERE id = ?", (meeting_id,)
            ).fetchone()
            if row is None:
                return None
            d = dict(row)
            d["payload"] = json.loads(d["payload"])
            return d
        finally:
            conn.close()


def list_meetings() -> list[dict[str, Any]]:
    """列出全部会议"""
    with _lock:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT * FROM meetings ORDER BY created_at DESC"
            ).fetchall()
            out = []
            for row in rows:
                d = dict(row)
                d["payload"] = json.loads(d["payload"])
                out.append(d)
            return out
        finally:
            conn.close()


def save_message(msg: dict[str, Any]) -> None:
    """保存发言记录"""
    with _lock:
        conn = _connect()
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO messages
                (id, meeting_id, agent_role, stage, content, claim_refs, evidence_refs, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    msg["id"],
                    msg["meeting_id"],
                    msg["agent_role"],
                    msg["stage"],
                    msg["content"],
                    json.dumps(msg.get("claim_refs", []), ensure_ascii=False),
                    json.dumps(msg.get("evidence_refs", []), ensure_ascii=False),
                    msg["created_at"],
                ),
            )
            conn.commit()
        finally:
            conn.close()


def list_messages(meeting_id: str) -> list[dict[str, Any]]:
    """取某会议的全部发言"""
    with _lock:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT * FROM messages WHERE meeting_id = ? ORDER BY created_at ASC",
                (meeting_id,),
            ).fetchall()
            out = []
            for row in rows:
                d = dict(row)
                d["claim_refs"] = json.loads(d["claim_refs"])
                d["evidence_refs"] = json.loads(d["evidence_refs"])
                out.append(d)
            return out
        finally:
            conn.close()
