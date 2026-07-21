"""0002_add_aux_api_keys_docs_cost

Revision ID: 0002_aux_keys_docs_cost
Revises: 0001_initial
Create Date: 2026-07-12 00:00:00.000000

Adds 4 new tables:
  - meeting_aux: 会议辅助大字段存储
  - api_keys: BYOK API Key 加密持久化
  - documents: 上传文档元数据
  - cost_records: LLM/工具调用成本记录
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision: str = "0002_aux_keys_docs_cost"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 8. meeting_aux ───────────────────────────────────────────
    op.create_table(
        "meeting_aux",
        sa.Column("meeting_id", sa.String(36), sa.ForeignKey("meetings.id", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("key", sa.String(50), primary_key=True,
                  comment="aux field name: llm_trace|evidence_set|conclusion_chain|borrowed_agents"),
        sa.Column("value_json", sa.Text, nullable=False, server_default="{}",
                  comment="JSON-serialized aux field value"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_index("idx_meeting_aux_meeting", "meeting_aux", ["meeting_id"])

    # ── 9. api_keys ──────────────────────────────────────────────
    op.create_table(
        "api_keys",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("provider", sa.String(50), nullable=False, index=True,
                  comment="LLM厂商: siliconflow/deepseek/openai/openrouter/custom"),
        sa.Column("name", sa.String(100), nullable=False, server_default="default",
                  comment="Key别名"),
        sa.Column("encrypted_key", sa.Text, nullable=False,
                  comment="Fernet加密存储的API Key"),
        sa.Column("base_url", sa.String(500), nullable=False, server_default=""),
        sa.Column("is_default", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.UniqueConstraint("provider", "name", name="uq_api_key_provider_name"),
    )
    op.create_index("idx_api_keys_provider", "api_keys", ["provider"])

    # ── 10. documents ───────────────────────────────────────────
    op.create_table(
        "documents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("meeting_id", sa.String(36), sa.ForeignKey("meetings.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("filename", sa.String(500), nullable=False),
        sa.Column("original_name", sa.String(500), nullable=False, server_default=""),
        sa.Column("content_type", sa.String(100), nullable=False, server_default="text/markdown"),
        sa.Column("size_bytes", sa.Integer, nullable=False, server_default="0"),
        sa.Column("chunk_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("content_hash", sa.String(64), nullable=False, server_default="",
                  comment="SHA256 of file content for dedup"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_index("idx_documents_meeting", "documents", ["meeting_id"])

    # ── 11. cost_records ────────────────────────────────────────
    op.create_table(
        "cost_records",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("meeting_id", sa.String(36),
                  sa.ForeignKey("meetings.id", ondelete="SET NULL"),
                  nullable=True, index=True),
        sa.Column("stage", sa.String(30), nullable=False, server_default=""),
        sa.Column("node", sa.String(50), nullable=False, server_default="",
                  comment="调用节点: llm|tool|sandbox"),
        sa.Column("role", sa.String(50), nullable=False, server_default=""),
        sa.Column("provider", sa.String(50), nullable=False, server_default=""),
        sa.Column("model", sa.String(100), nullable=False, server_default=""),
        sa.Column("tool_name", sa.String(100), nullable=False, server_default=""),
        sa.Column("input_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Float, nullable=False, server_default="0.0"),
        sa.Column("latency_ms", sa.Integer, nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="ok"),
        sa.Column("error", sa.Text, nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_index("idx_cost_meeting", "cost_records", ["meeting_id"])
    op.create_index("idx_cost_created", "cost_records", ["created_at"])
    op.create_index("idx_cost_node", "cost_records", ["node"])


def downgrade() -> None:
    op.drop_table("cost_records")
    op.drop_table("documents")
    op.drop_table("api_keys")
    op.drop_table("meeting_aux")
