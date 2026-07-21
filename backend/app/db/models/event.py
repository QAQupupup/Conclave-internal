"""事件溯源 ORM 模型：events。

跨模块 relationship（EventModel -> MeetingModel）使用字符串前向引用，
由 SQLAlchemy 在 mapper 配置阶段通过共享 Base 注册表惰性解析，无需导入
MeetingModel，从而避免循环导入。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TenantScopeMixin

if TYPE_CHECKING:
    from app.db.models.meeting import MeetingModel


# ============================================================
# events — 事件溯源
# ============================================================
class EventModel(Base, TenantScopeMixin):
    __tablename__ = "events"

    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    meeting_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("meetings.id", ondelete="CASCADE"),
        nullable=False,
    )
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    trace_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    meeting: Mapped[MeetingModel] = relationship(back_populates="events")

    __table_args__ = (
        Index("idx_events_meeting", "meeting_id"),
        Index("idx_events_meeting_seq", "meeting_id", "seq"),
    )
