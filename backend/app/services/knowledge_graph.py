# 知识图谱物化 + 惰性实体抽取（GraphRAG-lite）。
#
# 会议 DONE 时调用 materialize_meeting_knowledge(state)：
#   1. state.conflicts       → contradicts 边（claim 节点互连）
#   2. state.evidence_set    → supports 边 + evidence 节点
#   3. 议题向量 upsert（DONE 状态，供临近话题聚类）
#   4. 触发惰性实体抽取（fire-and-forget，仅真实 LLM 配置时；否则优雅跳过）
#
# 设计依据：docs/design/knowledge-rag-orchestration-review.md §3.3 / §3.4
from __future__ import annotations

import asyncio
import hashlib
import json
import re
from typing import Any

from sqlalchemy import text

from app.db.engine import async_session_factory
from app.logging_config import get_logger
from app.rag.topic_index import get_topic_index

logger = get_logger("services.knowledge_graph")

# 后台实体抽取任务引用（防止 GC 提前回收导致协程未执行）
_bg_tasks: set[asyncio.Task] = set()


def _edge_id(meeting_id: str, source: str, target: str, relation: str) -> str:
    raw = f"{meeting_id}|{source}|{target}|{relation}".encode()
    return "ge-" + hashlib.sha256(raw).hexdigest()[:16]


def _claim_node_id(meeting_id: str, ref_or_text: str) -> str:
    key = ref_or_text.strip()
    if not key:
        key = "unknown"
    return f"claim:{meeting_id}:{hashlib.sha256(key.encode()).hexdigest()[:12]}"


def _norm_text(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


async def materialize_meeting_knowledge(state: Any) -> None:
    """会议 DONE 物化：冲突/证据 → 图谱边，议题向量更新，触发实体抽取。

    任何异常都被吞掉（图谱是增值能力，绝不让其阻塞/污染会议主流程）。
    """
    try:
        tid = state.tenant_id
        mid = state.meeting_id
        async with async_session_factory() as session:
            # 先清旧边（幂等：重跑 DONE 不产生重复）
            await session.execute(
                text("DELETE FROM graph_edges WHERE meeting_id = :mid"),
                {"mid": mid},
            )
            edges: list[dict[str, Any]] = []
            # 1. conflicts → contradicts 边
            for c in state.conflicts or []:
                side_a = _norm_text(c.get("side_a", ""))
                side_b = _norm_text(c.get("side_b", ""))
                refs = c.get("claim_refs") or []
                a_id = _claim_node_id(mid, refs[0] if len(refs) > 0 else side_a)
                b_id = _claim_node_id(mid, refs[1] if len(refs) > 1 else side_b)
                if a_id == b_id:
                    continue
                edges.append(
                    {
                        "id": _edge_id(mid, a_id, b_id, "contradicts"),
                        "source_type": "claim",
                        "source_id": a_id,
                        "target_type": "claim",
                        "target_id": b_id,
                        "relation_type": "contradicts",
                        "weight": 1.0,
                        "evidence_id": None,
                        "note": _norm_text(c.get("summary", ""))[:500] or None,
                    }
                )
            # 2. evidence_set → supports 边 + evidence 节点
            for es in state.evidence_set or []:
                cid = es.get("conflict_id", "")
                # 找到该 conflict 的两条 claim 节点，按 supports 指向 a/b
                claim_a = None
                claim_b = None
                for c in state.conflicts or []:
                    if c.get("id") == cid or c.get("conflict_id") == cid:
                        refs = c.get("claim_refs") or []
                        sa = _norm_text(c.get("side_a", ""))
                        sb = _norm_text(c.get("side_b", ""))
                        claim_a = _claim_node_id(mid, refs[0] if len(refs) > 0 else sa)
                        claim_b = _claim_node_id(mid, refs[1] if len(refs) > 1 else sb)
                        break
                for idx, a in enumerate(es.get("assessments", []) or []):
                    ev_id = f"evidence:{cid}:{idx}"
                    supports = a.get("supports", "neutral")
                    target = None
                    if supports == "a" and claim_a:
                        target = claim_a
                    elif supports == "b" and claim_b:
                        target = claim_b
                    elif claim_a:
                        target = claim_a
                    if not target:
                        continue
                    edges.append(
                        {
                            "id": _edge_id(mid, ev_id, target, "supports"),
                            "source_type": "evidence",
                            "source_id": ev_id,
                            "target_type": "claim",
                            "target_id": target,
                            "relation_type": "supports",
                            "weight": 0.8,
                            "evidence_id": ev_id,
                            "note": _norm_text(a.get("quote", ""))[:300] or None,
                        }
                    )
            # 批量插入
            for e in edges:
                await session.execute(
                    text(
                        """
                        INSERT INTO graph_edges
                            (id, tenant_id, meeting_id, source_type, source_id,
                             target_type, target_id, relation_type, weight, evidence_id, note, created_at)
                        VALUES
                            (:id, :tid, :mid, :st, :sid, :tt, :tid2, :rel, :w, :ev, :note, NOW())
                        ON CONFLICT (id) DO NOTHING
                        """
                    ),
                    {
                        "id": e["id"],
                        "tid": tid,
                        "mid": mid,
                        "st": e["source_type"],
                        "sid": e["source_id"],
                        "tt": e["target_type"],
                        "tid2": e["target_id"],
                        "rel": e["relation_type"],
                        "w": e["weight"],
                        "ev": e["evidence_id"],
                        "note": e["note"],
                    },
                )
            await session.commit()
            if edges:
                logger.info("物化图谱边 %d 条（会议 %s）", len(edges), mid)

        # 3. 议题向量更新为 DONE 状态（供临近话题聚类）
        try:
            summary = (state.artifact or {}).get("answer", "") or (state.artifact or {}).get("title", "")
            await get_topic_index().upsert(
                meeting_id=mid,
                tenant_id=tid,
                topic=state.topic or state.clarified_topic or "",
                status="done",
                deliverable_type=state.deliverable_type,
                summary=summary,
                tags=[],
            )
        except Exception as e:
            logger.warning("DONE 议题向量更新失败（忽略）: %s", str(e)[:120])

        # 4. 惰性实体抽取（fire-and-forget，仅真实 LLM 时；失败不影响会议）
        try:
            from app.config import settings

            if getattr(settings, "use_real_llm", False):
                task = asyncio.create_task(_extract_entities_for_meeting(mid, tid))
                _bg_tasks.add(task)
                task.add_done_callback(_bg_tasks.discard)
        except Exception:
            pass
    except Exception as e:
        logger.warning("物化会议知识图谱失败（已忽略，不阻塞会议）: %s", str(e)[:200])


async def get_materialized_graph(
    meeting_id: str | None, tenant_id: int | None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """读取物化边，构造成 graph 端点可用的 nodes/edges。

    返回 (nodes, edges)：包含 claim / evidence 节点及 supports/contradicts 边。
    """
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    seen_nodes: set[str] = set()

    def add_node(nid: str, ntype: str, label: str, size: int = 14) -> None:
        if nid in seen_nodes:
            return
        seen_nodes.add(nid)
        nodes.append(
            {
                "id": nid,
                "type": ntype,
                "label": (label[:80] + "...") if len(label) > 80 else label,
                "x": 0,
                "y": 0,
                "vx": 0,
                "vy": 0,
                "size": size,
                "meta": {},
            }
        )

    async with async_session_factory() as session:
        if meeting_id:
            res = await session.execute(
                text(
                    "SELECT source_type, source_id, target_type, target_id, "
                    "relation_type, weight, note FROM graph_edges WHERE meeting_id = :mid"
                ),
                {"mid": meeting_id},
            )
        else:
            if tenant_id is None:
                return nodes, edges
            res = await session.execute(
                text(
                    "SELECT source_type, source_id, target_type, target_id, "
                    "relation_type, weight, note FROM graph_edges "
                    "WHERE tenant_id = :tid ORDER BY created_at DESC LIMIT 500"
                ),
                {"tid": tenant_id},
            )
        for row in res.mappings().all():
            st, sid = row["source_type"], row["source_id"]
            tt, tid2 = row["target_type"], row["target_id"]
            rel = row["relation_type"]
            # 节点标签：claim 节点用尾部 hash 不可读，改为"主张"前缀；evidence 用"证据"
            if st == "claim":
                add_node(sid, "claim", f"主张 {sid[-6:]}", size=14)
            elif st == "evidence":
                add_node(sid, "evidence", f"证据 {sid[-6:]}", size=10)
            if tt == "claim":
                add_node(tid2, "claim", f"主张 {tid2[-6:]}", size=14)
            elif tt == "evidence":
                add_node(tid2, "evidence", f"证据 {tid2[-6:]}", size=10)
            edges.append(
                {
                    "id": f"{sid}->{tid2}:{rel}",
                    "source": sid,
                    "target": tid2,
                    "type": rel,
                    "weight": float(row["weight"] or 1.0),
                    "note": row["note"],
                }
            )
    return nodes, edges


async def get_related_meetings(meeting_id: str, tenant_id: int | None, top_k: int = 5) -> list[dict[str, Any]]:
    """该会议的相似历史会议（基于议题向量，排除自身）。"""
    async with async_session_factory() as session:
        row = (
            await session.execute(
                text("SELECT topic, clarified_topic FROM meetings WHERE id = :mid"),
                {"mid": meeting_id},
            )
        ).first()
    if not row:
        return []
    topic = (row[1] or row[0] or "").strip()
    if not topic:
        return []
    return await get_topic_index().search(topic, tenant_id, top_k=top_k, exclude_meeting_id=meeting_id)


# ─────────────────────────────────────────────────────────────────────────────
# 惰性实体抽取（LLM temp 0.0；仅真实 LLM 时运行）
# ─────────────────────────────────────────────────────────────────────────────


async def _extract_entities_for_meeting(meeting_id: str, tenant_id: int | None) -> None:
    """后台惰性抽取：对会议引用的文档逐 chunk 抽取实体/主张，落 entities + chunk_entities。"""
    try:
        from app.agents.llm import get_llm
        from app.rag.chunker import chunk_markdown

        # 取会议引用的文档原文
        async with async_session_factory() as session:
            rows = (
                (
                    await session.execute(
                        text(
                            """
                        SELECT d.id, d.raw_content, d.filename
                        FROM documents d
                        JOIN meeting_document_refs r ON r.document_id = d.id
                        WHERE r.meeting_id = :mid AND d.raw_content IS NOT NULL
                        LIMIT 5
                        """
                        ),
                        {"mid": meeting_id},
                    )
                )
                .mappings()
                .all()
            )

        llm = get_llm()
        entity_norm_cache: dict[str, str] = {}
        doc_entities: dict[str, set[str]] = {}

        for doc in rows:
            doc_id = doc["id"]
            raw = doc["raw_content"] or ""
            if not raw.strip():
                continue
            chunks = chunk_markdown(raw, doc_id)[:20]  # 单文档上限 20 chunk
            for ch in chunks:
                try:
                    parsed = await _extract_chunk_entities(llm, ch.text)
                except Exception:
                    parsed = None
                if not parsed:
                    continue
                chunk_ents = set()
                for ent in parsed.get("entities", [])[:8]:
                    name = (ent.get("name") or "").strip()
                    if not name:
                        continue
                    norm = name.lower()
                    entity_norm_cache.setdefault(norm, name)
                    chunk_ents.add(norm)
                # 落库（chunk_entities + entities 去重）
                await _persist_chunk_entities(
                    session_maker=async_session_factory,
                    meeting_id=meeting_id,
                    tenant_id=tenant_id,
                    doc_id=doc_id,
                    chunk_id=ch.chunk_id,
                    norms=list(chunk_ents),
                    names_map=entity_norm_cache,
                )
                doc_entities.setdefault(doc_id, set()).update(chunk_ents)

        # 跨文档共享实体 → document_relations（related）
        await _persist_doc_relations(async_session_factory, meeting_id, tenant_id, doc_entities)
        logger.info("惰性实体抽取完成（会议 %s，文档 %d）", meeting_id, len(rows))
    except Exception as e:
        logger.warning("惰性实体抽取失败（忽略）: %s", str(e)[:200])


async def _extract_chunk_entities(llm: Any, chunk_text: str) -> dict[str, Any] | None:
    """调用 LLM（temp 0.0）抽取实体。返回 {entities:[{name,type}]} 或 None。"""
    prompt = (
        "从以下文本中抽取关键业务实体（最多 8 个）。\n"
        '仅返回 JSON：{"entities": [{"name": "实体名", "type": "concept|person|org|tech|metric"}]}\n'
        "不要输出其他内容。\n\n文本：\n" + chunk_text[:1500]
    )
    try:
        out = await llm.complete_text(prompt, temperature=0.0)
        if not out:
            return None
        # 从文本中抠出 JSON 对象
        m = re.search(r"\{.*\}", out, re.DOTALL)
        if not m:
            return None
        entities: dict[str, Any] = json.loads(m.group(0))
        return entities
    except Exception:
        return None


async def _persist_chunk_entities(
    session_maker: Any,
    meeting_id: str,
    tenant_id: int | None,
    doc_id: str,
    chunk_id: str,
    norms: list[str],
    names_map: dict[str, str],
) -> None:
    async with session_maker() as session:
        for norm in norms:
            name = names_map.get(norm, norm)
            ent_id = "ent-" + hashlib.sha256(f"{tenant_id}:{norm}".encode()).hexdigest()[:16]
            await session.execute(
                text(
                    """
                    INSERT INTO entities (id, tenant_id, meeting_id, name, name_norm,
                                           entity_type, mention_count, created_at)
                    VALUES (:id, :tid, :mid, :name, :norm, 'concept', 1, NOW())
                    ON CONFLICT (tenant_id, name_norm) DO UPDATE SET mention_count = entities.mention_count + 1
                    """
                ),
                {"id": ent_id, "tid": tenant_id, "mid": meeting_id, "name": name, "norm": norm},
            )
            await session.execute(
                text(
                    """
                    INSERT INTO chunk_entities (tenant_id, meeting_id, doc_id, chunk_id, entity_id, salience)
                    VALUES (:tid, :mid, :doc, :chunk, :ent, 0.5)
                    ON CONFLICT (chunk_id, entity_id) DO NOTHING
                    """
                ),
                {"tid": tenant_id, "mid": meeting_id, "doc": doc_id, "chunk": chunk_id, "ent": ent_id},
            )
        await session.commit()


async def _persist_doc_relations(
    session_maker: Any,
    meeting_id: str,
    tenant_id: int | None,
    doc_entities: dict[str, set[str]],
) -> None:
    doc_ids = list(doc_entities.keys())
    for i in range(len(doc_ids)):
        for j in range(i + 1, len(doc_ids)):
            shared = doc_entities[doc_ids[i]] & doc_entities[doc_ids[j]]
            if shared:
                score = min(1.0, len(shared) / 5.0)
                async with session_maker() as session:
                    await session.execute(
                        text(
                            """
                            INSERT INTO document_relations
                                (tenant_id, src_doc_id, dst_doc_id, relation_type, score, created_by, created_at)
                            VALUES (:tid, :s, :d, 'related', :score, 'pipeline', NOW())
                            ON CONFLICT (src_doc_id, dst_doc_id, relation_type) DO NOTHING
                            """
                        ),
                        {
                            "tid": tenant_id,
                            "s": doc_ids[i],
                            "d": doc_ids[j],
                            "score": score,
                        },
                    )
                    await session.commit()
