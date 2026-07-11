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

                CREATE TABLE IF NOT EXISTS events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    meeting_id TEXT NOT NULL,
                    type TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    ts TEXT NOT NULL,
                    trace_id TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_events_meeting ON events(meeting_id);
                CREATE INDEX IF NOT EXISTS idx_events_meeting_seq ON events(meeting_id, seq);

                CREATE TABLE IF NOT EXISTS user_preferences (
                    user_id TEXT NOT NULL DEFAULT 'default',
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (user_id, key)
                );

                CREATE TABLE IF NOT EXISTS meeting_tags (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    meeting_id TEXT NOT NULL,
                    tag TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(meeting_id, tag),
                    FOREIGN KEY (meeting_id) REFERENCES meetings(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_meeting_tags_meeting ON meeting_tags(meeting_id);
                CREATE INDEX IF NOT EXISTS idx_meeting_tags_tag ON meeting_tags(tag);

                CREATE TABLE IF NOT EXISTS agent_roles (
                    id TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL,
                    perspective TEXT NOT NULL DEFAULT '',
                    expertise_domains TEXT NOT NULL DEFAULT '[]',
                    risk_appetite TEXT NOT NULL DEFAULT 'balanced',
                    default_stance TEXT NOT NULL DEFAULT '',
                    evidence_preference TEXT NOT NULL DEFAULT 'balanced',
                    model_override TEXT NOT NULL DEFAULT '',
                    background_brief TEXT NOT NULL DEFAULT '',
                    prompt_template TEXT NOT NULL DEFAULT '',
                    is_builtin INTEGER NOT NULL DEFAULT 0,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_agent_roles_active ON agent_roles(is_active);

                CREATE TABLE IF NOT EXISTS meeting_aux (
                    meeting_id TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value_json TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (meeting_id, key),
                    FOREIGN KEY (meeting_id) REFERENCES meetings(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_meeting_aux_meeting ON meeting_aux(meeting_id);
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


# ---------- meeting_aux 辅助大字段持久化 ----------

# 需要从 payload 中分离的 aux 字段名列表
_AUX_KEYS = ("llm_trace", "evidence_set", "conclusion_chain", "borrowed_agents")


def save_meeting_aux(meeting_id: str, aux: dict[str, Any]) -> None:
    """将 aux 大字段单独持久化到 meeting_aux 表。

    每个 aux key 对应一行，value_json 存 JSON 序列化后的值。
    使用 INSERT OR REPLACE 实现 upsert。

    Args:
        meeting_id: 会议 ID
        aux: extract_aux() 返回的 dict，key 为字段名，value 为可 JSON 序列化的值
    """
    if not aux:
        return
    now = datetime.now().isoformat()
    with _lock:
        conn = _connect()
        try:
            for key, value in aux.items():
                conn.execute(
                    """
                    INSERT OR REPLACE INTO meeting_aux (meeting_id, key, value_json, updated_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        meeting_id,
                        key,
                        json.dumps(value, ensure_ascii=False, default=str),
                        now,
                    ),
                )
            conn.commit()
        finally:
            conn.close()


def get_meeting_aux(meeting_id: str) -> dict[str, Any]:
    """从 meeting_aux 表加载某会议的全部辅助大字段。

    向后兼容：如果 meeting_aux 表不存在或该会议无 aux 数据，返回空 dict。

    Args:
        meeting_id: 会议 ID

    Returns:
        dict，key 为字段名，value 为反序列化后的值。可能为空 dict。
    """
    aux: dict[str, Any] = {}
    with _lock:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT key, value_json FROM meeting_aux WHERE meeting_id = ?",
                (meeting_id,),
            ).fetchall()
            for row in rows:
                try:
                    aux[row["key"]] = json.loads(row["value_json"])
                except (json.JSONDecodeError, KeyError):
                    pass  # 损坏的 aux 数据跳过，不影响主流程
        except Exception:
            # 表可能不存在（旧数据库），静默返回空 dict
            pass
        finally:
            conn.close()
    return aux


def strip_aux_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """从 payload dict 中移除 aux 大字段，返回清理后的副本。

    用于在 save_meeting 之前精简 payload，配合 save_meeting_aux 使用。
    返回新的 dict，不修改原始输入。

    Args:
        payload: MeetingState.snapshot() 返回的 dict

    Returns:
        移除了 aux 字段的 payload 副本
    """
    cleaned = dict(payload)
    for key in _AUX_KEYS:
        if key in cleaned:
            cleaned[key] = {"_aux": True}
    return cleaned


def list_meetings(include_deleted: bool = False) -> list[dict[str, Any]]:
    """列出全部会议。默认排除软删除（status='deleted'）的记录。"""
    with _lock:
        conn = _connect()
        try:
            if include_deleted:
                rows = conn.execute(
                    "SELECT * FROM meetings ORDER BY created_at DESC"
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM meetings WHERE status != 'deleted' ORDER BY created_at DESC"
                ).fetchall()
            out = []
            for row in rows:
                d = dict(row)
                d["payload"] = json.loads(d["payload"])
                out.append(d)
            return out
        finally:
            conn.close()


def query_meetings(
    q: str | None = None,
    limit: int = 20,
    offset: int = 0,
    tags: list[str] | None = None,
    include_deleted: bool = False,
) -> dict[str, Any]:
    """搜索+分页+标签过滤查询会议。

    返回 {items, total}：
    - items：当前页的会议列表（含 tags 字段）
    - total：满足条件的总记录数（用于分页计算）
    """
    with _lock:
        conn = _connect()
        try:
            conditions: list[str] = []
            params: list[Any] = []

            if not include_deleted:
                conditions.append("m.status != 'deleted'")

            if q:
                conditions.append("m.topic LIKE ?")
                params.append(f"%{q}%")

            if tags:
                # 交集过滤：会议需同时拥有所有指定标签
                placeholders = ",".join("?" for _ in tags)
                conditions.append(
                    f"m.id IN (SELECT meeting_id FROM meeting_tags "
                    f"WHERE tag IN ({placeholders}) "
                    f"GROUP BY meeting_id HAVING COUNT(DISTINCT tag) = ?)"
                )
                params.extend(tags)
                params.append(len(tags))

            where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

            # 总数
            total_row = conn.execute(
                f"SELECT COUNT(*) as cnt FROM meetings m {where_clause}", params
            ).fetchone()
            total = total_row["cnt"] if total_row else 0

            # 分页查询
            rows = conn.execute(
                f"SELECT m.* FROM meetings m {where_clause} "
                f"ORDER BY m.created_at DESC LIMIT ? OFFSET ?",
                [*params, limit, offset],
            ).fetchall()

            items = []
            for row in rows:
                d = dict(row)
                d["payload"] = json.loads(d["payload"])
                # 查询该会议的标签
                tag_rows = conn.execute(
                    "SELECT tag FROM meeting_tags WHERE meeting_id = ? ORDER BY tag",
                    (d["id"],),
                ).fetchall()
                d["tags"] = [r["tag"] for r in tag_rows]
                items.append(d)

            return {"items": items, "total": total}
        finally:
            conn.close()


def get_meetings_by_ids(meeting_ids: list[str]) -> list[dict[str, Any]]:
    """批量获取会议记录（用于历史会议引用）。

    返回已完成的会议摘要列表，包含 topic、stage、status、artifact 摘要。
    不包含运行中的会议（status='running'），也不包含已删除的会议。
    """
    if not meeting_ids:
        return []
    with _lock:
        conn = _connect()
        try:
            placeholders = ",".join("?" for _ in meeting_ids)
            rows = conn.execute(
                f"SELECT id, topic, status, stage, created_at, payload "
                f"FROM meetings WHERE id IN ({placeholders}) "
                f"AND status NOT IN ('deleted', 'running') "
                f"ORDER BY created_at DESC",
                meeting_ids,
            ).fetchall()
            out = []
            for row in rows:
                d = dict(row)
                payload = json.loads(d["payload"])
                d["payload"] = payload
                d["clarified_topic"] = payload.get("clarified_topic", d["topic"])
                d["key_questions"] = payload.get("key_questions", [])
                d["artifact"] = payload.get("artifact")
                d["decision_record"] = payload.get("decision_record")
                d["flow_plan"] = payload.get("flow_plan", "full")
                # 提取产出摘要
                art = d["artifact"]
                if art:
                    d["artifact_summary"] = _extract_artifact_summary(art)
                out.append(d)
            return out
        finally:
            conn.close()


def _extract_artifact_summary(artifact: dict[str, Any] | None) -> str:
    """从 artifact 中提取简洁摘要文本"""
    if not artifact:
        return "（无产出）"
    parts = []
    if artifact.get("title"):
        parts.append(artifact["title"])
    if artifact.get("overview"):
        parts.append(artifact["overview"])
    if artifact.get("summary"):
        parts.append(artifact["summary"])
    if artifact.get("executive_summary"):
        parts.append(artifact["executive_summary"])
    if artifact.get("verdict"):
        parts.append(artifact["verdict"])
    if not parts:
        # 尝试从 design_doc 等嵌套结构中提取
        for key in ("design_doc", "comprehensive", "research_report", "business_report"):
            inner = artifact.get(key, {})
            if isinstance(inner, dict):
                if inner.get("title"):
                    parts.append(inner["title"])
                if inner.get("overview"):
                    parts.append(inner["overview"])
                if inner.get("summary"):
                    parts.append(inner["summary"])
                if parts:
                    break
    return " | ".join(parts) if parts else "（无产出摘要）"


# ---------- 标签 CRUD ----------


def list_all_tags() -> list[dict[str, Any]]:
    """列出所有标签及其使用次数，按使用次数降序排列"""
    with _lock:
        conn = _connect()
        try:
            rows = conn.execute(
                """SELECT tag, COUNT(*) as cnt, MAX(created_at) as last_used
                FROM meeting_tags
                GROUP BY tag
                ORDER BY cnt DESC, tag ASC"""
            ).fetchall()
            return [{"tag": r["tag"], "count": r["cnt"], "last_used": r["last_used"]} for r in rows]
        finally:
            conn.close()


def get_meeting_tags(meeting_id: str) -> list[str]:
    """取某会议的全部标签"""
    with _lock:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT tag FROM meeting_tags WHERE meeting_id = ? ORDER BY tag",
                (meeting_id,),
            ).fetchall()
            return [r["tag"] for r in rows]
        finally:
            conn.close()


def add_meeting_tag(meeting_id: str, tag: str) -> bool:
    """为会议添加标签。已存在则忽略（UNIQUE 约束）。返回是否新增。"""
    with _lock:
        conn = _connect()
        try:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO meeting_tags (meeting_id, tag, created_at) VALUES (?, ?, ?)",
                (meeting_id, tag, datetime.now().isoformat()),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()


def remove_meeting_tag(meeting_id: str, tag: str) -> bool:
    """移除会议的某个标签。返回是否删除了记录。"""
    with _lock:
        conn = _connect()
        try:
            cursor = conn.execute(
                "DELETE FROM meeting_tags WHERE meeting_id = ? AND tag = ?",
                (meeting_id, tag),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()


# ---------- 批量删除 ----------


def batch_delete_meetings(
    meeting_ids: list[str], mode: str = "soft"
) -> dict[str, list[str]]:
    """批量删除会议。

    - mode=soft：软删除，保留数据
    - mode=hard：硬删除，永久删除

    返回 {deleted: [...], failed: [...]}。
    running 状态的会议会被跳过并记入 failed。
    """
    deleted: list[str] = []
    failed: list[str] = []
    for mid in meeting_ids:
        if mode == "soft":
            ok = soft_delete_meeting(mid)
        elif mode == "hard":
            ok = hard_delete_meeting(mid)
        else:
            failed.append(mid)
            continue
        if ok:
            deleted.append(mid)
        else:
            failed.append(mid)
    return {"deleted": deleted, "failed": failed}


# ---------- 事件持久化 ----------

def save_event(
    meeting_id: str,
    event_type: str,
    payload: dict[str, Any],
    ts: str,
    trace_id: str | None = None,
) -> int:
    """持久化事件到 SQLite，返回自增 seq"""
    with _lock:
        conn = _connect()
        try:
            cursor = conn.execute(
                """INSERT INTO events (meeting_id, type, payload, ts, trace_id)
                VALUES (?, ?, ?, ?, ?)""",
                (
                    meeting_id,
                    event_type,
                    json.dumps(payload, ensure_ascii=False, default=str),
                    ts,
                    trace_id,
                ),
            )
            conn.commit()
            return cursor.lastrowid or 0
        finally:
            conn.close()


def load_events(meeting_id: str, from_seq: int = 0) -> list[dict[str, Any]]:
    """从 SQLite 加载事件，支持增量回放"""
    with _lock:
        conn = _connect()
        try:
            rows = conn.execute(
                """SELECT seq, meeting_id, type, payload, ts, trace_id
                FROM events WHERE meeting_id = ? AND seq > ?
                ORDER BY seq ASC""",
                (meeting_id, from_seq),
            ).fetchall()
            out = []
            for row in rows:
                out.append({
                    "seq": row["seq"],
                    "meeting_id": row["meeting_id"],
                    "type": row["type"],
                    "payload": json.loads(row["payload"]),
                    "ts": row["ts"],
                    "trace_id": row["trace_id"],
                })
            return out
        finally:
            conn.close()


def last_event_seq(meeting_id: str) -> int:
    """取某会议最后一条事件的 seq，无事件返回 0"""
    with _lock:
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT MAX(seq) as max_seq FROM events WHERE meeting_id = ?",
                (meeting_id,),
            ).fetchone()
            return row["max_seq"] if row and row["max_seq"] else 0
        finally:
            conn.close()


def recover_running_meetings() -> list[dict[str, Any]]:
    """查找状态为 running 的会议（用于崩溃恢复）"""
    with _lock:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT * FROM meetings WHERE status = 'running'"
            ).fetchall()
            return [dict(row) for row in rows]
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


# ---------- 会议删除 ----------


def soft_delete_meeting(meeting_id: str) -> bool:
    """软删除会议：将 status 标记为 'deleted'，保留全部数据用于回归。
    返回是否找到了记录并更新。"""
    with _lock:
        conn = _connect()
        try:
            # 先读取当前 payload
            row = conn.execute(
                "SELECT payload FROM meetings WHERE id = ?", (meeting_id,)
            ).fetchone()
            if row is None:
                return False
            payload = json.loads(row["payload"])
            payload["_deleted_at"] = datetime.now().isoformat()
            conn.execute(
                "UPDATE meetings SET status = 'deleted', payload = ? WHERE id = ?",
                (json.dumps(payload, ensure_ascii=False, default=str), meeting_id),
            )
            conn.commit()
            return True
        finally:
            conn.close()


def hard_delete_meeting(meeting_id: str) -> bool:
    """硬删除会议：永久删除 meetings、messages、events 表中该会议的全部记录。
    不可恢复，用于彻底清理。返回是否删除了主记录。"""
    with _lock:
        conn = _connect()
        try:
            # 先检查主记录是否存在
            row = conn.execute(
                "SELECT id FROM meetings WHERE id = ?", (meeting_id,)
            ).fetchone()
            if row is None:
                return False
            # 按依赖顺序删除：先 meeting_tags、messages（有外键），再 events，最后 meetings
            conn.execute("DELETE FROM meeting_tags WHERE meeting_id = ?", (meeting_id,))
            conn.execute("DELETE FROM messages WHERE meeting_id = ?", (meeting_id,))
            conn.execute("DELETE FROM events WHERE meeting_id = ?", (meeting_id,))
            conn.execute("DELETE FROM meetings WHERE id = ?", (meeting_id,))
            conn.commit()
            return True
        finally:
            conn.close()


def restore_meeting(meeting_id: str) -> bool:
    """恢复软删除的会议：将 status 从 'deleted' 恢复为 'aborted'。
    返回是否找到了记录并恢复。"""
    with _lock:
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT payload FROM meetings WHERE id = ? AND status = 'deleted'",
                (meeting_id,),
            ).fetchone()
            if row is None:
                return False
            payload = json.loads(row["payload"])
            payload.pop("_deleted_at", None)
            conn.execute(
                "UPDATE meetings SET status = 'aborted', payload = ? WHERE id = ?",
                (json.dumps(payload, ensure_ascii=False, default=str), meeting_id),
            )
            conn.commit()
            return True
        finally:
            conn.close()


# ---------- 用户偏好持久化 ----------


def get_preference(user_id: str, key: str) -> str | None:
    """取单条用户偏好，不存在返回 None"""
    with _lock:
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT value FROM user_preferences WHERE user_id = ? AND key = ?",
                (user_id, key),
            ).fetchone()
            return row["value"] if row else None
        finally:
            conn.close()


def set_preference(user_id: str, key: str, value: str) -> str:
    """upsert 用户偏好，返回写入的 updated_at"""
    updated_at = datetime.now().isoformat()
    with _lock:
        conn = _connect()
        try:
            conn.execute(
                """
                INSERT INTO user_preferences (user_id, key, value, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id, key) DO UPDATE SET
                    value=excluded.value,
                    updated_at=excluded.updated_at
                """,
                (user_id, key, value, updated_at),
            )
            conn.commit()
            return updated_at
        finally:
            conn.close()


def get_all_preferences(user_id: str) -> dict[str, str]:
    """取该用户全部偏好，返回 {key: value}"""
    with _lock:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT key, value FROM user_preferences WHERE user_id = ?",
                (user_id,),
            ).fetchall()
            return {row["key"]: row["value"] for row in rows}
        finally:
            conn.close()


def delete_preference(user_id: str, key: str) -> bool:
    """删除单条用户偏好，返回是否删除了记录"""
    with _lock:
        conn = _connect()
        try:
            cursor = conn.execute(
                "DELETE FROM user_preferences WHERE user_id = ? AND key = ?",
                (user_id, key),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()


# ---------- Agent 角色 CRUD ----------


def list_agent_roles(active_only: bool = False) -> list[dict[str, Any]]:
    """列出所有角色，可选仅活跃角色"""
    with _lock:
        conn = _connect()
        try:
            if active_only:
                rows = conn.execute(
                    "SELECT * FROM agent_roles WHERE is_active = 1 ORDER BY is_builtin DESC, display_name ASC"
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM agent_roles ORDER BY is_builtin DESC, display_name ASC"
                ).fetchall()
            return [_row_to_role_dict(r) for r in rows]
        finally:
            conn.close()


def get_agent_role(role_id: str) -> dict[str, Any] | None:
    """取单个角色"""
    with _lock:
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT * FROM agent_roles WHERE id = ?", (role_id,)
            ).fetchone()
            if row is None:
                return None
            return _row_to_role_dict(row)
        finally:
            conn.close()


def save_agent_role(role: dict[str, Any]) -> None:
    """upsert 角色"""
    with _lock:
        conn = _connect()
        try:
            conn.execute(
                """
                INSERT INTO agent_roles (
                    id, display_name, perspective, expertise_domains,
                    risk_appetite, default_stance, evidence_preference,
                    model_override, background_brief, prompt_template,
                    is_builtin, is_active, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    display_name=excluded.display_name,
                    perspective=excluded.perspective,
                    expertise_domains=excluded.expertise_domains,
                    risk_appetite=excluded.risk_appetite,
                    default_stance=excluded.default_stance,
                    evidence_preference=excluded.evidence_preference,
                    model_override=excluded.model_override,
                    background_brief=excluded.background_brief,
                    prompt_template=excluded.prompt_template,
                    is_active=excluded.is_active,
                    updated_at=excluded.updated_at
                """,
                (
                    role["id"],
                    role["display_name"],
                    role.get("perspective", ""),
                    json.dumps(role.get("expertise_domains", []), ensure_ascii=False),
                    role.get("risk_appetite", "balanced"),
                    role.get("default_stance", ""),
                    role.get("evidence_preference", "balanced"),
                    role.get("model_override", ""),
                    role.get("background_brief", ""),
                    role.get("prompt_template", ""),
                    role.get("is_builtin", 0),
                    role.get("is_active", 1),
                    role.get("created_at", ""),
                    role.get("updated_at", ""),
                ),
            )
            conn.commit()
        finally:
            conn.close()


def delete_agent_role(role_id: str) -> bool:
    """删除角色（内置角色不可删除）"""
    with _lock:
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT is_builtin FROM agent_roles WHERE id = ?", (role_id,)
            ).fetchone()
            if row is None:
                return False
            if row["is_builtin"]:
                return False
            conn.execute("DELETE FROM agent_roles WHERE id = ?", (role_id,))
            conn.commit()
            return True
        finally:
            conn.close()


def get_agent_roles_by_ids(role_ids: list[str]) -> list[dict[str, Any]]:
    """批量取角色，按输入顺序返回"""
    with _lock:
        conn = _connect()
        try:
            placeholders = ",".join("?" for _ in role_ids)
            rows = conn.execute(
                f"SELECT * FROM agent_roles WHERE id IN ({placeholders}) AND is_active = 1",
                role_ids,
            ).fetchall()
            role_map = {r["id"]: _row_to_role_dict(r) for r in rows}
            return [role_map[rid] for rid in role_ids if rid in role_map]
        finally:
            conn.close()


def _row_to_role_dict(row: sqlite3.Row) -> dict[str, Any]:
    """将 SQLite 行转为字典，解析 JSON 字段"""
    d = dict(row)
    d["expertise_domains"] = json.loads(d["expertise_domains"])
    return d
