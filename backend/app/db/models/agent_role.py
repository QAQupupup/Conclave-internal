"""Agent 角色定义 ORM 模型：agent_roles。"""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Index,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


# ============================================================
# agent_roles — Agent 角色定义
# ============================================================
class AgentRoleModel(Base, TimestampMixin):
    __tablename__ = "agent_roles"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    perspective: Mapped[str] = mapped_column(Text, nullable=False, default="")
    expertise_domains: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    risk_appetite: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="balanced",
    )
    default_stance: Mapped[str] = mapped_column(Text, nullable=False, default="")
    evidence_preference: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="balanced",
    )
    model_override: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    background_brief: Mapped[str] = mapped_column(Text, nullable=False, default="")
    prompt_template: Mapped[str] = mapped_column(Text, nullable=False, default="")
    is_builtin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (Index("idx_agent_roles_active", "is_active"),)
