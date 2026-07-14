"""0004_add_memory_tables

Revision ID: 0004_add_memory_tables
Revises: 0003_drop_cost_records_fk
Create Date: 2026-07-14 00:00:00.000000

Adds 3 new tables for the three-layer memory subsystem:
  - raw_memories: Agent 原始发言记忆（不可变层）
  - feature_memories: Agent 行为特征记忆（特征层）
  - profile_memories: Agent 稳定画像（画像层）
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004_add_memory_tables"
down_revision: Union[str, None] = "0003_drop_cost_records_fk"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 12. raw_memories ─────────────────────────────────────────
    op.create_table(
        "raw_memories",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("agent_role", sa.String(50), nullable=False),
        sa.Column("meeting_id", sa.String(36), nullable=False),
        sa.Column("stage", sa.String(20), nullable=False, server_default=""),
        sa.Column("content", sa.Text, nullable=False, server_default=""),
        sa.Column("evidence_refs", sa.Text, nullable=False, server_default="[]"),
        sa.Column("adopted", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("corrected_by", sa.String(50), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("idx_raw_memories_agent", "raw_memories", ["agent_role"])
    op.create_index("idx_raw_memories_meeting", "raw_memories", ["meeting_id"])

    # ── 13. feature_memories ─────────────────────────────────────
    op.create_table(
        "feature_memories",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("agent_role", sa.String(50), nullable=False),
        sa.Column("feature_type", sa.String(30), nullable=False, server_default=""),
        sa.Column("feature_value", sa.String(50), nullable=False, server_default=""),
        sa.Column("confidence", sa.Float, nullable=False, server_default="0.0"),
        sa.Column("sample_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("source_meeting_ids", sa.Text, nullable=False, server_default="[]"),
        sa.Column(
            "extracted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("idx_feature_memories_agent", "feature_memories", ["agent_role"])

    # ── 14. profile_memories ─────────────────────────────────────
    op.create_table(
        "profile_memories",
        sa.Column("agent_role", sa.String(50), primary_key=True),
        sa.Column(
            "default_stance_style",
            sa.String(20),
            nullable=False,
            server_default="balanced",
        ),
        sa.Column("ambiguity_tolerance", sa.Float, nullable=False, server_default="0.5"),
        sa.Column(
            "evidence_dependency_level",
            sa.String(20),
            nullable=False,
            server_default="medium",
        ),
        sa.Column(
            "collaboration_preference",
            sa.String(20),
            nullable=False,
            server_default="collaborative",
        ),
        sa.Column("escalation_threshold", sa.Float, nullable=False, server_default="0.6"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
    )


def downgrade() -> None:
    op.drop_table("profile_memories")
    op.drop_table("feature_memories")
    op.drop_table("raw_memories")
