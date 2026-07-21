"""可观测性 ORM 模型：cost_records（LLM/工具调用成本记录）。"""

from __future__ import annotations

from sqlalchemy import (
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin, IntegerPrimaryKeyMixin, TenantScopeMixin


# ============================================================
# cost_records — LLM/工具调用成本记录
# ============================================================
class CostRecordModel(Base, IntegerPrimaryKeyMixin, CreatedAtMixin, TenantScopeMixin):
    __tablename__ = "cost_records"

    meeting_id: Mapped[str] = mapped_column(
        String(36),
        nullable=True,
        index=True,
    )
    stage: Mapped[str] = mapped_column(String(30), nullable=False, default="")
    node: Mapped[str] = mapped_column(String(50), nullable=False, default="", comment="调用节点: llm|tool|sandbox")
    role: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    provider: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    model: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    tool_name: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[float] = mapped_column(default=0.0)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ok")
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")

    __table_args__ = (
        Index("idx_cost_meeting", "meeting_id"),
        Index("idx_cost_created", "created_at"),
        Index("idx_cost_node", "node"),
    )
