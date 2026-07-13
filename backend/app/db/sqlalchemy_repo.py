"""SQLAlchemy Repository 实现。

实现所有 Repository ABC 接口，基于 SQLAlchemy 2.0 async ORM。
同时支持 PostgreSQL 和 SQLite 双后端（由 DATABASE_URL 决定）。

所有 SQL 通过 SQLAlchemy ORM / Core Expression 构建，不写原生 SQL 字符串，
确保未来迁移到 OceanBase MySQL 模式时只需改连接串。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, func, delete, update, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    MeetingModel, MessageModel, EventModel, MeetingTagModel,
    AgentRoleModel, UserPreferenceModel, NetAuthRequestModel,
)
from app.db.mapper import (
    meeting_row_to_dict, meeting_to_orm_values,
    message_row_to_dict, message_to_orm_values,
    event_row_to_dict,
    agent_role_row_to_dict, agent_role_to_orm_values,
    net_auth_row_to_dict,
    CURRENT_SCHEMA_VERSION,
)
from app.db.repository import (
    MeetingRepository, MessageRepository, EventRepository,
    TagRepository, PreferenceRepository, AgentRoleRepository,
    NetAuthRepository,
)


class SqlAlchemyMeetingRepo(MeetingRepository):
    """SQLAlchemy 实现：会议 CRUD"""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ── save ──
    async def save(self, meeting_id: str, topic: str, status: str,
                   stage: str, created_at: datetime, payload: dict[str, Any],
                   schema_version: int = CURRENT_SCHEMA_VERSION) -> None:
        values = meeting_to_orm_values(
            meeting_id, topic, status, stage, created_at, payload, schema_version,
        )
        # [CON-16 修复] 使用方言感知的 upsert 工厂
        # 旧版硬编码走 PostgreSQL dialect，SQLite 模式下会因编译器不匹配产生隐性错误
        from app.db.upsert import dialect_upsert

        stmt = dialect_upsert(
            self.db,
            MeetingModel,
            values,
            index_elements=["id"],
            set_={
                "topic": values["topic"],
                "status": values["status"],
                "stage": values["stage"],
                "payload": values["payload"],
                "schema_version": values["schema_version"],
            },
        )
        await self.db.execute(stmt)

    # ── get ──
    async def get(self, meeting_id: str) -> dict[str, Any] | None:
        result = await self.db.execute(
            select(MeetingModel).where(MeetingModel.id == meeting_id)
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return meeting_row_to_dict(row)

    # ── list ──
    async def list(self, include_deleted: bool = False) -> list[dict[str, Any]]:
        stmt = select(MeetingModel).order_by(MeetingModel.created_at.desc())
        if not include_deleted:
            stmt = stmt.where(MeetingModel.status != "deleted")
        result = await self.db.execute(stmt)
        return [meeting_row_to_dict(r) for r in result.scalars().all()]

    # ── query ──
    async def query(self, q: str | None = None, limit: int = 20,
                    offset: int = 0, tags: list[str] | None = None,
                    include_deleted: bool = False) -> dict[str, Any]:
        conditions = []
        if not include_deleted:
            conditions.append(MeetingModel.status != "deleted")
        if q:
            conditions.append(MeetingModel.topic.ilike(f"%{q}%"))
        if tags:
            # 交集过滤：会议需同时拥有所有指定标签
            tag_subquery = (
                select(MeetingTagModel.meeting_id)
                .where(MeetingTagModel.tag.in_(tags))
                .group_by(MeetingTagModel.meeting_id)
                .having(func.count(func.distinct(MeetingTagModel.tag)) == len(tags))
            ).subquery()
            conditions.append(MeetingModel.id.in_(select(tag_subquery)))

        base_stmt = select(MeetingModel)
        if conditions:
            base_stmt = base_stmt.where(and_(*conditions))

        # 总数
        count_stmt = select(func.count()).select_from(base_stmt.subquery())
        total_result = await self.db.execute(count_stmt)
        total = total_result.scalar() or 0

        # 分页
        page_stmt = base_stmt.order_by(MeetingModel.created_at.desc()).limit(limit).offset(offset)
        result = await self.db.execute(page_stmt)
        items = []
        for row in result.scalars().all():
            d = meeting_row_to_dict(row)
            # 查询标签
            tag_rows = await self.db.execute(
                select(MeetingTagModel.tag)
                .where(MeetingTagModel.meeting_id == row.id)
                .order_by(MeetingTagModel.tag)
            )
            d["tags"] = list(tag_rows.scalars().all())
            items.append(d)

        return {"items": items, "total": total}

    # ── get_by_ids ──
    async def get_by_ids(self, meeting_ids: list[str]) -> list[dict[str, Any]]:
        if not meeting_ids:
            return []
        result = await self.db.execute(
            select(MeetingModel)
            .where(
                MeetingModel.id.in_(meeting_ids),
                MeetingModel.status.notin_(["deleted", "running"]),
            )
            .order_by(MeetingModel.created_at.desc())
        )
        out = []
        for row in result.scalars().all():
            d = meeting_row_to_dict(row)
            payload = d["payload"]
            d["clarified_topic"] = payload.get("clarified_topic", d["topic"])
            d["key_questions"] = payload.get("key_questions", [])
            d["artifact"] = payload.get("artifact")
            d["decision_record"] = payload.get("decision_record")
            d["flow_plan"] = payload.get("flow_plan", "full")
            art = d["artifact"]
            if art:
                d["artifact_summary"] = _extract_artifact_summary(art)
            out.append(d)
        return out

    # ── soft_delete ──
    async def soft_delete(self, meeting_id: str) -> bool:
        result = await self.db.execute(
            select(MeetingModel).where(MeetingModel.id == meeting_id)
        )
        row = result.scalar_one_or_none()
        if row is None:
            return False
        payload = json.loads(row.payload)
        payload["_deleted_at"] = datetime.now(timezone.utc).isoformat()
        await self.db.execute(
            update(MeetingModel)
            .where(MeetingModel.id == meeting_id)
            .values(
                status="deleted",
                payload=json.dumps(payload, ensure_ascii=False, default=str),
            )
        )
        return True

    # ── hard_delete ──
    async def hard_delete(self, meeting_id: str) -> bool:
        result = await self.db.execute(
            select(MeetingModel.id).where(MeetingModel.id == meeting_id)
        )
        if result.scalar_one_or_none() is None:
            return False
        # 级联删除由 ORM relationship cascade 处理
        await self.db.execute(
            delete(MeetingModel).where(MeetingModel.id == meeting_id)
        )
        return True

    # ── restore ──
    async def restore(self, meeting_id: str) -> bool:
        result = await self.db.execute(
            select(MeetingModel).where(
                MeetingModel.id == meeting_id,
                MeetingModel.status == "deleted",
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            return False
        payload = json.loads(row.payload)
        payload.pop("_deleted_at", None)
        await self.db.execute(
            update(MeetingModel)
            .where(MeetingModel.id == meeting_id)
            .values(
                status="aborted",
                payload=json.dumps(payload, ensure_ascii=False, default=str),
            )
        )
        return True

    # ── recover_running ──
    async def recover_running(self) -> list[dict[str, Any]]:
        result = await self.db.execute(
            select(MeetingModel).where(MeetingModel.status == "running")
        )
        return [meeting_row_to_dict(r) for r in result.scalars().all()]


class SqlAlchemyMessageRepo(MessageRepository):
    """SQLAlchemy 实现：发言记录"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def save(self, msg: dict[str, Any]) -> None:
        # [CON-16 修复] 使用方言感知 upsert
        from app.db.upsert import dialect_upsert

        values = message_to_orm_values(msg)
        stmt = dialect_upsert(
            self.db,
            MessageModel,
            values,
            index_elements=["id"],
            set_={
                "agent_role": values["agent_role"],
                "stage": values["stage"],
                "content": values["content"],
                "claim_refs": values["claim_refs"],
                "evidence_refs": values["evidence_refs"],
            },
        )
        await self.db.execute(stmt)

    async def list_by_meeting(self, meeting_id: str) -> list[dict[str, Any]]:
        result = await self.db.execute(
            select(MessageModel)
            .where(MessageModel.meeting_id == meeting_id)
            .order_by(MessageModel.created_at.asc())
        )
        return [message_row_to_dict(r) for r in result.scalars().all()]


class SqlAlchemyEventRepo(EventRepository):
    """SQLAlchemy 实现：事件溯源"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def save(self, meeting_id: str, event_type: str,
                   payload: dict[str, Any], ts: str,
                   trace_id: str | None = None) -> int:
        event = EventModel(
            meeting_id=meeting_id,
            type=event_type,
            payload=json.dumps(payload, ensure_ascii=False, default=str),
            ts=datetime.fromisoformat(ts) if ts else datetime.now(timezone.utc),
            trace_id=trace_id,
        )
        self.db.add(event)
        await self.db.flush()
        return event.seq

    async def load(self, meeting_id: str, from_seq: int = 0) -> list[dict[str, Any]]:
        result = await self.db.execute(
            select(EventModel)
            .where(
                EventModel.meeting_id == meeting_id,
                EventModel.seq > from_seq,
            )
            .order_by(EventModel.seq.asc())
        )
        return [event_row_to_dict(r) for r in result.scalars().all()]

    async def last_seq(self, meeting_id: str) -> int:
        result = await self.db.execute(
            select(func.max(EventModel.seq))
            .where(EventModel.meeting_id == meeting_id)
        )
        val = result.scalar()
        return val if val else 0


class SqlAlchemyTagRepo(TagRepository):
    """SQLAlchemy 实现：标签"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_all(self) -> list[dict[str, Any]]:
        result = await self.db.execute(
            select(
                MeetingTagModel.tag,
                func.count().label("cnt"),
                func.max(MeetingTagModel.created_at).label("last_used"),
            )
            .group_by(MeetingTagModel.tag)
            .order_by(func.count().desc(), MeetingTagModel.tag.asc())
        )
        return [
            {"tag": r.tag, "count": r.cnt, "last_used": r.last_used.isoformat() if r.last_used else ""}
            for r in result.all()
        ]

    async def get_meeting_tags(self, meeting_id: str) -> list[str]:
        result = await self.db.execute(
            select(MeetingTagModel.tag)
            .where(MeetingTagModel.meeting_id == meeting_id)
            .order_by(MeetingTagModel.tag)
        )
        return list(result.scalars().all())

    async def add(self, meeting_id: str, tag: str) -> bool:
        # 检查是否已存在
        existing = await self.db.execute(
            select(MeetingTagModel.id).where(
                MeetingTagModel.meeting_id == meeting_id,
                MeetingTagModel.tag == tag,
            )
        )
        if existing.scalar_one_or_none():
            return False
        self.db.add(MeetingTagModel(
            meeting_id=meeting_id,
            tag=tag,
            created_at=datetime.now(timezone.utc),
        ))
        await self.db.flush()
        return True

    async def remove(self, meeting_id: str, tag: str) -> bool:
        result = await self.db.execute(
            delete(MeetingTagModel).where(
                MeetingTagModel.meeting_id == meeting_id,
                MeetingTagModel.tag == tag,
            )
        )
        return result.rowcount > 0

    async def batch_delete(self, meeting_ids: list[str],
                           mode: str = "soft") -> dict[str, list[str]]:
        # 委托给 MeetingRepo（跨 Repository 协调）
        meeting_repo = SqlAlchemyMeetingRepo(self.db)
        deleted: list[str] = []
        failed: list[str] = []
        for mid in meeting_ids:
            if mode == "soft":
                ok = await meeting_repo.soft_delete(mid)
            elif mode == "hard":
                ok = await meeting_repo.hard_delete(mid)
            else:
                failed.append(mid)
                continue
            if ok:
                deleted.append(mid)
            else:
                failed.append(mid)
        return {"deleted": deleted, "failed": failed}


class SqlAlchemyPreferenceRepo(PreferenceRepository):
    """SQLAlchemy 实现：用户偏好"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get(self, user_id: str, key: str) -> str | None:
        result = await self.db.execute(
            select(UserPreferenceModel.value).where(
                UserPreferenceModel.user_id == user_id,
                UserPreferenceModel.key == key,
            )
        )
        return result.scalar_one_or_none()

    async def set(self, user_id: str, key: str, value: str) -> str:
        # [CON-16 修复] 使用方言感知 upsert
        from app.db.upsert import dialect_upsert

        updated_at = datetime.now(timezone.utc)
        values = {
            "user_id": user_id,
            "key": key,
            "value": value,
            "updated_at": updated_at,
        }
        stmt = dialect_upsert(
            self.db,
            UserPreferenceModel,
            values,
            index_elements=["user_id", "key"],
            set_={"value": value, "updated_at": updated_at},
        )
        await self.db.execute(stmt)
        return updated_at.isoformat()

    async def get_all(self, user_id: str) -> dict[str, str]:
        result = await self.db.execute(
            select(UserPreferenceModel).where(UserPreferenceModel.user_id == user_id)
        )
        return {r.key: r.value for r in result.scalars().all()}

    async def delete(self, user_id: str, key: str) -> bool:
        result = await self.db.execute(
            delete(UserPreferenceModel).where(
                UserPreferenceModel.user_id == user_id,
                UserPreferenceModel.key == key,
            )
        )
        return result.rowcount > 0


class SqlAlchemyAgentRoleRepo(AgentRoleRepository):
    """SQLAlchemy 实现：Agent 角色"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list(self, active_only: bool = False) -> list[dict[str, Any]]:
        stmt = select(AgentRoleModel).order_by(
            AgentRoleModel.is_builtin.desc(), AgentRoleModel.display_name.asc()
        )
        if active_only:
            stmt = stmt.where(AgentRoleModel.is_active == True)  # noqa: E712
        result = await self.db.execute(stmt)
        return [agent_role_row_to_dict(r) for r in result.scalars().all()]

    async def get(self, role_id: str) -> dict[str, Any] | None:
        result = await self.db.execute(
            select(AgentRoleModel).where(AgentRoleModel.id == role_id)
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return agent_role_row_to_dict(row)

    async def save(self, role: dict[str, Any]) -> None:
        # [CON-16 修复] 使用方言感知 upsert
        from app.db.upsert import dialect_upsert

        values = agent_role_to_orm_values(role)
        set_fields = {k: v for k, v in values.items() if k != "id"}
        stmt = dialect_upsert(
            self.db,
            AgentRoleModel,
            values,
            index_elements=["id"],
            set_=set_fields,
        )
        await self.db.execute(stmt)

    async def delete(self, role_id: str) -> bool:
        result = await self.db.execute(
            select(AgentRoleModel).where(AgentRoleModel.id == role_id)
        )
        row = result.scalar_one_or_none()
        if row is None:
            return False
        if row.is_builtin:
            return False
        await self.db.execute(
            delete(AgentRoleModel).where(AgentRoleModel.id == role_id)
        )
        return True

    async def get_by_ids(self, role_ids: list[str]) -> list[dict[str, Any]]:
        result = await self.db.execute(
            select(AgentRoleModel).where(
                AgentRoleModel.id.in_(role_ids),
                AgentRoleModel.is_active == True,  # noqa: E712
            )
        )
        role_map = {r.id: agent_role_row_to_dict(r) for r in result.scalars().all()}
        return [role_map[rid] for rid in role_ids if rid in role_map]


class SqlAlchemyNetAuthRepo(NetAuthRepository):
    """SQLAlchemy 实现：网络授权申请"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_request(self, request_id: str, meeting_id: str,
                             stage: str, code_snippet: str,
                             requested_level: str, detected_level: str,
                             failure_reason: str, stderr_output: str,
                             expires_at: datetime) -> None:
        self.db.add(NetAuthRequestModel(
            id=request_id,
            meeting_id=meeting_id,
            stage=stage,
            code_snippet=code_snippet,
            requested_level=requested_level,
            detected_level=detected_level,
            failure_reason=failure_reason,
            stderr_output=stderr_output,
            status="pending",
            created_at=datetime.now(timezone.utc),
            expires_at=expires_at,
        ))

    async def get(self, request_id: str) -> dict[str, Any] | None:
        result = await self.db.execute(
            select(NetAuthRequestModel).where(NetAuthRequestModel.id == request_id)
        )
        row = result.scalar_one_or_none()
        return net_auth_row_to_dict(row) if row else None

    async def list_by_meeting(self, meeting_id: str,
                              status: str | None = None) -> list[dict[str, Any]]:
        stmt = select(NetAuthRequestModel).where(
            NetAuthRequestModel.meeting_id == meeting_id
        ).order_by(NetAuthRequestModel.created_at.desc())
        if status:
            stmt = stmt.where(NetAuthRequestModel.status == status)
        result = await self.db.execute(stmt)
        return [net_auth_row_to_dict(r) for r in result.scalars().all()]

    async def review(self, request_id: str, action: str,
                     comment: str) -> dict[str, Any] | None:
        result = await self.db.execute(
            select(NetAuthRequestModel).where(NetAuthRequestModel.id == request_id)
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        row.status = action
        row.review_action = action
        row.review_comment = comment
        row.reviewed_at = datetime.now(timezone.utc)
        if action in ("approved", "denied"):
            row.resolved_at = datetime.now(timezone.utc)
        await self.db.flush()
        return net_auth_row_to_dict(row)

    async def expire_pending(self) -> list[dict[str, Any]]:
        now = datetime.now(timezone.utc)
        result = await self.db.execute(
            select(NetAuthRequestModel).where(
                NetAuthRequestModel.status == "pending",
                NetAuthRequestModel.expires_at < now,
            )
        )
        rows = result.scalars().all()
        for row in rows:
            row.status = "expired"
            row.resolved_at = now
        await self.db.flush()
        return [net_auth_row_to_dict(r) for r in rows]

    async def get_pending(self, meeting_id: str) -> list[dict[str, Any]]:
        return await self.list_by_meeting(meeting_id, status="pending")


# ============================================================
# Repository 工厂：从一个 AsyncSession 创建所有 Repository
# ============================================================

class RepositoryFactory:
    """便捷工厂：一次性创建所有 Repository 实例。"""

    def __init__(self, db: AsyncSession):
        self.meetings = SqlAlchemyMeetingRepo(db)
        self.messages = SqlAlchemyMessageRepo(db)
        self.events = SqlAlchemyEventRepo(db)
        self.tags = SqlAlchemyTagRepo(db)
        self.preferences = SqlAlchemyPreferenceRepo(db)
        self.agent_roles = SqlAlchemyAgentRoleRepo(db)
        self.net_auth = SqlAlchemyNetAuthRepo(db)


# ============================================================
# 辅助函数
# ============================================================

def _extract_artifact_summary(artifact: dict[str, Any] | None) -> str:
    """从 artifact 中提取简洁摘要文本"""
    if not artifact:
        return "（无产出）"
    parts = []
    for key in ("title", "overview", "summary", "executive_summary", "verdict"):
        if artifact.get(key):
            parts.append(artifact[key])
    if not parts:
        for key in ("design_doc", "comprehensive", "research_report", "business_report"):
            inner = artifact.get(key, {})
            if isinstance(inner, dict):
                for k in ("title", "overview", "summary"):
                    if inner.get(k):
                        parts.append(inner[k])
                if parts:
                    break
    return " | ".join(parts) if parts else "（无产出摘要）"