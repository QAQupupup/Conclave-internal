# 文档上传：POST /meetings/{id}/documents 上传 md，切块入库 + 元数据持久化
from __future__ import annotations

import hashlib
import re
import uuid
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.db.engine import async_session_factory
from app.db.models import DocumentModel
from app.orchestrator.runner import get_state
from app.rag.chunker import chunk_markdown
from app.rag.store import get_store

router = APIRouter(prefix="/meetings", tags=["documents"])

# 文件大小限制：10MB
MAX_UPLOAD_SIZE = 10 * 1024 * 1024
# 允许的文件扩展名
_ALLOWED_EXTENSIONS = {".md", ".markdown", ".txt"}
# 文件名安全化正则：只保留字母、数字、下划线、连字符、中文
_SAFE_FILENAME_RE = re.compile(r"[^\w\u4e00-\u9fff\-]", re.UNICODE)


@router.post("/{meeting_id}/documents")
async def upload_document(meeting_id: str, file: UploadFile = File(...)) -> dict[str, Any]:
    """上传 Markdown 文档，切块入库到该会议的向量库，并持久化文档元数据"""
    state = get_state(meeting_id)
    if state is None:
        raise HTTPException(status_code=404, detail="会议不存在，请先创建")

    # [SECURITY-FIX] 文件大小预检查（Content-Length 头），避免大文件全量读入内存
    if file.size is not None and file.size > MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"文件过大：{file.size // 1024}KB，限制 {MAX_UPLOAD_SIZE // 1024 // 1024}MB",
        )

    # 文件大小限制（读取后校验实际大小）
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

    # 切块入库
    chunks = chunk_markdown(content, doc_id)
    store = get_store(meeting_id)
    store.add_chunks(chunks)
    # 缓存完整原文，支持跨 chunk 惰性展开
    store.store_raw_text(doc_id, content)

    # 记录文档摘要供 clarify 阶段使用
    summary = f"{doc_id}（{len(chunks)} 块）"
    state.doc_summaries.append(summary)

    # 持久化文档元数据到数据库
    doc_db_id = uuid.uuid4().hex
    content_hash = hashlib.sha256(raw).hexdigest()
    try:
        async with async_session_factory() as session:
            doc_record = DocumentModel(
                id=doc_db_id,
                meeting_id=meeting_id,
                filename=doc_id + ext,
                original_name=filename,
                content_type=file.content_type or "text/markdown",
                size_bytes=len(raw),
                chunk_count=len(chunks),
                content_hash=content_hash,
            )
            session.add(doc_record)
            await session.commit()
    except Exception as e:
        # 元数据持久化失败不影响主流程（切块已入库）
        import logging

        logging.getLogger("routers.documents").warning("文档元数据持久化失败: %s", str(e)[:100])

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
    """列出会议已上传的文档"""
    from sqlalchemy import select

    try:
        async with async_session_factory() as session:
            result = await session.execute(
                select(DocumentModel)
                .where(DocumentModel.meeting_id == meeting_id)
                .order_by(DocumentModel.created_at.desc())
            )
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
                    "created_at": d.created_at.isoformat() if d.created_at else None,
                }
                for d in docs
            ],
        }
    except Exception as e:
        return {"meeting_id": meeting_id, "documents": [], "error": str(e)[:100]}
