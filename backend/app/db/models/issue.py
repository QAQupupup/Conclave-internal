"""议题 ORM 模型：issues（ADR-017 Phase 2）。

议题是项目下的迭代单元。两条入口（ADR-017 D7）：
- ``source=user``：用户手动入池；
- ``source=meeting``：会议候选议题经用户确认后入池（挂 source_meeting_id）。

状态机 ``open | scheduled | in_progress | conflict | resolved | wontfix``，
合法流转由服务层（services/issue_service.py）校验；
``resolved`` 必须挂 ``resolution_artifact_id``（闭环凭证红线）；
``conflict`` 为 ADR-017 D11 合入 main 冲突态（交回用户处置）。

跨模块关联一律通过显式 join 实现，不使用 relationship
（见 docs/sql-development-rules.md §1.2 红线）。
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import (
    Base,
    TenantScopeMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)


class IssueModel(Base, UUIDPrimaryKeyMixin, TimestampMixin, TenantScopeMixin):
    __tablename__ = "issues"

    # 归属项目（projects 为 ORM 管理表，可声明 FK；删项目级联删议题）
    project_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 入口：user（手动）| meeting（会议候选经人工确认，ADR-017 D7）
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    # 提出该议题的会议（会议删除后置 NULL，议题保留）
    source_meeting_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("meetings.id", ondelete="SET NULL"),
        nullable=True,
    )
    # 状态机：open|scheduled|in_progress|conflict|resolved|wontfix（服务层校验流转）
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open", server_default=text("'open'"))
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=50, server_default=text("50"))
    # 当前绑定的执行会议（议题 → 会议；会议删除后置 NULL）
    assigned_meeting_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("meetings.id", ondelete="SET NULL"),
        nullable=True,
    )
    # 闭环凭证：解决该议题的产物（resolved 必挂，服务层校验）
    resolution_artifact_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("artifacts.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_by: Mapped[str | None] = mapped_column(String(100), nullable=True)

    __table_args__ = (
        Index("idx_issues_tenant", "tenant_id"),
        Index("idx_issues_project", "project_id"),
        Index("idx_issues_status", "status"),
    )
