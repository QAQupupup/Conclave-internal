# 文档上传：POST /meetings/{id}/documents 上传 md，切块入库 + 元数据持久化（资产化）
from __future__ import annotations

import hashlib
import logging
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import async_session_factory
from app.db.models import DocumentModel, KnowledgeSpaceModel, MeetingDocumentRefModel
from app.orchestrator.runner import get_state
from app.rag.chunker import chunk_markdown
from app.rag.store import get_store
from app.tenants import current_tenant_id

logger = logging.getLogger("routers.documents")

router = APIRouter(prefix="/meetings", tags=["documents"])

# 文件大小限制：10MB
MAX_UPLOAD_SIZE = 10 * 1024 * 1024
# 允许的文件扩展名（P1 仅 md/txt；pdf/docx 等解析为后续里程碑）
_ALLOWED_EXTENSIONS = {".md", ".markdown", ".txt"}
# 文件名安全化正则：只保留字母、数字、下划线、连字符、中文
_SAFE_FILENAME_RE = re.compile(r"[^\w\u4e00-\u9fff\-]", re.UNICODE)

# TTL（天）：临时附件缓冲期 → 回收箱 → 物理删除
EPHEMERAL_TTL_DAYS = int(os.environ.get("CONCLAVE_EPHEMERAL_TTL_DAYS", "7"))
RECYCLE_TTL_DAYS = int(os.environ.get("CONCLAVE_RECYCLE_TTL_DAYS", "30"))


async def _get_or_create_default_space(session: AsyncSession, tid: int | None) -> KnowledgeSpaceModel:
    """获取（或创建）租户默认知识空间。首期单一默认空间，UI 不暴露空间概念。"""
    q = select(KnowledgeSpaceModel).where(
        and_(KnowledgeSpaceModel.tenant_id == tid, KnowledgeSpaceModel.is_default.is_(True))
    )
    result = await session.execute(q)
    space = result.scalars().first()
    if space is None:
        space = KnowledgeSpaceModel(
            id=uuid.uuid4().hex,
            tenant_id=tid,
            name="默认空间",
            scope="team",
            kind="ephemeral",
            is_default=True,
        )
        session.add(space)
        await session.flush()
    return space


async def _cleanup_ephemeral_docs(session: AsyncSession, tid: int | None) -> None:
    """惰性 TTL 清理：缓冲期超期 → 回收箱；回收箱超期 → 物理删除。

    设计要点（ADR §3.1）：
    - 仅处理 ephemeral 默认空间的文档；persistent 空间永不自动清理。
    - meeting_document_refs 永不在 TTL 中删除——历史会议文档列表与原文始终可读。
    - 回收箱内文档检索不命中（status=recycled），但可一键恢复。
    """
    now = datetime.now(timezone.utc)
    buffer_deadline = now - timedelta(days=EPHEMERAL_TTL_DAYS)
    recycle_deadline = now - timedelta(days=RECYCLE_TTL_DAYS)

    # 1) 缓冲期超期且仍 active → 回收箱
    q_active = select(DocumentModel).where(
        and_(
            DocumentModel.tenant_id == tid,
            DocumentModel.status == "active",
            DocumentModel.created_at < buffer_deadline,
        )
    )
    active_docs = (await session.execute(q_active)).scalars().all()
    for d in active_docs:
        d.status = "recycled"
        d.recycled_at = now

    # 2) 回收箱超期 → 物理删除（含 chunk 由调用方在 reindex 时同步；此处仅删元数据）
    q_recycled = select(DocumentModel).where(
        and_(
            DocumentModel.tenant_id == tid,
            DocumentModel.status == "recycled",
            DocumentModel.recycled_at < recycle_deadline,
        )
    )
    recycled_docs = (await session.execute(q_recycled)).scalars().all()
    for d in recycled_docs:
        await session.delete(d)

    if active_docs or recycled_docs:
        await session.commit()
        logger.info("TTL 清理：%d 篇转回收箱，%d 篇物理删除", len(active_docs), len(recycled_docs))


@router.post("/{meeting_id}/documents")
async def upload_document(meeting_id: str, file: UploadFile = File(...)) -> dict[str, Any]:
    """上传 Markdown 文档，切块入库到该会议的向量库，并持久化文档元数据（资产化）。"""
    state = get_state(meeting_id)
    if state is None:
        raise HTTPException(status_code=404, detail="会议不存在，请先创建")

    # 文件大小预检查（Content-Length 头），避免大文件全量读入内存
    if file.size is not None and file.size > MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"文件过大：{file.size // 1024}KB，限制 {MAX_UPLOAD_SIZE // 1024 // 1024}MB",
        )

    raw = await file.read()
    if len(raw) > MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"文件过大：{len(raw)} bytes，限制 {MAX_UPLOAD_SIZE} bytes",
        )

    # 文件类型校验
    filename = file.filename or "doc"
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext and ext not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=f"不支持的文件类型：{ext}，仅支持 {_ALLOWED_EXTENSIONS}",
        )

    # 读取内容
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError:
        content = raw.decode("gbk", errors="replace")

    # 文件名安全化：去除路径穿越、特殊字符
    base_name = filename.rsplit(".", 1)[0] if "." in filename else filename
    doc_id = _SAFE_FILENAME_RE.sub("_", base_name).strip("_")
    if not doc_id:
        doc_id = "doc"

    # 切块入库（store 实例持有 meeting_id 作用域，Qdrant payload 含 meeting_id）
    chunks = chunk_markdown(content, doc_id)
    store = get_store(meeting_id)
    try:
        await store.add_chunks(chunks)
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"文档入库失败，Embedding 服务暂时不可用，请稍后重试: {str(e)[:150]}",
        ) from e
    # 缓存完整原文，支持跨 chunk 惰性展开（会话内）
    store.store_raw_text(doc_id, content)

    # 记录文档摘要供 clarify 阶段使用
    summary = f"{doc_id}（{len(chunks)} 块）"
    state.doc_summaries.append(summary)

    # 持久化：默认空间 + 文档元数据（含原文）+ 会议引用
    doc_db_id = uuid.uuid4().hex
    content_hash = hashlib.sha256(raw).hexdigest()
    tid = current_tenant_id()
    try:
        async with async_session_factory() as session:
            space = await _get_or_create_default_space(session, tid)
            doc_record = DocumentModel(
                id=doc_db_id,
                tenant_id=tid,
                space_id=space.id,
                meeting_id=meeting_id,
                filename=doc_id + ext,
                original_name=filename,
                content_type=file.content_type or "text/markdown",
                size_bytes=len(raw),
                chunk_count=len(chunks),
                content_hash=content_hash,
                raw_content=content,  # 持久化原文，支撑重启后 reindex
                status="active",
            )
            session.add(doc_record)
            session.add(
                MeetingDocumentRefModel(
                    meeting_id=meeting_id,
                    document_id=doc_db_id,
                    tenant_id=tid,
                    added_by="upload",
                )
            )
            await session.commit()
    except Exception as e:
        logger.warning("文档元数据持久化失败: %s", str(e)[:100])

    return {
        "meeting_id": meeting_id,
        "doc_id": doc_id,
        "chunks": len(chunks),
        "sections": [c.section for c in chunks],
        "char_count": len(content),
        "document_id": doc_db_id,
    }


@router.get("/{meeting_id}/documents")
async def list_documents(meeting_id: str) -> dict[str, Any]:
    """列出会议已引用的文档（按租户过滤 + TTL 惰性清理）。"""
    tid = current_tenant_id()
    try:
        async with async_session_factory() as session:
            await _cleanup_ephemeral_docs(session, tid)
            # 通过 meeting_document_refs 取本会议引用的文档（含回收箱内，UI 标"已归档"）
            q = (
                select(DocumentModel)
                .join(
                    MeetingDocumentRefModel,
                    MeetingDocumentRefModel.document_id == DocumentModel.id,
                )
                .where(
                    and_(
                        MeetingDocumentRefModel.meeting_id == meeting_id,
                        MeetingDocumentRefModel.tenant_id == tid,
                    )
                )
                .order_by(DocumentModel.created_at.desc())
            )
            result = await session.execute(q)
            docs = result.scalars().all()
        return {
            "meeting_id": meeting_id,
            "documents": [
                {
                    "id": d.id,
                    "filename": d.filename,
                    "original_name": d.original_name,
                    "content_type": d.content_type,
                    "size_bytes": d.size_bytes,
                    "chunk_count": d.chunk_count,
                    "status": d.status,
                    "recycled_at": d.recycled_at.isoformat() if d.recycled_at else None,
                    "created_at": d.created_at.isoformat() if d.created_at else None,
                }
                for d in docs
            ],
        }
    except Exception as e:
        return {"meeting_id": meeting_id, "documents": [], "error": str(e)[:100]}


@router.post("/{meeting_id}/documents/reindex")
async def reindex_documents(meeting_id: str) -> dict[str, Any]:
    """从数据库原文重建该会议向量索引（重启后恢复 / 修复索引漂移）。

    仅处理本会议引用的 active 文档；recycled 文档不进索引。
    """
    tid = current_tenant_id()
    async with async_session_factory() as session:
        q = (
            select(DocumentModel)
            .join(
                MeetingDocumentRefModel,
                MeetingDocumentRefModel.document_id == DocumentModel.id,
            )
            .where(
                and_(
                    MeetingDocumentRefModel.meeting_id == meeting_id,
                    MeetingDocumentRefModel.tenant_id == tid,
                    DocumentModel.status == "active",
                    DocumentModel.raw_content.isnot(None),
                )
            )
        )
        docs = (await session.execute(q)).scalars().all()

    store = get_store(meeting_id)
    total = 0
    for d in docs:
        assert d.raw_content is not None
        chunks = chunk_markdown(d.raw_content, d.filename.rsplit(".", 1)[0] or "doc")
        await store.add_chunks(chunks)
        store.store_raw_text(d.filename.rsplit(".", 1)[0] or "doc", d.raw_content)
        total += len(chunks)
    return {"meeting_id": meeting_id, "reindexed_documents": len(docs), "reindexed_chunks": total}
