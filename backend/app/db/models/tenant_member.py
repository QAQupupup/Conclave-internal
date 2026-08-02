"""租户成员 ORM 模型：tenant_members 多对多关联表。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IntegerPrimaryKeyMixin, TimestampMixin, utcnow


class TenantMemberModel(Base, IntegerPrimaryKeyMixin, TimestampMixin):
    """租户-用户多对多成员关系表。

    一个用户可以属于多个租户（Team），在每个租户中拥有独立角色。
    外键由 raw SQL 迁移脚本通过 ALTER TABLE 添加（遵循项目规范，ORM 不声明 FK）。
    """

    __tablename__ = "tenant_members"

    tenant_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    role: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="member",
        server_default=text("'member'"),
        comment="Team级角色: owner/maintainer/member/reporter/banned",
    )
    is_banned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("FALSE"))
    invited_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        server_default=text("NOW()"),
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", name="uq_tm_tenant_user"),
        CheckConstraint(
            "role IN ('owner','maintainer','member','reporter','banned')",
            name="ck_tm_role",
        ),
        Index("idx_tm_role", "role"),
        Index("idx_tm_tenant_role", "tenant_id", "role"),
        Index(
            "idx_tm_tenant_active_joined",
            "tenant_id",
            "joined_at",
            postgresql_where=text("is_banned = FALSE"),
        ),
    )
