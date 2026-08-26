"""上传文档元数据 ORM 模型：documents / knowledge_spaces / meeting_document_refs。

跨模块关联一律通过显式 join 实现，不使用 relationship（见 docs/sql-development-rules.md
§1.2 红线）。历史 relationship 声明已注释保留、未删除。

P1 知识资产化改造（2026-08-06）：
- documents 不再强绑会议（meeting_id 改为可空，表示"首次上传来源"）；
  文档归属 knowledge_spaces（space_id 非空），会议通过 meeting_document_refs 引用。
- 新增 status（active/recycled）实现回收箱生命周期；recycled_at 标记回收时间。
- 新增 raw_content 持久化原文，支撑重启后 reindex 与跨 chunk 惰性展开。
- 临时上传附件进入租户默认 space（scope=team, kind=ephemeral 语义由 TTL 实现），
  可一键转存到 persistent space。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin, TenantScopeMixin, UUIDPrimaryKeyMixin, utcnow


# ============================================================
# knowledge_spaces — 知识空间（资产容器）
# ============================================================
class KnowledgeSpaceModel(Base, UUIDPrimaryKeyMixin, CreatedAtMixin, TenantScopeMixin):
    __tablename__ = "knowledge_spaces"

    name: Mapped[str] = mapped_column(String(200), nullable=False, default="默认空间")
    # scope: personal | team；首期只实现 team 默认空间，personal 后续扩展
    scope: Mapped[str] = mapped_column(String(20), nullable=False, default="team")
    # kind: persistent | ephemeral；ephemeral 走 TTL 回收，persistent 永久保留
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="ephemeral")
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        Index("idx_knowledge_spaces_tenant", "tenant_id"),
        Index("idx_knowledge_spaces_tenant_default", "tenant_id", "is_default"),
    )


# ============================================================
# meeting_document_refs — 会议对文档的引用（多对多）
# ============================================================
class MeetingDocumentRefModel(Base, TenantScopeMixin):
    __tablename__ = "meeting_document_refs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    meeting_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    document_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    added_by: Mapped[str] = mapped_column(String(100), nullable=False, default="system")

    __table_args__ = (
        Index("idx_mdr_meeting_doc", "meeting_id", "document_id", unique=True),
        Index("idx_mdr_tenant", "tenant_id"),
    )


# ============================================================
# documents — 上传文档元数据（资产化）
# ============================================================
class DocumentModel(Base, UUIDPrimaryKeyMixin, CreatedAtMixin, TenantScopeMixin):
    __tablename__ = "documents"

    # 资产归属：文档属于某个知识空间；会议仅通过 ref 引用
    space_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    # 首次上传来源会议（可空）；区别于"当前引用该文档的会议"
    meeting_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("meetings.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    original_name: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    content_type: Mapped[str] = mapped_column(String(100), nullable=False, default="text/markdown")
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    content_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, default="", comment="SHA256 of file content for dedup"
    )
    # 原文持久化：支撑重启后 reindex 与跨 chunk 惰性展开（旧实现仅存内存，重启即丢）
    raw_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 生命周期：active（可用/可检索）| recycled（回收箱，原文保留但检索不命中）
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    recycled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # meeting: Mapped[MeetingModel | None] = relationship()  # 历史 relationship，已注释

    __table_args__ = (
        Index("idx_documents_space", "space_id"),
        Index("idx_documents_meeting", "meeting_id"),
        Index("idx_documents_status", "status"),
    )
