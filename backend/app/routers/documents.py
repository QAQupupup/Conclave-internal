# 文档上传：POST /meetings/{id}/documents 上传 md，切块入库
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.orchestrator.runner import get_state
from app.rag.chunker import chunk_markdown
from app.rag.store import get_store

router = APIRouter(prefix="/meetings", tags=["documents"])


@router.post("/{meeting_id}/documents")
async def upload_document(meeting_id: str, file: UploadFile = File(...)) -> dict[str, Any]:
    """上传 Markdown 文档，切块入库到该会议的向量库"""
    state = get_state(meeting_id)
    if state is None:
        raise HTTPException(status_code=404, detail="会议不存在，请先创建")

    # 读取内容
    raw = await file.read()
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError:
        content = raw.decode("gbk", errors="replace")

    # 以文件名（去扩展名）作为 doc_id
    doc_id = file.filename or "doc"
    if "." in doc_id:
        doc_id = doc_id.rsplit(".", 1)[0]
    doc_id = doc_id.replace(" ", "_")

    # 切块入库
    chunks = chunk_markdown(content, doc_id)
    store = get_store(meeting_id)
    store.add_chunks(chunks)

    # 记录文档摘要供 clarify 阶段使用
    summary = f"{doc_id}（{len(chunks)} 块）"
    state.doc_summaries.append(summary)

    return {
        "meeting_id": meeting_id,
        "doc_id": doc_id,
        "chunks": len(chunks),
        "sections": [c.section for c in chunks],
        "char_count": len(content),
    }
