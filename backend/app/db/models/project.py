"""项目 ORM 模型：projects（ADR-017 Phase 2）。

项目是仓库绑定的 namespace：议题、会议、产物、代码库理解索引的聚合根。
隔离键是稳定的 ``projects.id``（ADR-017 D5 / ADR-018 D3
``{tenant_id}:proj-{project_id}``）；slug 仅作人类可读标识与 URL，
改名不影响索引。

跨模块关联一律通过显式 join 实现，不使用 relationship
（见 docs/sql-development-rules.md §1.2 红线）。
"""

from __future__ import annotations

from sqlalchemy import Index, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import (
    Base,
    TenantScopeMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)


class ProjectModel(Base, UUIDPrimaryKeyMixin, TimestampMixin, TenantScopeMixin):
    __tablename__ = "projects"

    # namespace 标识：tenant 内唯一；允许改名（隔离键是 id 不是 slug）
    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # 绑定的仓库（可空：纯文档型项目）
    repo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    default_branch: Mapped[str] = mapped_column(
        String(200), nullable=False, default="main", server_default=text("'main'")
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(100), nullable=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "slug", name="uq_projects_tenant_slug"),
        Index("idx_projects_tenant", "tenant_id"),
        Index("idx_projects_slug", "slug"),
    )
