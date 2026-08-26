"""事件溯源 ORM 模型：events。

跨模块关联一律通过显式 join 实现，不使用 relationship（见 docs/sql-development-rules.md
§1.2 红线）。历史 relationship 声明已注释保留、未删除。
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    DateTime,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScopeMixin


# ============================================================
# events — 事件溯源
# ============================================================
class EventModel(Base, TenantScopeMixin):
    __tablename__ = "events"

    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 注意：不声明 ForeignKey("meetings.id")。events 还承载系统级事件，
    # 其 meeting_id 使用哨兵值 "*"（如 system.meetings.changed），并不指向真实会议，
    # 外键约束会与哨兵设计冲突且历史 init_db 手写 DDL 也从未建过该外键。
    meeting_id: Mapped[str] = mapped_column(
        String(36),
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

    # meeting: Mapped[MeetingModel] = relationship(back_populates="events")  # 历史 relationship，已注释

    __table_args__ = (
        Index("idx_events_meeting", "meeting_id"),
        Index("idx_events_meeting_seq", "meeting_id", "seq"),
    )
