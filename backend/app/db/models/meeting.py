"""会议相关 ORM 模型：meetings / meeting_tags / meeting_aux。

跨模块 relationship（MeetingModel -> MessageModel / EventModel）使用字符串前向
引用，由 SQLAlchemy 在 mapper 配置阶段通过共享 Base 注册表惰性解析，无需在此
导入目标模型类，从而避免循环导入。
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    String, Text, Integer, DateTime, ForeignKey, Index, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


# ============================================================
# meetings — 会议主表
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
# meeting_tags — 会议标签
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
# meeting_aux — 会议辅助大字段存储（MeetingState 瘦身）
# ============================================================
# 将 MeetingState 中的大字段（llm_trace, evidence_set, conclusion_chain,
# borrowed_agents）从主 payload JSON 中分离，减少热路径序列化开销。
# 采用 (meeting_id, key) 组合主键，支持灵活扩展。
class MeetingAuxModel(Base):
    __tablename__ = "meeting_aux"

    meeting_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("meetings.id", ondelete="CASCADE"),
        primary_key=True,
    )
    key: Mapped[str] = mapped_column(
        String(50), primary_key=True,
        comment="aux field name: llm_trace|evidence_set|conclusion_chain|borrowed_agents",
    )
    value_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="{}",
        comment="JSON-serialized aux field value",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        Index("idx_meeting_aux_meeting", "meeting_id"),
    )
