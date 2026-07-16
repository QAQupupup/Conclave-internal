"""上传文档元数据 ORM 模型：documents。

跨模块 relationship（DocumentModel -> MeetingModel）使用字符串前向引用，
由 SQLAlchemy 在 mapper 配置阶段通过共享 Base 注册表惰性解析，无需导入
MeetingModel，从而避免循环导入。
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    String, Text, Integer, DateTime, ForeignKey, Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


# ============================================================
# documents — 上传文档元数据
# ============================================================
class DocumentModel(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    meeting_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("meetings.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    original_name: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    content_type: Mapped[str] = mapped_column(String(100), nullable=False, default="text/markdown")
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="",
                                              comment="SHA256 of file content for dedup")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    meeting: Mapped["MeetingModel"] = relationship()

    __table_args__ = (
        Index("idx_documents_meeting", "meeting_id"),
    )
