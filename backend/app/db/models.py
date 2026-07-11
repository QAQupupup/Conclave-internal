"""SQLAlchemy 2.0 ORM 模型 — 映射当前全部 7 张表。

使用 DeclarativeBase + mapped_column 风格，兼容 PostgreSQL 和 SQLite 双后端。
迁移路径：SQLite 中的 TEXT/INTEGER → PostgreSQL 中的 TEXT/BOOLEAN/TIMESTAMPTZ/JSONB。
"""
from __future__ import annotations

from datetime import datetime, timezone
from sqlalchemy import (
    String, Text, Integer, Boolean, Float, DateTime, ForeignKey, Index, UniqueConstraint,
    func, text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


# ============================================================
# 1. meetings — 会议主表
# ============================================================
class MeetingModel(Base):
    __tablename__ = "meetings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    topic: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="running",
        comment="running|paused|aborted|done|deleted"
    )
    stage: Mapped[str] = mapped_column(
        String(20), nullable=False, default="clarify",
        comment="clarify|intra_team|cross_team|evidence_check|arbitrate|produce"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    # 完整 MeetingState JSON 快照
    payload: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    # 数据格式版本号（用于未来 schema 演进时的数据迁移）
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # 关系
    messages: Mapped[list["MessageModel"]] = relationship(
        back_populates="meeting", cascade="all, delete-orphan",
    )
    events: Mapped[list["EventModel"]] = relationship(
        back_populates="meeting", cascade="all, delete-orphan",
    )
    tags: Mapped[list["MeetingTagModel"]] = relationship(
        back_populates="meeting", cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("idx_meetings_status", "status"),
        Index("idx_meetings_created", "created_at"),
    )


# ============================================================
# 2. messages — 发言记录
# ============================================================
class MessageModel(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    meeting_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("meetings.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    agent_role: Mapped[str] = mapped_column(String(50), nullable=False)
    stage: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    claim_refs: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    evidence_refs: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    meeting: Mapped["MeetingModel"] = relationship(back_populates="messages")

    __table_args__ = (
        Index("idx_messages_meeting", "meeting_id"),
    )


# ============================================================
# 3. events — 事件溯源
# ============================================================
class EventModel(Base):
    __tablename__ = "events"

    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    meeting_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("meetings.id", ondelete="CASCADE"),
        nullable=False,
    )
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    trace_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    meeting: Mapped["MeetingModel"] = relationship(back_populates="events")

    __table_args__ = (
        Index("idx_events_meeting", "meeting_id"),
        Index("idx_events_meeting_seq", "meeting_id", "seq"),
    )


# ============================================================
# 4. user_preferences — 用户偏好
# ============================================================
class UserPreferenceModel(Base):
    __tablename__ = "user_preferences"

    user_id: Mapped[str] = mapped_column(
        String(50), primary_key=True, default="default",
    )
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


# ============================================================
# 5. meeting_tags — 会议标签
# ============================================================
class MeetingTagModel(Base):
    __tablename__ = "meeting_tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    meeting_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("meetings.id", ondelete="CASCADE"),
        nullable=False,
    )
    tag: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    meeting: Mapped["MeetingModel"] = relationship(back_populates="tags")

    __table_args__ = (
        UniqueConstraint("meeting_id", "tag", name="uq_meeting_tag"),
        Index("idx_meeting_tags_meeting", "meeting_id"),
        Index("idx_meeting_tags_tag", "tag"),
    )


# ============================================================
# 6. agent_roles — Agent 角色定义
# ============================================================
class AgentRoleModel(Base):
    __tablename__ = "agent_roles"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    perspective: Mapped[str] = mapped_column(Text, nullable=False, default="")
    expertise_domains: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    risk_appetite: Mapped[str] = mapped_column(
        String(20), nullable=False, default="balanced",
    )
    default_stance: Mapped[str] = mapped_column(Text, nullable=False, default="")
    evidence_preference: Mapped[str] = mapped_column(
        String(20), nullable=False, default="balanced",
    )
    model_override: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    background_brief: Mapped[str] = mapped_column(Text, nullable=False, default="")
    prompt_template: Mapped[str] = mapped_column(Text, nullable=False, default="")
    is_builtin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        Index("idx_agent_roles_active", "is_active"),
    )


# ============================================================
# 7. net_auth_requests — 网络授权申请
# ============================================================
class NetAuthRequestModel(Base):
    __tablename__ = "net_auth_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    meeting_id: Mapped[str] = mapped_column(
        String(36), nullable=False, index=True,
    )
    stage: Mapped[str] = mapped_column(String(20), nullable=False)
    code_snippet: Mapped[str] = mapped_column(Text, nullable=False)
    requested_level: Mapped[str] = mapped_column(String(20), nullable=False)
    detected_level: Mapped[str] = mapped_column(String(20), nullable=False)
    failure_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    stderr_output: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending",
        comment="pending|approved|denied|expired",
    )
    review_action: Mapped[str | None] = mapped_column(String(20), nullable=True)
    review_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    __table_args__ = (
        Index("idx_auth_meeting", "meeting_id"),
        Index("idx_auth_status", "status"),
    )


# ============================================================
# 8. meeting_aux — 会议辅助大字段存储（MeetingState 瘦身）
# ============================================================
# 将 MeetingState 中的大字段（llm_trace, evidence_set, conclusion_chain,
# borrowed_agents）从主 payload JSON 中分离，减少热路径序列化开销。
# 采用 (meeting_id, key) 组合主键，支持灵活扩展。
class MeetingAuxModel(Base):
    __tablename__ = "meeting_aux"

    meeting_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("meetings.id", ondelete="CASCADE"),
        primary_key=True,
    )
    key: Mapped[str] = mapped_column(
        String(50), primary_key=True,
        comment="aux field name: llm_trace|evidence_set|conclusion_chain|borrowed_agents",
    )
    value_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="{}",
        comment="JSON-serialized aux field value",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        Index("idx_meeting_aux_meeting", "meeting_id"),
    )


# ============================================================
# 9. api_keys — BYOK API Key 加密持久化
# ============================================================
class ApiKeyModel(Base):
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(50), nullable=False, index=True,
                                          comment="LLM厂商: siliconflow/deepseek/openai/openrouter/custom")
    name: Mapped[str] = mapped_column(String(100), nullable=False, default="default",
                                      comment="Key别名（同一厂商可存多个）")
    # 密钥使用 Fernet 对称加密存储，key 从 CONCLAVE_SECRET_KEY 派生
    encrypted_key: Mapped[str] = mapped_column(Text, nullable=False)
    base_url: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        UniqueConstraint("provider", "name", name="uq_api_key_provider_name"),
        Index("idx_api_keys_provider", "provider"),
    )


# ============================================================
# 10. documents — 上传文档元数据
# ============================================================
class DocumentModel(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    meeting_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("meetings.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    original_name: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    content_type: Mapped[str] = mapped_column(String(100), nullable=False, default="text/markdown")
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="",
                                              comment="SHA256 of file content for dedup")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    meeting: Mapped["MeetingModel"] = relationship()

    __table_args__ = (
        Index("idx_documents_meeting", "meeting_id"),
    )


# ============================================================
# 11. cost_records — LLM/工具调用成本记录
# ============================================================
class CostRecordModel(Base):
    __tablename__ = "cost_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    meeting_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("meetings.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    stage: Mapped[str] = mapped_column(String(30), nullable=False, default="")
    node: Mapped[str] = mapped_column(String(50), nullable=False, default="",
                                      comment="调用节点: llm|tool|sandbox")
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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        Index("idx_cost_meeting", "meeting_id"),
        Index("idx_cost_created", "created_at"),
        Index("idx_cost_node", "node"),
    )