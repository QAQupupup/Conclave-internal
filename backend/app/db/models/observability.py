"""可观测性 ORM 模型：cost_records（LLM/工具调用成本记录）、audit_logs（审计日志）。"""

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


# ============================================================
# audit_logs — 审计日志（从 SQLite audit.db 迁移到 PostgreSQL）
# ============================================================
class AuditLogModel(Base, IntegerPrimaryKeyMixin):
    """审计日志表。

    记录所有关键用户操作和系统事件，用于问题定位、安全审计、行为分析、合规审计。
    原 SQLite 实现（audit.db）已废弃，统一到 PostgreSQL。
    """

    __tablename__ = "audit_logs"

    timestamp: Mapped[str] = mapped_column(
        String(40), nullable=False, index=True, comment="ISO8601 UTC 时间戳"
    )
    category: Mapped[str] = mapped_column(String(20), nullable=False, default="其他", index=True)
    action: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, default="-")
    username: Mapped[str] = mapped_column(String(128), nullable=False, default="-", index=True)
    user_role: Mapped[str] = mapped_column(String(30), nullable=False, default="")
    meeting_id: Mapped[str] = mapped_column(String(36), nullable=False, default="-", index=True)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False, default="-")
    ip: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="success")
    details: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        Index("idx_audit_time", "timestamp"),
        Index("idx_audit_user", "username"),
        Index("idx_audit_meeting", "meeting_id"),
        Index("idx_audit_action", "action"),
        Index("idx_audit_category", "category"),
    )
