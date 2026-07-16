"""发言记录 ORM 模型：messages。

跨模块 relationship（MessageModel -> MeetingModel）使用字符串前向引用，
由 SQLAlchemy 在 mapper 配置阶段通过共享 Base 注册表惰性解析，无需导入
MeetingModel，从而避免循环导入。
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    String, Text, DateTime, ForeignKey, Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


# ============================================================
# messages — 发言记录
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
