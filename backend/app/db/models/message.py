"""发言记录 ORM 模型：messages。

跨模块关联一律通过显式 join 实现，不使用 relationship（见 docs/sql-development-rules.md
§1.2 红线）。历史 relationship 声明已注释保留、未删除。
"""

from __future__ import annotations

from sqlalchemy import (
    ForeignKey,
    Index,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin, TenantScopeMixin, UUIDPrimaryKeyMixin


# ============================================================
# messages — 发言记录
# ============================================================
class MessageModel(Base, UUIDPrimaryKeyMixin, CreatedAtMixin, TenantScopeMixin):
    __tablename__ = "messages"

    meeting_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("meetings.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agent_role: Mapped[str] = mapped_column(String(50), nullable=False)
    stage: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    claim_refs: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    evidence_refs: Mapped[str] = mapped_column(Text, nullable=False, default="[]")

    # meeting: Mapped[MeetingModel] = relationship(back_populates="messages")  # 历史 relationship，已注释

    __table_args__ = (Index("idx_messages_meeting", "meeting_id"),)
