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
    # 幂等确保 tenant_id 列存在（全新数据库 alembic upgrade 时，
    # ensure_business_tables_tenant_id() 尚未运行，需要先添加列）
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.tables WHERE table_name = 'meetings'
            ) AND NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'meetings' AND column_name = 'tenant_id'
            ) THEN
                ALTER TABLE meetings ADD COLUMN tenant_id INTEGER;
            END IF;
        END $$;
    """)
    op.create_index(
        "idx_meetings_tenant_status_created",
        "meetings",
        ["tenant_id", "status", sa.text("created_at DESC")],
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("idx_meetings_tenant_status_created", table_name="meetings", if_exists=True)
