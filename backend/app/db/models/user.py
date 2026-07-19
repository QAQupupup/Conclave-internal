"""用户偏好与 BYOK API Key ORM 模型：user_preferences / api_keys。"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


# ============================================================
# user_preferences — 用户偏好
# ============================================================
class UserPreferenceModel(Base):
    __tablename__ = "user_preferences"

    user_id: Mapped[str] = mapped_column(
        String(50),
        primary_key=True,
        default="default",
    )
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


# ============================================================
# api_keys — BYOK API Key 加密持久化
# ============================================================
class ApiKeyModel(Base):
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True, comment="LLM厂商: siliconflow/deepseek/openai/openrouter/custom"
    )
    name: Mapped[str] = mapped_column(
        String(100), nullable=False, default="default", comment="Key别名（同一厂商可存多个）"
    )
    # 密钥使用 Fernet 对称加密存储，key 从 CONCLAVE_SECRET_KEY 派生
    encrypted_key: Mapped[str] = mapped_column(Text, nullable=False)
    base_url: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        UniqueConstraint("provider", "name", name="uq_api_key_provider_name"),
        Index("idx_api_keys_provider", "provider"),
    )
