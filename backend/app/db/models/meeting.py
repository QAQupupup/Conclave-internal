"""会议相关 ORM 模型：meetings / meeting_tags / meeting_aux。

跨模块关联一律通过显式 join 实现，不使用 relationship（见 docs/sql-development-rules.md
§1.2 红线）。历史 relationship 声明已注释保留、未删除。
"""

from __future__ import annotations

from sqlalchemy import (
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import (
    Base,
    CreatedAtMixin,
    IntegerPrimaryKeyMixin,
    TenantScopeMixin,
    UpdatedAtMixin,
    UUIDPrimaryKeyMixin,
)

# 注：MessageModel / EventModel 仅供历史 relationship 注解引用，已一并注释，
# 故不再需要 TYPE_CHECKING 前向导入。


# ============================================================
# meetings — 会议主表
# ============================================================
class MeetingModel(Base, UUIDPrimaryKeyMixin, CreatedAtMixin, TenantScopeMixin):
    __tablename__ = "meetings"

    topic: Mapped[str] = mapped_column(String(500), nullable=False)
    owner_username: Mapped[str] = mapped_column(String(100), nullable=False, default="system", index=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="running", comment="running|paused|aborted|done|deleted"
    )
    stage: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="clarify",
        comment="clarify|intra_team|cross_team|evidence_check|arbitrate|produce",
    )
    # 完整 MeetingState JSON 快照
    payload: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    # 数据格式版本号（用于未来 schema 演进时的数据迁移）
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # ADR-017：项目/议题关联（Phase 1 建列，Phase 2 补 FK）。
    # SET NULL：项目/议题删除不级联删会议，历史可追溯。
    project_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True,
    )
    issue_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("issues.id", ondelete="SET NULL"),
        nullable=True,
    )

    # 关系（历史 relationship 已按 docs/sql-development-rules.md §1.2 红线注释，
    # 跨模块关联改用显式 join；保留注释以便追溯，不可重新启用）
    # messages: Mapped[list[MessageModel]] = relationship(
    #     back_populates="meeting",
    #     cascade="all, delete-orphan",
    # )
    # events: Mapped[list[EventModel]] = relationship(
    #     back_populates="meeting",
    #     cascade="all, delete-orphan",
    # )
    # tags: Mapped[list[MeetingTagModel]] = relationship(
    #     back_populates="meeting",
    #     cascade="all, delete-orphan",
    # )

    __table_args__ = (
        Index("idx_meetings_status", "status"),
        Index("idx_meetings_created", "created_at"),
    )


# ============================================================
# meeting_tags — 会议标签
# ============================================================
class MeetingTagModel(Base, IntegerPrimaryKeyMixin, CreatedAtMixin, TenantScopeMixin):
    __tablename__ = "meeting_tags"

    meeting_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("meetings.id", ondelete="CASCADE"),
        nullable=False,
    )
    tag: Mapped[str] = mapped_column(String(100), nullable=False)

    # meeting: Mapped[MeetingModel] = relationship(back_populates="tags")  # 历史 relationship，已注释

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
class MeetingAuxModel(Base, UpdatedAtMixin, TenantScopeMixin):
    __tablename__ = "meeting_aux"

    meeting_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("meetings.id", ondelete="CASCADE"),
        primary_key=True,
    )
    key: Mapped[str] = mapped_column(
        String(50),
        primary_key=True,
        comment="aux field name: llm_trace|evidence_set|conclusion_chain|borrowed_agents",
    )
    value_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="{}",
        comment="JSON-serialized aux field value",
    )

    __table_args__ = (Index("idx_meeting_aux_meeting", "meeting_id"),)
