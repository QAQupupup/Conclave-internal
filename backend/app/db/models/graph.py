"""知识图谱与图 RAG ORM 模型：graph_edges / entities / chunk_entities / document_relations。

GraphRAG-lite 数据底座（docs/design/knowledge-rag-orchestration-review.md §3.3 / §3.4）。

- ``graph_edges``：物化边（supports / contradicts / derived_from / cites / related）。
  会议 DONE 时由 ``state.conflicts``（→ contradicts）、``state.evidence_set``（→ supports + evidence 节点）物化入库。
- ``entities`` + ``chunk_entities``：惰性实体抽取结果（LLM temp 0.0，ADR 决策 3：惰性 + 后台闲时）。
- ``document_relations``：文档间关系（duplicate / similar / derived / cites），由 content_hash / 向量质心 / 共享实体推断。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin, TenantScopeMixin, UUIDPrimaryKeyMixin, utcnow

if TYPE_CHECKING:
    pass

# 边类型白名单（与 routers/graph.py EDGE_TYPES 对齐，新增 supports/contradicts 语义边）
GRAPH_EDGE_TYPES = {
    "supports",
    "contradicts",
    "relates_to",
    "proposed_by",
    "derived_from",
    "has_conflict",
    "cites",
    "related",
}
# 节点类型白名单
GRAPH_NODE_TYPES = {"topic", "claim", "evidence", "conflict", "source", "agent", "entity"}


# ============================================================
# graph_edges — 物化知识图谱边
# ============================================================
class GraphEdgeModel(Base, UUIDPrimaryKeyMixin, CreatedAtMixin, TenantScopeMixin):
    __tablename__ = "graph_edges"

    meeting_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    # 端点类型：claim | evidence | meeting | entity | conflict | source | agent
    source_type: Mapped[str] = mapped_column(String(20), nullable=False, default="claim")
    source_id: Mapped[str] = mapped_column(String(120), nullable=False)
    target_type: Mapped[str] = mapped_column(String(20), nullable=False, default="claim")
    target_id: Mapped[str] = mapped_column(String(120), nullable=False)
    # 边类型：supports | contradicts | derived_from | cites | related ...
    relation_type: Mapped[str] = mapped_column(String(20), nullable=False, default="relates_to")
    weight: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    # 关联的证据 ID（supports 边指向 evidence 节点时记录）；可选
    evidence_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # 该边的语义标注（如冲突摘要、论据文本），用于前端溯源展示
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("idx_graph_edges_meeting", "meeting_id"),
        Index("idx_graph_edges_tenant", "tenant_id"),
        Index("idx_graph_edges_relation", "relation_type"),
        UniqueConstraint(
            "meeting_id",
            "source_type",
            "source_id",
            "target_type",
            "target_id",
            "relation_type",
            name="uq_graph_edge",
        ),
    )


# ============================================================
# entities — 业务实体（惰性抽取）
# ============================================================
class EntityModel(Base, UUIDPrimaryKeyMixin, CreatedAtMixin, TenantScopeMixin):
    __tablename__ = "entities"

    meeting_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    # 实体名称（归一化小写，用于跨文档共享识别）
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    name_norm: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False, default="concept")
    mention_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __table_args__ = (
        Index("idx_entities_meeting", "meeting_id"),
        Index("idx_entities_tenant", "tenant_id"),
        UniqueConstraint("tenant_id", "name_norm", name="uq_entity_tenant_name"),
    )


# ============================================================
# chunk_entities — chunk 到实体的归属边
# ============================================================
class ChunkEntityModel(Base, TenantScopeMixin):
    __tablename__ = "chunk_entities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    meeting_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    doc_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    chunk_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    # 显著性（实体在该 chunk 中的重要度，0-1）
    salience: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)

    __table_args__ = (
        Index("idx_chunk_entities_chunk", "chunk_id"),
        Index("idx_chunk_entities_entity", "entity_id"),
        Index("idx_chunk_entities_tenant", "tenant_id"),
        UniqueConstraint("chunk_id", "entity_id", name="uq_chunk_entity"),
    )


# ============================================================
# document_relations — 文档间关系
# ============================================================
class DocumentRelationModel(Base, TenantScopeMixin):
    __tablename__ = "document_relations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    src_doc_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    dst_doc_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    # duplicate | similar | derived | cites
    relation_type: Mapped[str] = mapped_column(String(20), nullable=False, default="similar")
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    # pipeline（自动抽取）| user（用户手动）
    created_by: Mapped[str] = mapped_column(String(20), nullable=False, default="pipeline")
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        Index("idx_doc_relations_src", "src_doc_id"),
        Index("idx_doc_relations_dst", "dst_doc_id"),
        Index("idx_doc_relations_tenant", "tenant_id"),
        UniqueConstraint("src_doc_id", "dst_doc_id", "relation_type", name="uq_doc_relation"),
    )
