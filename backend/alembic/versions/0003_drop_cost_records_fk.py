"""0003_drop_cost_records_fk

Revision ID: 0003_drop_cost_records_fk
Revises: 0002_aux_keys_docs_cost
Create Date: 2026-07-12 00:00:00.000000

Removes the foreign key from cost_records.meeting_id to meetings.id.
Conclave stores meetings in SQLite (legacy db_legacy) while cost_records
live in PostgreSQL, so the FK cannot be satisfied and causes silent flush
failures.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

# revision identifiers
revision: str = "0003_drop_cost_records_fk"
down_revision: Union[str, None] = "0002_aux_keys_docs_cost"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # PostgreSQL constraint name follows SQLAlchemy's auto-generated naming
    op.drop_constraint("cost_records_meeting_id_fkey", "cost_records", type_="foreignkey")


def downgrade() -> None:
    op.create_foreign_key(
        "cost_records_meeting_id_fkey",
        "cost_records",
        "meetings",
        ["meeting_id"],
        ["id"],
        ondelete="SET NULL",
    )
