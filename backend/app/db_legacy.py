# PostgreSQL 持久化：meetings / messages / events 等表
# 已从 psycopg2 同步连接池迁移到 SQLAlchemy async（app.db.engine.async_session_factory）
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import text, bindparam
from sqlalchemy.engine import RowMapping

from app.db.engine import async_session_factory, get_engine


async def close_db_pool() -> None:
    """关闭连接池，主要用于测试清理。"""
    engine = await get_engine()
    await engine.dispose()


async def init_db() -> None:
    """初始化所有 legacy 表。"""
    ddl_statements = [
        """
        CREATE TABLE IF NOT EXISTS meetings (
            id TEXT PRIMARY KEY,
            topic TEXT NOT NULL,
            status TEXT NOT NULL,
            stage TEXT NOT NULL,
            created_at TEXT NOT NULL,
            payload TEXT NOT NULL
        )
        """,
        """
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
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_messages_meeting ON messages(meeting_id)",
        """
        CREATE TABLE IF NOT EXISTS events (
            seq SERIAL PRIMARY KEY,
            meeting_id TEXT NOT NULL,
            type TEXT NOT NULL,
            payload TEXT NOT NULL,
            ts TEXT NOT NULL,
            trace_id TEXT
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_events_meeting ON events(meeting_id)",
        "CREATE INDEX IF NOT EXISTS idx_events_meeting_seq ON events(meeting_id, seq)",
        """
        CREATE TABLE IF NOT EXISTS user_preferences (
            user_id TEXT NOT NULL DEFAULT 'default',
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (user_id, key)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS meeting_tags (
            id SERIAL PRIMARY KEY,
            meeting_id TEXT NOT NULL,
            tag TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(meeting_id, tag),
            FOREIGN KEY (meeting_id) REFERENCES meetings(id) ON DELETE CASCADE
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_meeting_tags_meeting ON meeting_tags(meeting_id)",
        "CREATE INDEX IF NOT EXISTS idx_meeting_tags_tag ON meeting_tags(tag)",
        """
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
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_agent_roles_active ON agent_roles(is_active)",
        """
        CREATE TABLE IF NOT EXISTS meeting_aux (
            meeting_id TEXT NOT NULL,
            key TEXT NOT NULL,
            value_json TEXT NOT NULL DEFAULT '{}',
            updated_at TEXT NOT NULL,
            PRIMARY KEY (meeting_id, key),
            FOREIGN KEY (meeting_id) REFERENCES meetings(id) ON DELETE CASCADE
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_meeting_aux_meeting ON meeting_aux(meeting_id)",
    ]
    async with async_session_factory() as session:
        for stmt in ddl_statements:
            await session.execute(text(stmt))
        await session.commit()


async def save_meeting(
    meeting_id: str,
    topic: str,
    status: str,
    stage: str,
    created_at: datetime,
    payload: dict[str, Any],
) -> None:
    """upsert 会议记录，payload 存 JSON"""
    async with async_session_factory() as session:
        await session.execute(
            text(
                """
                INSERT INTO meetings (id, topic, status, stage, created_at, payload)
                VALUES (:meeting_id, :topic, :status, :stage, :created_at, :payload)
                ON CONFLICT(id) DO UPDATE SET
                    topic=excluded.topic,
                    status=excluded.status,
                    stage=excluded.stage,
                    payload=excluded.payload
                """
            ),
            {
                "meeting_id": meeting_id,
                "topic": topic,
                "status": status,
                "stage": stage,
                "created_at": created_at.isoformat(),
                "payload": json.dumps(payload, ensure_ascii=False, default=str),
            },
        )
        await session.commit()


async def get_meeting(meeting_id: str) -> dict[str, Any] | None:
    """取单条会议记录"""
    async with async_session_factory() as session:
        result = await session.execute(
            text("SELECT * FROM meetings WHERE id = :meeting_id"),
            {"meeting_id": meeting_id},
        )
        row = result.mappings().first()
        if row is None:
            return None
        d = dict(row)
        d["payload"] = json.loads(d["payload"])
        return d


# ---------- meeting_aux 辅助大字段持久化 ----------

# 需要从 payload 中分离的 aux 字段名列表
_AUX_KEYS = ("llm_trace", "evidence_set", "conclusion_chain", "borrowed_agents")


async def save_meeting_aux(meeting_id: str, aux: dict[str, Any]) -> None:
    """将 aux 大字段单独持久化到 meeting_aux 表。

    每个 aux key 对应一行，value_json 存 JSON 序列化后的值。
    使用 INSERT ... ON CONFLICT DO UPDATE 实现 upsert。

    Args:
        meeting_id: 会议 ID
        aux: extract_aux() 返回的 dict，key 为字段名，value 为可 JSON 序列化的值
    """
    if not aux:
        return
    now = datetime.now().isoformat()
    async with async_session_factory() as session:
        for key, value in aux.items():
            await session.execute(
                text(
                    """
                    INSERT INTO meeting_aux (meeting_id, key, value_json, updated_at)
                    VALUES (:meeting_id, :key, :value_json, :updated_at)
                    ON CONFLICT(meeting_id, key) DO UPDATE SET
                        value_json=excluded.value_json,
                        updated_at=excluded.updated_at
                    """
                ),
                {
                    "meeting_id": meeting_id,
                    "key": key,
                    "value_json": json.dumps(value, ensure_ascii=False, default=str),
                    "updated_at": now,
                },
            )
        await session.commit()


async def get_meeting_aux(meeting_id: str) -> dict[str, Any]:
    """从 meeting_aux 表加载某会议的全部辅助大字段。

    向后兼容：如果 meeting_aux 表不存在或该会议无 aux 数据，返回空 dict。

    Args:
        meeting_id: 会议 ID

    Returns:
        dict，key 为字段名，value 为反序列化后的值。可能为空 dict。
    """
    aux: dict[str, Any] = {}
    try:
        async with async_session_factory() as session:
            result = await session.execute(
                text("SELECT key, value_json FROM meeting_aux WHERE meeting_id = :meeting_id"),
                {"meeting_id": meeting_id},
            )
            rows = result.mappings().all()
            for row in rows:
                try:
                    aux[row["key"]] = json.loads(row["value_json"])
                except (json.JSONDecodeError, KeyError):
                    pass  # 损坏的 aux 数据跳过，不影响主流程
    except Exception:
        # 表可能不存在（旧数据库），静默返回空 dict
        pass
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


async def list_meetings(include_deleted: bool = False) -> list[dict[str, Any]]:
    """列出全部会议。默认排除软删除（status='deleted'）的记录。"""
    async with async_session_factory() as session:
        if include_deleted:
            result = await session.execute(
                text("SELECT * FROM meetings ORDER BY created_at DESC")
            )
        else:
            result = await session.execute(
                text("SELECT * FROM meetings WHERE status != 'deleted' ORDER BY created_at DESC")
            )
        rows = result.mappings().all()
        out = []
        for row in rows:
            d = dict(row)
            d["payload"] = json.loads(d["payload"])
            out.append(d)
        return out


async def query_meetings(
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
    async with async_session_factory() as session:
        conditions: list[str] = []
        params: dict[str, Any] = {}

        if not include_deleted:
            conditions.append("m.status != 'deleted'")

        if q:
            conditions.append("m.topic LIKE :q")
            params["q"] = f"%{q}%"

        if tags:
            # 交集过滤：会议需同时拥有所有指定标签
            conditions.append(
                "m.id IN (SELECT meeting_id FROM meeting_tags "
                "WHERE tag IN :tags "
                "GROUP BY meeting_id HAVING COUNT(DISTINCT tag) = :tag_count)"
            )
            params["tags"] = tags
            params["tag_count"] = len(tags)

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        # 总数
        count_sql = f"SELECT COUNT(*) as cnt FROM meetings m {where_clause}"
        count_stmt = text(count_sql)
        if tags:
            count_stmt = count_stmt.bindparams(bindparam("tags", expanding=True))
        count_result = await session.execute(count_stmt, params)
        total_row = count_result.mappings().first()
        total = total_row["cnt"] if total_row else 0

        # 分页查询
        list_sql = (
            f"SELECT m.* FROM meetings m {where_clause} "
            "ORDER BY m.created_at DESC "
            "LIMIT CAST(:limit AS INTEGER) OFFSET CAST(:offset AS INTEGER)"
        )
        list_stmt = text(list_sql)
        if tags:
            list_stmt = list_stmt.bindparams(bindparam("tags", expanding=True))
        list_params = {**params, "limit": limit, "offset": offset}
        list_result = await session.execute(list_stmt, list_params)
        rows = list_result.mappings().all()

        items = []
        for row in rows:
            d = dict(row)
            d["payload"] = json.loads(d["payload"])
            # 查询该会议的标签
            tag_result = await session.execute(
                text("SELECT tag FROM meeting_tags WHERE meeting_id = :meeting_id ORDER BY tag"),
                {"meeting_id": d["id"]},
            )
            tag_rows = tag_result.mappings().all()
            d["tags"] = [r["tag"] for r in tag_rows]
            items.append(d)

        return {"items": items, "total": total}


async def get_meetings_by_ids(meeting_ids: list[str]) -> list[dict[str, Any]]:
    """批量获取会议记录（用于历史会议引用）。

    返回已完成的会议摘要列表，包含 topic、stage、status、artifact 摘要。
    不包含运行中的会议（status='running'），也不包含已删除的会议。
    """
    if not meeting_ids:
        return []
    async with async_session_factory() as session:
        stmt = text(
            "SELECT id, topic, status, stage, created_at, payload "
            "FROM meetings WHERE id IN :meeting_ids "
            "AND status NOT IN ('deleted', 'running') "
            "ORDER BY created_at DESC"
        ).bindparams(bindparam("meeting_ids", expanding=True))
        result = await session.execute(stmt, {"meeting_ids": meeting_ids})
        rows = result.mappings().all()
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


async def list_all_tags() -> list[dict[str, Any]]:
    """列出所有标签及其使用次数，按使用次数降序排列"""
    async with async_session_factory() as session:
        result = await session.execute(
            text(
                """SELECT tag, COUNT(*) as cnt, MAX(created_at) as last_used
                FROM meeting_tags
                GROUP BY tag
                ORDER BY cnt DESC, tag ASC"""
            )
        )
        rows = result.mappings().all()
        return [{"tag": r["tag"], "count": r["cnt"], "last_used": r["last_used"]} for r in rows]


async def get_meeting_tags(meeting_id: str) -> list[str]:
    """取某会议的全部标签"""
    async with async_session_factory() as session:
        result = await session.execute(
            text("SELECT tag FROM meeting_tags WHERE meeting_id = :meeting_id ORDER BY tag"),
            {"meeting_id": meeting_id},
        )
        rows = result.mappings().all()
        return [r["tag"] for r in rows]


async def add_meeting_tag(meeting_id: str, tag: str) -> bool:
    """为会议添加标签。已存在则忽略（UNIQUE 约束）。返回是否新增。"""
    async with async_session_factory() as session:
        result = await session.execute(
            text(
                """INSERT INTO meeting_tags (meeting_id, tag, created_at)
                VALUES (:meeting_id, :tag, :created_at)
                ON CONFLICT(meeting_id, tag) DO NOTHING"""
            ),
            {
                "meeting_id": meeting_id,
                "tag": tag,
                "created_at": datetime.now().isoformat(),
            },
        )
        await session.commit()
        return result.rowcount > 0


async def remove_meeting_tag(meeting_id: str, tag: str) -> bool:
    """移除会议的某个标签。返回是否删除了记录。"""
    async with async_session_factory() as session:
        result = await session.execute(
            text("DELETE FROM meeting_tags WHERE meeting_id = :meeting_id AND tag = :tag"),
            {"meeting_id": meeting_id, "tag": tag},
        )
        await session.commit()
        return result.rowcount > 0


# ---------- 批量删除 ----------


async def batch_delete_meetings(
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
            ok = await soft_delete_meeting(mid)
        elif mode == "hard":
            ok = await hard_delete_meeting(mid)
        else:
            failed.append(mid)
            continue
        if ok:
            deleted.append(mid)
        else:
            failed.append(mid)
    return {"deleted": deleted, "failed": failed}


# ---------- 事件持久化 ----------


async def save_event(
    meeting_id: str,
    event_type: str,
    payload: dict[str, Any],
    ts: str,
    trace_id: str | None = None,
) -> int:
    """持久化事件到 PostgreSQL，返回自增 seq（对外 0 起始）"""
    async with async_session_factory() as session:
        result = await session.execute(
            text(
                """INSERT INTO events (meeting_id, type, payload, ts, trace_id)
                VALUES (:meeting_id, :event_type, :payload, :ts, :trace_id)
                RETURNING seq"""
            ),
            {
                "meeting_id": meeting_id,
                "event_type": event_type,
                "payload": json.dumps(payload, ensure_ascii=False, default=str),
                "ts": ts,
                "trace_id": trace_id,
            },
        )
        # PostgreSQL SERIAL 从 1 开始；对外统一转换为 0 起始
        seq = result.scalars().first()
        await session.commit()
        if seq is None:
            seq = 1
        return seq - 1


async def load_events(meeting_id: str, from_seq: int = 0, limit: int = 0) -> list[dict[str, Any]]:
    """从 PostgreSQL 加载事件，支持增量回放。
    limit=0 表示不限制（增量回放场景）；全量恢复时应传 limit 防止内存暴涨。
    """
    async with async_session_factory() as session:
        if limit > 0 and from_seq == 0:
            # 全量恢复：取最近N条（子查询倒序取后再正序排列）
            result = await session.execute(
                text(
                    """SELECT seq, meeting_id, type, payload, ts, trace_id FROM (
                        SELECT seq, meeting_id, type, payload, ts, trace_id
                        FROM events WHERE meeting_id = :meeting_id AND seq > :from_seq
                        ORDER BY seq DESC LIMIT CAST(:limit AS INTEGER)
                    ) t ORDER BY seq ASC"""
                ),
                {"meeting_id": meeting_id, "from_seq": from_seq, "limit": limit},
            )
        else:
            result = await session.execute(
                text(
                    """SELECT seq, meeting_id, type, payload, ts, trace_id
                    FROM events WHERE meeting_id = :meeting_id AND seq > :from_seq
                    ORDER BY seq ASC"""
                ),
                {"meeting_id": meeting_id, "from_seq": from_seq},
            )
        rows = result.mappings().all()
        out = []
        for row in rows:
            out.append({
                "seq": row["seq"] - 1,
                "meeting_id": row["meeting_id"],
                "type": row["type"],
                "payload": json.loads(row["payload"]),
                "ts": row["ts"],
                "trace_id": row["trace_id"],
            })
        return out


async def last_event_seq(meeting_id: str) -> int:
    """取某会议最后一条事件的 seq（对外 0 起始），无事件返回 0"""
    async with async_session_factory() as session:
        result = await session.execute(
            text("SELECT MAX(seq) as max_seq FROM events WHERE meeting_id = :meeting_id"),
            {"meeting_id": meeting_id},
        )
        row = result.mappings().first()
        return (row["max_seq"] - 1) if row and row["max_seq"] else 0


async def recover_running_meetings() -> list[dict[str, Any]]:
    """查找状态为 running 的会议（用于崩溃恢复）"""
    async with async_session_factory() as session:
        result = await session.execute(
            text("SELECT * FROM meetings WHERE status = 'running'")
        )
        rows = result.mappings().all()
        return [dict(row) for row in rows]


async def save_message(msg: dict[str, Any]) -> None:
    """保存发言记录"""
    async with async_session_factory() as session:
        await session.execute(
            text(
                """
                INSERT INTO messages
                (id, meeting_id, agent_role, stage, content, claim_refs, evidence_refs, created_at)
                VALUES (:id, :meeting_id, :agent_role, :stage, :content, :claim_refs, :evidence_refs, :created_at)
                ON CONFLICT(id) DO UPDATE SET
                    meeting_id=excluded.meeting_id,
                    agent_role=excluded.agent_role,
                    stage=excluded.stage,
                    content=excluded.content,
                    claim_refs=excluded.claim_refs,
                    evidence_refs=excluded.evidence_refs,
                    created_at=excluded.created_at
                """
            ),
            {
                "id": msg["id"],
                "meeting_id": msg["meeting_id"],
                "agent_role": msg["agent_role"],
                "stage": msg["stage"],
                "content": msg["content"],
                "claim_refs": json.dumps(msg.get("claim_refs", []), ensure_ascii=False),
                "evidence_refs": json.dumps(msg.get("evidence_refs", []), ensure_ascii=False),
                "created_at": msg["created_at"],
            },
        )
        await session.commit()


async def list_messages(meeting_id: str) -> list[dict[str, Any]]:
    """取某会议的全部发言"""
    async with async_session_factory() as session:
        result = await session.execute(
            text("SELECT * FROM messages WHERE meeting_id = :meeting_id ORDER BY created_at ASC"),
            {"meeting_id": meeting_id},
        )
        rows = result.mappings().all()
        out = []
        for row in rows:
            d = dict(row)
            d["claim_refs"] = json.loads(d["claim_refs"])
            d["evidence_refs"] = json.loads(d["evidence_refs"])
            out.append(d)
        return out


# ---------- 会议删除 ----------


async def soft_delete_meeting(meeting_id: str) -> bool:
    """软删除会议：将 status 标记为 'deleted'，保留全部数据用于回归。
    返回是否找到了记录并更新。"""
    async with async_session_factory() as session:
        # 先读取当前 payload
        result = await session.execute(
            text("SELECT payload FROM meetings WHERE id = :meeting_id"),
            {"meeting_id": meeting_id},
        )
        row = result.mappings().first()
        if row is None:
            return False
        payload = json.loads(row["payload"])
        payload["_deleted_at"] = datetime.now().isoformat()
        await session.execute(
            text("UPDATE meetings SET status = 'deleted', payload = :payload WHERE id = :meeting_id"),
            {
                "payload": json.dumps(payload, ensure_ascii=False, default=str),
                "meeting_id": meeting_id,
            },
        )
        await session.commit()
        return True


async def hard_delete_meeting(meeting_id: str) -> bool:
    """硬删除会议：永久删除 meetings、messages、events 表中该会议的全部记录。
    不可恢复，用于彻底清理。返回是否删除了主记录。"""
    async with async_session_factory() as session:
        # 先检查主记录是否存在
        result = await session.execute(
            text("SELECT id FROM meetings WHERE id = :meeting_id"),
            {"meeting_id": meeting_id},
        )
        row = result.mappings().first()
        if row is None:
            return False
        # 按依赖顺序删除：先 meeting_tags、messages（有外键），再 events，最后 meetings
        await session.execute(
            text("DELETE FROM meeting_tags WHERE meeting_id = :meeting_id"),
            {"meeting_id": meeting_id},
        )
        await session.execute(
            text("DELETE FROM messages WHERE meeting_id = :meeting_id"),
            {"meeting_id": meeting_id},
        )
        await session.execute(
            text("DELETE FROM events WHERE meeting_id = :meeting_id"),
            {"meeting_id": meeting_id},
        )
        await session.execute(
            text("DELETE FROM meetings WHERE id = :meeting_id"),
            {"meeting_id": meeting_id},
        )
        await session.commit()
        return True


async def restore_meeting(meeting_id: str) -> bool:
    """恢复软删除的会议：将 status 从 'deleted' 恢复为 'aborted'。
    返回是否找到了记录并恢复。"""
    async with async_session_factory() as session:
        result = await session.execute(
            text("SELECT payload FROM meetings WHERE id = :meeting_id AND status = 'deleted'"),
            {"meeting_id": meeting_id},
        )
        row = result.mappings().first()
        if row is None:
            return False
        payload = json.loads(row["payload"])
        payload.pop("_deleted_at", None)
        await session.execute(
            text("UPDATE meetings SET status = 'aborted', payload = :payload WHERE id = :meeting_id"),
            {
                "payload": json.dumps(payload, ensure_ascii=False, default=str),
                "meeting_id": meeting_id,
            },
        )
        await session.commit()
        return True


# ---------- 用户偏好持久化 ----------


async def get_preference(user_id: str, key: str) -> str | None:
    """取单条用户偏好，不存在返回 None"""
    async with async_session_factory() as session:
        result = await session.execute(
            text("SELECT value FROM user_preferences WHERE user_id = :user_id AND key = :key"),
            {"user_id": user_id, "key": key},
        )
        row = result.mappings().first()
        return row["value"] if row else None


async def set_preference(user_id: str, key: str, value: str) -> str:
    """upsert 用户偏好，返回写入的 updated_at"""
    updated_at = datetime.now().isoformat()
    async with async_session_factory() as session:
        await session.execute(
            text(
                """
                INSERT INTO user_preferences (user_id, key, value, updated_at)
                VALUES (:user_id, :key, :value, :updated_at)
                ON CONFLICT(user_id, key) DO UPDATE SET
                    value=excluded.value,
                    updated_at=excluded.updated_at
                """
            ),
            {
                "user_id": user_id,
                "key": key,
                "value": value,
                "updated_at": updated_at,
            },
        )
        await session.commit()
        return updated_at


async def get_all_preferences(user_id: str) -> dict[str, str]:
    """取该用户全部偏好，返回 {key: value}"""
    async with async_session_factory() as session:
        result = await session.execute(
            text("SELECT key, value FROM user_preferences WHERE user_id = :user_id"),
            {"user_id": user_id},
        )
        rows = result.mappings().all()
        return {row["key"]: row["value"] for row in rows}


async def delete_preference(user_id: str, key: str) -> bool:
    """删除单条用户偏好，返回是否删除了记录"""
    async with async_session_factory() as session:
        result = await session.execute(
            text("DELETE FROM user_preferences WHERE user_id = :user_id AND key = :key"),
            {"user_id": user_id, "key": key},
        )
        await session.commit()
        return result.rowcount > 0


# ---------- Agent 角色 CRUD ----------


async def list_agent_roles(active_only: bool = False) -> list[dict[str, Any]]:
    """列出所有角色，可选仅活跃角色"""
    async with async_session_factory() as session:
        if active_only:
            result = await session.execute(
                text(
                    "SELECT * FROM agent_roles WHERE is_active = 1 "
                    "ORDER BY is_builtin DESC, display_name ASC"
                )
            )
        else:
            result = await session.execute(
                text("SELECT * FROM agent_roles ORDER BY is_builtin DESC, display_name ASC")
            )
        rows = result.mappings().all()
        return [_row_to_role_dict(r) for r in rows]


async def get_agent_role(role_id: str) -> dict[str, Any] | None:
    """取单个角色"""
    async with async_session_factory() as session:
        result = await session.execute(
            text("SELECT * FROM agent_roles WHERE id = :role_id"),
            {"role_id": role_id},
        )
        row = result.mappings().first()
        if row is None:
            return None
        return _row_to_role_dict(row)


async def save_agent_role(role: dict[str, Any]) -> None:
    """upsert 角色"""
    async with async_session_factory() as session:
        await session.execute(
            text(
                """
                INSERT INTO agent_roles (
                    id, display_name, perspective, expertise_domains,
                    risk_appetite, default_stance, evidence_preference,
                    model_override, background_brief, prompt_template,
                    is_builtin, is_active, created_at, updated_at
                ) VALUES (
                    :id, :display_name, :perspective, :expertise_domains,
                    :risk_appetite, :default_stance, :evidence_preference,
                    :model_override, :background_brief, :prompt_template,
                    :is_builtin, :is_active, :created_at, :updated_at
                )
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
                """
            ),
            {
                "id": role["id"],
                "display_name": role["display_name"],
                "perspective": role.get("perspective", ""),
                "expertise_domains": json.dumps(role.get("expertise_domains", []), ensure_ascii=False),
                "risk_appetite": role.get("risk_appetite", "balanced"),
                "default_stance": role.get("default_stance", ""),
                "evidence_preference": role.get("evidence_preference", "balanced"),
                "model_override": role.get("model_override", ""),
                "background_brief": role.get("background_brief", ""),
                "prompt_template": role.get("prompt_template", ""),
                "is_builtin": role.get("is_builtin", 0),
                "is_active": role.get("is_active", 1),
                "created_at": role.get("created_at", ""),
                "updated_at": role.get("updated_at", ""),
            },
        )
        await session.commit()


async def delete_agent_role(role_id: str) -> bool:
    """删除角色（内置角色不可删除）"""
    async with async_session_factory() as session:
        result = await session.execute(
            text("SELECT is_builtin FROM agent_roles WHERE id = :role_id"),
            {"role_id": role_id},
        )
        row = result.mappings().first()
        if row is None:
            return False
        if row["is_builtin"]:
            return False
        await session.execute(
            text("DELETE FROM agent_roles WHERE id = :role_id"),
            {"role_id": role_id},
        )
        await session.commit()
        return True


async def get_agent_roles_by_ids(role_ids: list[str]) -> list[dict[str, Any]]:
    """批量取角色，按输入顺序返回"""
    if not role_ids:
        return []
    async with async_session_factory() as session:
        stmt = text(
            "SELECT * FROM agent_roles WHERE id IN :role_ids AND is_active = 1"
        ).bindparams(bindparam("role_ids", expanding=True))
        result = await session.execute(stmt, {"role_ids": role_ids})
        rows = result.mappings().all()
        role_map = {r["id"]: _row_to_role_dict(r) for r in rows}
        return [role_map[rid] for rid in role_ids if rid in role_map]


def _row_to_role_dict(row: RowMapping) -> dict[str, Any]:
    """将 SQLAlchemy RowMapping 转为字典，解析 JSON 字段"""
    d = dict(row)
    d["expertise_domains"] = json.loads(d["expertise_domains"])
    return d
