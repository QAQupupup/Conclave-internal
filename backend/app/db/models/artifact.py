"""产物 ORM 模型：artifacts（ADR-017 Phase 1）。

产物是会议产出的一等公民实体：可查询、可版本化、可血缘追溯、可跨会议消费。
Publish 模式（ADR-017 D2）：会议运行态仍以 state.artifact 为准，
会议成功终态后由 artifact_service 单向幂等发布入本表。

跨模块关联一律通过显式 join 实现，不使用 relationship
（见 docs/sql-development-rules.md §1.2 红线）。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import (
    Base,
    CreatedAtMixin,
    TenantScopeMixin,
    UUIDPrimaryKeyMixin,
)


class ArtifactModel(Base, UUIDPrimaryKeyMixin, CreatedAtMixin, TenantScopeMixin):
    __tablename__ = "artifacts"

    # 生产会议（meetings 为 ORM 管理表，可声明 FK，先例 MeetingTagModel）
    meeting_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("meetings.id", ondelete="CASCADE"),
        nullable=False,
    )
    # 可选归属项目（ADR-017 Phase 2 补 FK；SET NULL：项目删除不级联删产物）
    project_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True,
    )
    # 产物类型：直接复用 deliverable_type 取值（017 任务清单 I1）
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # 供后续会议消费的浓缩摘要（控制 prompt 体积）
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 小型结构化内容；大产物只存 content_ref 指针（ADR-017 红线）
    content: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    content_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # 版本链：同会议同类型重生成时递增；parent_id 指向上一版本
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    parent_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # 血缘：本产物消费了哪些上游产物（ADR-017 D3 产物级双轨）
    source_artifact_ids: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    created_by: Mapped[str | None] = mapped_column(String(100), nullable=True)

    __table_args__ = (
        # Publish 幂等键（ADR-017 D2 / 017 任务清单 I4）
        UniqueConstraint("meeting_id", "type", "version", name="uq_artifacts_meeting_type_version"),
        Index("idx_artifacts_tenant", "tenant_id"),
        Index("idx_artifacts_meeting", "meeting_id"),
        Index("idx_artifacts_type", "type"),
    )
