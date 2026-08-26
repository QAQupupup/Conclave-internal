"""0006_align_legacy_timestamp_types

Revision ID: 0006_align_legacy_timestamps
Revises: 0005_add_meetings_composite
Create Date: 2026-08-26 00:00:00.000000

将 legacy 表（由旧版 db_init.py 手写 DDL 创建）的时间字段与布尔字段
对齐到 ORM 模型 / Alembic 0001 声明的类型，消除"双源真相"：

  时间字段：TEXT（存 ISO 字符串）→ TIMESTAMPTZ
  布尔字段：INTEGER（0/1）→ BOOLEAN

涉及表/列：
  - meetings.created_at
  - messages.created_at
  - events.ts
  - user_preferences.updated_at
  - meeting_tags.created_at
  - agent_roles.created_at / updated_at
  - meeting_aux.updated_at
  - agent_roles.is_builtin / is_active

幂等性：每个 ALTER 都先用 information_schema 校验列的 data_type，
仅在仍是 legacy 类型（text / integer）时才转换，可安全重复执行。
存量数据格式约定：legacy DAO 一律写入 datetime.isoformat() 字符串，
可被 PostgreSQL `::timestamptz` 直接解析（含 'T' 分隔符与小数秒）。
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0006_align_legacy_timestamps"
down_revision: str | None = "0005_add_meetings_composite"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (table, column)：时间字段 TEXT → TIMESTAMPTZ
_TIMESTAMP_COLUMNS: tuple[tuple[str, str], ...] = (
    ("meetings", "created_at"),
    ("messages", "created_at"),
    ("events", "ts"),
    ("user_preferences", "updated_at"),
    ("meeting_tags", "created_at"),
    ("agent_roles", "created_at"),
    ("agent_roles", "updated_at"),
    ("meeting_aux", "updated_at"),
)

# (table, column)：布尔字段 INTEGER → BOOLEAN
_BOOLEAN_COLUMNS: tuple[tuple[str, str], ...] = (
    ("agent_roles", "is_builtin"),
    ("agent_roles", "is_active"),
)


def upgrade() -> None:
    # ── 时间字段：TEXT → TIMESTAMPTZ ─────────────────────────────
    for table, column in _TIMESTAMP_COLUMNS:
        op.execute(
            f"""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = '{table}' AND column_name = '{column}'
                      AND data_type = 'text'
                ) THEN
                    ALTER TABLE {table}
                        ALTER COLUMN {column} TYPE TIMESTAMPTZ
                        USING {column}::TIMESTAMPTZ;
                    ALTER TABLE {table}
                        ALTER COLUMN {column} SET DEFAULT now();
                END IF;
            END $$;
            """
        )

    # ── 布尔字段：INTEGER → BOOLEAN ──────────────────────────────
    for table, column in _BOOLEAN_COLUMNS:
        op.execute(
            f"""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = '{table}' AND column_name = '{column}'
                      AND data_type = 'integer'
                ) THEN
                    ALTER TABLE {table}
                        ALTER COLUMN {column} TYPE BOOLEAN
                        USING ({column} <> 0);
                END IF;
            END $$;
            """
        )


def downgrade() -> None:
    # 反向：TIMESTAMPTZ → TEXT（best-effort，ISO 语义改为文本，用于回滚调试）
    for table, column in _TIMESTAMP_COLUMNS:
        op.execute(
            f"""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = '{table}' AND column_name = '{column}'
                      AND data_type = 'timestamp with time zone'
                ) THEN
                    ALTER TABLE {table}
                        ALTER COLUMN {column} TYPE TEXT
                        USING {column}::TEXT;
                END IF;
            END $$;
            """
        )

    # 反向：BOOLEAN → INTEGER
    for table, column in _BOOLEAN_COLUMNS:
        op.execute(
            f"""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = '{table}' AND column_name = '{column}'
                      AND data_type = 'boolean'
                ) THEN
                    ALTER TABLE {table}
                        ALTER COLUMN {column} TYPE INTEGER
                        USING ({column}::int);
                END IF;
            END $$;
            """
        )
