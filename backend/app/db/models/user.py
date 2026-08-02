"""用户偏好与 BYOK API Key ORM 模型：user_preferences / api_keys / user_settings。"""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import (
    Base,
    IntegerPrimaryKeyMixin,
    TenantScopeMixin,
    TimestampMixin,
    UpdatedAtMixin,
)


# ============================================================
# user_preferences — 用户偏好
# ============================================================
class UserPreferenceModel(Base, UpdatedAtMixin, TenantScopeMixin):
    __tablename__ = "user_preferences"

    user_id: Mapped[str] = mapped_column(
        String(50),
        primary_key=True,
        default="default",
    )
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)


# ============================================================
# api_keys — BYOK API Key 加密持久化
# ============================================================
class ApiKeyModel(Base, IntegerPrimaryKeyMixin, TimestampMixin, TenantScopeMixin):
    __tablename__ = "api_keys"

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
    # 个人级 Key：user_id 非空表示个人 Key；NULL 表示租户级 Key
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", "provider", "name", name="uq_api_key_tenant_user_provider_name"),
        Index("idx_api_keys_provider", "provider"),
        Index("idx_api_keys_tenant_id", "tenant_id"),
        Index("idx_api_keys_user_id", "user_id"),
    )


# ============================================================
# user_settings — 用户级配置（KV 结构）
# ============================================================
class UserSettingModel(Base, IntegerPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "user_settings"

    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    value_type: Mapped[str] = mapped_column(String(20), nullable=False, default="string")

    __table_args__ = (
        UniqueConstraint("user_id", "key", name="uq_user_settings_user_key"),
        CheckConstraint(
            "value_type IN ('string','int','float','bool','json')",
            name="ck_user_settings_value_type",
        ),
    )
