"""记忆子系统 ORM 模型：raw_memories / feature_memories / profile_memories。"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin, UpdatedAtMixin, UUIDPrimaryKeyMixin


# ============================================================
# raw_memories — Agent 原始发言记忆（三层记忆子系统）
# ============================================================
class RawMemoryModel(Base, UUIDPrimaryKeyMixin, CreatedAtMixin):
    __tablename__ = "raw_memories"

    agent_role: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    meeting_id: Mapped[str] = mapped_column(String(36), nullable=False)
    stage: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    evidence_refs: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    adopted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    corrected_by: Mapped[str | None] = mapped_column(String(50), nullable=True)

    __table_args__ = (
        Index("idx_raw_memories_agent", "agent_role"),
        Index("idx_raw_memories_meeting", "meeting_id"),
    )


# ============================================================
# feature_memories — Agent 行为特征记忆
# ============================================================
class FeatureMemoryModel(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "feature_memories"

    agent_role: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    feature_type: Mapped[str] = mapped_column(String(30), nullable=False, default="")
    feature_value: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    confidence: Mapped[float] = mapped_column(nullable=False, default=0.0)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_meeting_ids: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    extracted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (Index("idx_feature_memories_agent", "agent_role"),)


# ============================================================
# profile_memories — Agent 稳定画像
# ============================================================
class ProfileMemoryModel(Base, UpdatedAtMixin):
    __tablename__ = "profile_memories"

    agent_role: Mapped[str] = mapped_column(String(50), primary_key=True)
    default_stance_style: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="balanced",
    )
    ambiguity_tolerance: Mapped[float] = mapped_column(nullable=False, default=0.5)
    evidence_dependency_level: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="medium",
    )
    collaboration_preference: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="collaborative",
    )
    escalation_threshold: Mapped[float] = mapped_column(nullable=False, default=0.6)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
