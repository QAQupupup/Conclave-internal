"""0007_add_artifacts_table

Revision ID: 0007_add_artifacts_table
Revises: 0006_align_legacy_timestamps
Create Date: 2026-09-04 00:00:00.000000

ADR-017 Phase 1：产物一等公民。

  - artifacts: 会议产出从 payload 内 dict 升格为独立表实体
    （可查询 / 可版本化 / 可血缘追溯 / 可跨会议消费）
  - meetings: 增加 project_id / issue_id 可空列
    （外键目标表 projects / issues 在 Phase 2 落地，本阶段只建列）

Publish 幂等键：UNIQUE (meeting_id, type, version)（ADR-017 D2）。
大产物红线：content 仅存小型结构化内容，大型内容走 content_ref 指针
（ADR-017「大产物不入库」）。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0007_add_artifacts_table"
down_revision: str | None = "0006_align_legacy_timestamps"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── artifacts：产物一等公民（ADR-017 D1）──────────────────────
    op.create_table(
        "artifacts",
        sa.Column("id", sa.String(36), primary_key=True),
        # 多租户：TenantScopeMixin 约定（Integer 可空，DAO 层强制过滤）
        sa.Column("tenant_id", sa.Integer, nullable=True),
        # 生产会议（meetings 为 ORM 管理表，可建 FK）
        sa.Column(
            "meeting_id",
            sa.String(36),
            sa.ForeignKey("meetings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # 可选归属项目（projects 表 Phase 2 落地，届时补 FK）
        sa.Column("project_id", sa.String(36), nullable=True),
        # 产物类型：直接复用 deliverable_type 取值（任务清单 I1）
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column("title", sa.String(500), nullable=True),
        # 供后续会议消费的浓缩摘要（控制 prompt 体积）
        sa.Column("summary", sa.Text, nullable=True),
        # 小型结构化内容（大产物不入库，走 content_ref）
        sa.Column("content", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        # 大型内容指针：workspace 相对路径
        sa.Column("content_ref", sa.String(500), nullable=True),
        # 版本链：同会议同类型重生成时递增
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("parent_id", sa.String(36), nullable=True),
        # 血缘：本产物消费了哪些上游产物（ADR-017 D3 产物级双轨）
        sa.Column(
            "source_artifact_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("created_by", sa.String(100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        # Publish 幂等键（ADR-017 D2 / 任务清单 I4）
        sa.UniqueConstraint("meeting_id", "type", "version", name="uq_artifacts_meeting_type_version"),
    )
    op.create_index("idx_artifacts_tenant", "artifacts", ["tenant_id"])
    op.create_index("idx_artifacts_meeting", "artifacts", ["meeting_id"])
    op.create_index("idx_artifacts_type", "artifacts", ["type"])

    # ── meetings：项目/议题关联列（FK Phase 2 补）─────────────────
    op.add_column("meetings", sa.Column("project_id", sa.String(36), nullable=True))
    op.add_column("meetings", sa.Column("issue_id", sa.String(36), nullable=True))


def downgrade() -> None:
    op.drop_column("meetings", "issue_id")
    op.drop_column("meetings", "project_id")
    op.drop_index("idx_artifacts_type", table_name="artifacts")
    op.drop_index("idx_artifacts_meeting", table_name="artifacts")
    op.drop_index("idx_artifacts_tenant", table_name="artifacts")
    op.drop_table("artifacts")
