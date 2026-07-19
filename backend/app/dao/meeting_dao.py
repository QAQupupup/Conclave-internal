"""会议 CRUD 与批量删除。

包含会议的增删改查、批量删除（软/硬删除）、崩溃恢复以及产出摘要提取。
batch_delete_meetings 内部调用本文件内的 soft_delete_meeting / hard_delete_meeting，
无需跨文件 import。
原迁移自 app/db_legacy.py，逻辑未做任何修改。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import bindparam, text

from app.db.engine import async_session_factory


async def save_meeting(
    meeting_id: str,
    topic: str,
    status: str,
    stage: str,
    created_at: datetime,
    payload: dict[str, Any],
    owner_username: str | None = None,
) -> None:
    """upsert 会议记录，payload 存 JSON"""
    async with async_session_factory() as session:
        if owner_username is not None:
            await session.execute(
                text(
                    """
                    INSERT INTO meetings (id, topic, owner_username, status, stage, created_at, payload)
                    VALUES (:meeting_id, :topic, :owner_username, :status, :stage, :created_at, :payload)
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
                    "owner_username": owner_username,
                    "status": status,
                    "stage": stage,
                    "created_at": created_at.isoformat(),
                    "payload": json.dumps(payload, ensure_ascii=False, default=str),
                },
            )
        else:
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


async def list_meetings(include_deleted: bool = False) -> list[dict[str, Any]]:
    """列出全部会议。默认排除软删除（status='deleted'）的记录。"""
    async with async_session_factory() as session:
        if include_deleted:
            result = await session.execute(text("SELECT * FROM meetings ORDER BY created_at DESC"))
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


async def recover_running_meetings() -> list[dict[str, Any]]:
    """查找状态为 running 的会议（用于崩溃恢复）"""
    async with async_session_factory() as session:
        result = await session.execute(text("SELECT * FROM meetings WHERE status = 'running'"))
        rows = result.mappings().all()
        return [dict(row) for row in rows]


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


async def batch_delete_meetings(meeting_ids: list[str], mode: str = "soft") -> dict[str, list[str]]:
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
