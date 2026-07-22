"""SQLAlchemy ORM 基类与公共 Mixin。

所有 ORM 模型继承自 Base，通过 Base.metadata 统一管理表结构。
公共字段（主键、时间戳、租户隔离）通过 Mixin 复用，避免每个模型重复声明。

注意 (AGENTS.md §4.12)：对于由 raw SQL 创建的表（如 tenants、users），
**不要**在 ORM 模型中声明 ForeignKey，否则 Base.metadata.create_all() 会因
找不到被引用表而抛出 NoReferencedTableError。外键约束统一由
`app/tenants/service.py::ensure_business_tables_tenant_id()` 通过 raw SQL
`ALTER TABLE ... ADD CONSTRAINT` 添加。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    """返回当前 UTC 时间（tz-aware），用于 created_at/updated_at 的 default。"""
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """ORM 模型基类。"""

    pass


# ============================================================
# 主键 Mixin
# ============================================================


class UUIDPrimaryKeyMixin:
    """UUID 字符串主键（String(36)），默认自动生成 uuid4。"""

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))


class IntegerPrimaryKeyMixin:
    """自增 Integer 主键。"""

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)


# ============================================================
# 时间戳 Mixin
# ============================================================


class CreatedAtMixin:
    """仅 created_at（不可变记录，如 events、messages、tags）。"""

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class UpdatedAtMixin:
    """仅 updated_at（配置/画像类，如 profile_memories、user_preferences）。
    带 onupdate=utcnow 自动刷新。"""

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


class TimestampMixin(CreatedAtMixin, UpdatedAtMixin):
    """标准 created_at + updated_at 双时间戳，updated_at 自动刷新。"""

    pass


# ============================================================
# 多租户 Mixin（纵深防御）
# ============================================================


class TenantScopeMixin:
    """tenant_id 多租户字段。

    - nullable=True 允许 NULL（系统级资源）
    - index=True 加速租户过滤查询
    - **不声明 ForeignKey**：外键由 raw SQL 迁移统一添加（见模块 docstring）
    - DAO/路由层必须在查询时加 WHERE tenant_id = :tid，不能依赖数据库隔离
    """

    tenant_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
