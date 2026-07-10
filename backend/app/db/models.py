"""SQLAlchemy 2.0 ORM 模型 — 映射当前全部 7 张表。

使用 DeclarativeBase + mapped_column 风格，兼容 PostgreSQL 和 SQLite 双后端。
迁移路径：SQLite 中的 TEXT/INTEGER → PostgreSQL 中的 TEXT/BOOLEAN/TIMESTAMPTZ/JSONB。
"""
from __future__ import annotations

from datetime import datetime, timezone
from sqlalchemy import (
    String, Text, Integer, Boolean, DateTime, ForeignKey, Index, UniqueConstraint,
    func, text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


# ============================================================
# 1. meetings — 会议主表
# ============================================================
class MeetingModel(Base):
    __tablename__ = "meetings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    topic: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="running",
        comment="running|paused|aborted|done|deleted"
    )
    stage: Mapped[str] = mapped_column(
        String(20), nullable=False, default="clarify",
        comment="clarify|intra_team|cross_team|evidence_check|arbitrate|produce"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    # 完整 MeetingState JSON 快照
    payload: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    # 数据格式版本号（用于未来 schema 演进时的数据迁移）
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # 关系
    messages: Mapped[list["MessageModel"]] = relationship(
        back_populates="meeting", cascade="all, delete-orphan",
    )
    events: Mapped[list["EventModel"]] = relationship(
        back_populates="meeting", cascade="all, delete-orphan",
    )
    tags: Mapped[list["MeetingTagModel"]] = relationship(
        back_populates="meeting", cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("idx_meetings_status", "status"),
        Index("idx_meetings_created", "created_at"),
    )


# ============================================================
# 2. messages — 发言记录
# ============================================================
class MessageModel(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    meeting_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("meetings.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    agent_role: Mapped[str] = mapped_column(String(50), nullable=False)
    stage: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    claim_refs: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    evidence_refs: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    meeting: Mapped["MeetingModel"] = relationship(back_populates="messages")

    __table_args__ = (
        Index("idx_messages_meeting", "meeting_id"),
    )


# ============================================================
# 3. events — 事件溯源
# ============================================================
class EventModel(Base):
    __tablename__ = "events"

    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    meeting_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("meetings.id", ondelete="CASCADE"),
        nullable=False,
    )
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    trace_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    meeting: Mapped["MeetingModel"] = relationship(back_populates="events")

    __table_args__ = (
        Index("idx_events_meeting", "meeting_id"),
        Index("idx_events_meeting_seq", "meeting_id", "seq"),
    )


# ============================================================
# 4. user_preferences — 用户偏好
# ============================================================
class UserPreferenceModel(Base):
    __tablename__ = "user_preferences"

    user_id: Mapped[str] = mapped_column(
        String(50), primary_key=True, default="default",
    )
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


# ============================================================
# 5. meeting_tags — 会议标签
# ============================================================
class MeetingTagModel(Base):
    __tablename__ = "meeting_tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    meeting_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("meetings.id", ondelete="CASCADE"),
        nullable=False,
    )
    tag: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    meeting: Mapped["MeetingModel"] = relationship(back_populates="tags")

    __table_args__ = (
        UniqueConstraint("meeting_id", "tag", name="uq_meeting_tag"),
        Index("idx_meeting_tags_meeting", "meeting_id"),
        Index("idx_meeting_tags_tag", "tag"),
    )


# ============================================================
# 6. agent_roles — Agent 角色定义
# ============================================================
class AgentRoleModel(Base):
    __tablename__ = "agent_roles"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    perspective: Mapped[str] = mapped_column(Text, nullable=False, default="")
    expertise_domains: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    risk_appetite: Mapped[str] = mapped_column(
        String(20), nullable=False, default="balanced",
    )
    default_stance: Mapped[str] = mapped_column(Text, nullable=False, default="")
    evidence_preference: Mapped[str] = mapped_column(
        String(20), nullable=False, default="balanced",
    )
    model_override: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    background_brief: Mapped[str] = mapped_column(Text, nullable=False, default="")
    prompt_template: Mapped[str] = mapped_column(Text, nullable=False, default="")
    is_builtin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        Index("idx_agent_roles_active", "is_active"),
    )


# ============================================================
# 7. net_auth_requests — 网络授权申请
# ============================================================
class NetAuthRequestModel(Base):
    __tablename__ = "net_auth_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    meeting_id: Mapped[str] = mapped_column(
        String(36), nullable=False, index=True,
    )
    stage: Mapped[str] = mapped_column(String(20), nullable=False)
    code_snippet: Mapped[str] = mapped_column(Text, nullable=False)
    requested_level: Mapped[str] = mapped_column(String(20), nullable=False)
    detected_level: Mapped[str] = mapped_column(String(20), nullable=False)
    failure_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    stderr_output: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending",
        comment="pending|approved|denied|expired",
    )
    review_action: Mapped[str | None] = mapped_column(String(20), nullable=True)
    review_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    __table_args__ = (
        Index("idx_auth_meeting", "meeting_id"),
        Index("idx_auth_status", "status"),
    )