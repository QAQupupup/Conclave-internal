"""0005_add_meetings_composite_index

Revision ID: 0005_add_meetings_composite
Revises: 0004_add_memory_tables
Create Date: 2026-07-22 00:00:00.000000

Adds composite index on meetings(tenant_id, status, created_at DESC)
to optimize the most common multi-tenant query pattern:
  WHERE tenant_id = ? AND status != 'deleted' ORDER BY created_at DESC
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005_add_meetings_composite"
down_revision: str | None = "0004_add_memory_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "idx_meetings_tenant_status_created",
        "meetings",
        ["tenant_id", "status", sa.text("created_at DESC")],
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("idx_meetings_tenant_status_created", table_name="meetings", if_exists=True)
