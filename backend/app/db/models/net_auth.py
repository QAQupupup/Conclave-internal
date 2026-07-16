"""网络授权申请 ORM 模型：net_auth_requests。"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    String, Text, DateTime, Index,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


# ============================================================
# net_auth_requests — 网络授权申请
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
