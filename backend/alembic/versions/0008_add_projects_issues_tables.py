"""0008_add_projects_issues_tables

Revision ID: 0008_add_projects_issues_tables
Revises: 0007_add_artifacts_table
Create Date: 2026-09-05 00:00:00.000000

ADR-017 Phase 2：项目命名空间与议题池。

  - projects: 仓库绑定的 namespace（议题/会议/产物/索引的聚合根）。
    slug 仅作人类可读标识（tenant 内唯一）；隔离键是稳定的
    projects.id（ADR-017 D5 / ADR-018 D3），slug 改名不影响索引。
  - issues: 项目下的迭代单元。两条入口：user（手动）/ meeting
    （会议候选经人工确认，ADR-017 D7）；状态机
    open|scheduled|in_progress|resolved|wontfix（服务层校验流转）。
  - 补外键：meetings.project_id / meetings.issue_id / artifacts.project_id
    （列在 Phase 1 0007 已建，本阶段补 FK；现有数据均为 NULL，安全）。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0008_add_projects_issues_tables"
down_revision: str | None = "0007_add_artifacts_table"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── projects：仓库绑定的 namespace（ADR-017 D5）──────────────
    op.create_table(
        "projects",
        sa.Column("id", sa.String(36), primary_key=True),
        # 多租户：TenantScopeMixin 约定（Integer 可空，DAO 层强制过滤）
        sa.Column("tenant_id", sa.Integer, nullable=True),
        # namespace 标识：tenant 内唯一；可改名（隔离键是 id 不是 slug）
        sa.Column("slug", sa.String(100), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        # 绑定的仓库（可空：纯文档型项目）
        sa.Column("repo_url", sa.String(500), nullable=True),
        sa.Column("default_branch", sa.String(200), nullable=False, server_default="main"),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("created_by", sa.String(100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("tenant_id", "slug", name="uq_projects_tenant_slug"),
    )
    op.create_index("idx_projects_tenant", "projects", ["tenant_id"])
    op.create_index("idx_projects_slug", "projects", ["slug"])

    # ── issues：项目下的迭代单元（ADR-017 D7 两条入口）──────────
    op.create_table(
        "issues",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.Integer, nullable=True),
        # 归属项目（ORM 管理表，可建 FK；删项目级联删议题）
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("body", sa.Text, nullable=True),
        # 入口：user（手动）| meeting（会议候选经人工确认）
        sa.Column("source", sa.String(20), nullable=False),
        # 提出该议题的会议（可空；会议删除后保留议题，置 NULL）
        sa.Column(
            "source_meeting_id",
            sa.String(36),
            sa.ForeignKey("meetings.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # 状态机：open|scheduled|in_progress|resolved|wontfix（服务层校验）
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("priority", sa.Integer, nullable=False, server_default="50"),
        # 当前绑定的执行会议（议题 → 会议，会议删除后置 NULL）
        sa.Column(
            "assigned_meeting_id",
            sa.String(36),
            sa.ForeignKey("meetings.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # 闭环凭证：解决该议题的产物（resolved 必挂，服务层校验）
        sa.Column(
            "resolution_artifact_id",
            sa.String(36),
            sa.ForeignKey("artifacts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_by", sa.String(100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("idx_issues_tenant", "issues", ["tenant_id"])
    op.create_index("idx_issues_project", "issues", ["project_id"])
    op.create_index("idx_issues_status", "issues", ["status"])

    # ── 补外键：Phase 1 已建列，本阶段补约束 ─────────────────────
    # 均为 SET NULL：项目/议题删除不级联删会议与产物（历史可追溯）
    op.create_foreign_key("fk_meetings_project", "meetings", "projects", ["project_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_meetings_issue", "meetings", "issues", ["issue_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_artifacts_project", "artifacts", "projects", ["project_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    op.drop_constraint("fk_artifacts_project", "artifacts", type_="foreignkey")
    op.drop_constraint("fk_meetings_issue", "meetings", type_="foreignkey")
    op.drop_constraint("fk_meetings_project", "meetings", type_="foreignkey")
    op.drop_index("idx_issues_status", table_name="issues")
    op.drop_index("idx_issues_project", table_name="issues")
    op.drop_index("idx_issues_tenant", table_name="issues")
    op.drop_table("issues")
    op.drop_index("idx_projects_slug", table_name="projects")
    op.drop_index("idx_projects_tenant", table_name="projects")
    op.drop_table("projects")
