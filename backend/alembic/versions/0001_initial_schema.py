"""initial_schema

Revision ID: 0001_initial
Revises:
Create Date: 2025-01-01 00:00:00.000000

Creates all 7 tables defined in app/db/models.py:
  meetings, messages, events, user_preferences,
  meeting_tags, agent_roles, net_auth_requests
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 1. meetings ──────────────────────────────────────────────
    op.create_table(
        "meetings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("topic", sa.String(500), nullable=False),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="running",
            comment="running|paused|aborted|done|deleted",
        ),
        sa.Column(
            "stage",
            sa.String(20),
            nullable=False,
            server_default="clarify",
            comment="clarify|intra_team|cross_team|evidence_check|arbitrate|produce",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("payload", sa.Text, nullable=False, server_default="{}"),
        sa.Column(
            "schema_version",
            sa.Integer,
            nullable=False,
            server_default=sa.text("1"),
        ),
    )
    op.create_index("idx_meetings_status", "meetings", ["status"])
    op.create_index("idx_meetings_created", "meetings", ["created_at"])

    # ── 2. messages ──────────────────────────────────────────────
    op.create_table(
        "messages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "meeting_id",
            sa.String(36),
            sa.ForeignKey("meetings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("agent_role", sa.String(50), nullable=False),
        sa.Column("stage", sa.String(20), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("claim_refs", sa.Text, nullable=False, server_default="[]"),
        sa.Column("evidence_refs", sa.Text, nullable=False, server_default="[]"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("idx_messages_meeting", "messages", ["meeting_id"])

    # ── 3. events ────────────────────────────────────────────────
    op.create_table(
        "events",
        sa.Column(
            "seq", sa.Integer, primary_key=True, autoincrement=True,
        ),
        sa.Column(
            "meeting_id",
            sa.String(36),
            sa.ForeignKey("meetings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column("payload", sa.Text, nullable=False),
        sa.Column(
            "ts",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("trace_id", sa.String(36), nullable=True),
    )
    op.create_index("idx_events_meeting", "events", ["meeting_id"])
    op.create_index(
        "idx_events_meeting_seq", "events", ["meeting_id", "seq"],
    )

    # ── 4. user_preferences ─────────────────────────────────────
    op.create_table(
        "user_preferences",
        sa.Column(
            "user_id",
            sa.String(50),
            primary_key=True,
            server_default="default",
        ),
        sa.Column("key", sa.String(100), primary_key=True),
        sa.Column("value", sa.Text, nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # ── 5. meeting_tags ─────────────────────────────────────────
    op.create_table(
        "meeting_tags",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "meeting_id",
            sa.String(36),
            sa.ForeignKey("meetings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tag", sa.String(100), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_unique_constraint(
        "uq_meeting_tag", "meeting_tags", ["meeting_id", "tag"],
    )
    op.create_index("idx_meeting_tags_meeting", "meeting_tags", ["meeting_id"])
    op.create_index("idx_meeting_tags_tag", "meeting_tags", ["tag"])

    # ── 6. agent_roles ──────────────────────────────────────────
    op.create_table(
        "agent_roles",
        sa.Column("id", sa.String(50), primary_key=True),
        sa.Column("display_name", sa.String(100), nullable=False),
        sa.Column("perspective", sa.Text, nullable=False, server_default=""),
        sa.Column(
            "expertise_domains", sa.Text, nullable=False, server_default="[]",
        ),
        sa.Column(
            "risk_appetite",
            sa.String(20),
            nullable=False,
            server_default="balanced",
        ),
        sa.Column("default_stance", sa.Text, nullable=False, server_default=""),
        sa.Column(
            "evidence_preference",
            sa.String(20),
            nullable=False,
            server_default="balanced",
        ),
        sa.Column(
            "model_override", sa.String(100), nullable=False, server_default="",
        ),
        sa.Column("background_brief", sa.Text, nullable=False, server_default=""),
        sa.Column("prompt_template", sa.Text, nullable=False, server_default=""),
        sa.Column(
            "is_builtin", sa.Boolean, nullable=False, server_default=sa.text("false"),
        ),
        sa.Column(
            "is_active", sa.Boolean, nullable=False, server_default=sa.text("true"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("idx_agent_roles_active", "agent_roles", ["is_active"])

    # ── 7. net_auth_requests ────────────────────────────────────
    op.create_table(
        "net_auth_requests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("meeting_id", sa.String(36), nullable=False),
        sa.Column("stage", sa.String(20), nullable=False),
        sa.Column("code_snippet", sa.Text, nullable=False),
        sa.Column("requested_level", sa.String(20), nullable=False),
        sa.Column("detected_level", sa.String(20), nullable=False),
        sa.Column(
            "failure_reason", sa.Text, nullable=False, server_default="",
        ),
        sa.Column(
            "stderr_output", sa.Text, nullable=False, server_default="",
        ),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="pending",
            comment="pending|approved|denied|expired",
        ),
        sa.Column("review_action", sa.String(20), nullable=True),
        sa.Column("review_comment", sa.Text, nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_auth_meeting", "net_auth_requests", ["meeting_id"])
    op.create_index("idx_auth_status", "net_auth_requests", ["status"])


def downgrade() -> None:
    op.drop_table("net_auth_requests")
    op.drop_table("meeting_tags")
    op.drop_table("user_preferences")
    op.drop_table("events")
    op.drop_table("messages")
    op.drop_table("meetings")
    op.drop_table("agent_roles")
