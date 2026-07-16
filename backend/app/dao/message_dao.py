"""发言记录（messages）持久化。

提供保存与按会议列出发言记录的能力。
原迁移自 app/db_legacy.py，逻辑未做任何修改。
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text

from app.db.engine import async_session_factory


async def save_message(msg: dict[str, Any]) -> None:
    """保存发言记录"""
    async with async_session_factory() as session:
        await session.execute(
            text(
                """
                INSERT INTO messages
                (id, meeting_id, agent_role, stage, content, claim_refs, evidence_refs, created_at)
                VALUES (:id, :meeting_id, :agent_role, :stage, :content, :claim_refs, :evidence_refs, :created_at)
                ON CONFLICT(id) DO UPDATE SET
                    meeting_id=excluded.meeting_id,
                    agent_role=excluded.agent_role,
                    stage=excluded.stage,
                    content=excluded.content,
                    claim_refs=excluded.claim_refs,
                    evidence_refs=excluded.evidence_refs,
                    created_at=excluded.created_at
                """
            ),
            {
                "id": msg["id"],
                "meeting_id": msg["meeting_id"],
                "agent_role": msg["agent_role"],
                "stage": msg["stage"],
                "content": msg["content"],
                "claim_refs": json.dumps(msg.get("claim_refs", []), ensure_ascii=False),
                "evidence_refs": json.dumps(msg.get("evidence_refs", []), ensure_ascii=False),
                "created_at": msg["created_at"],
            },
        )
        await session.commit()


async def list_messages(meeting_id: str) -> list[dict[str, Any]]:
    """取某会议的全部发言"""
    async with async_session_factory() as session:
        result = await session.execute(
            text("SELECT * FROM messages WHERE meeting_id = :meeting_id ORDER BY created_at ASC"),
            {"meeting_id": meeting_id},
        )
        rows = result.mappings().all()
        out = []
        for row in rows:
            d = dict(row)
            d["claim_refs"] = json.loads(d["claim_refs"])
            d["evidence_refs"] = json.loads(d["evidence_refs"])
            out.append(d)
        return out
