# Evidence helpers: 证据检索 + 预检索辅助函数
# 从 nodes/evidence_check.py 提取到 orchestrator 层，消除 stage_runners 对 nodes/ 的反向依赖。
# nodes/evidence_check.py 保留 re-export 以向后兼容。
from __future__ import annotations

import asyncio

from app.models import MeetingState
from app.rag.retriever import retrieve_for_conflict
from app.tools import get_web_search


def _make_common_knowledge_evidence(conflict: dict) -> list[dict]:
    """无文档/网络证据时的降级：为每个冲突生成双方向通用工程原则证据。

    替代旧的单条中性占位符，让 evidence_check 仍有方向可判断：
    - ev-a：呼应 side_a 立场的通用原则
    - ev-b：呼应 side_b 立场的通用原则
    标记 strength=weak 和 source=common_knowledge，让 LLM 知道这是弱证据。
    """
    side_a = conflict.get("side_a", "")
    side_b = conflict.get("side_b", "")
    summary = conflict.get("summary", str(conflict))
    return [
        {
            "evidence_id": "ev-a",
            "quote": f"（通用工程实践 · 倾向 A 方）{side_a or summary}。此原则基于行业常识，非具体文档证据，需用户验证。",
            "source": "common_knowledge:side_a",
            "char_range": [0, 0],
            "strength": "weak",
        },
        {
            "evidence_id": "ev-b",
            "quote": f"（通用工程实践 · 倾向 B 方）{side_b or summary}。此原则基于行业常识，非具体文档证据，需用户验证。",
            "source": "common_knowledge:side_b",
            "char_range": [0, 0],
            "strength": "weak",
        },
    ]


async def _collect_evidence(meeting_id: str, conflict: dict) -> list[dict]:
    """为单个冲突检索证据（RAG + Web Search + 通用知识降级）

    统一检索流程：cross_team 预检索和 evidence_check 实时检索共用此函数（DRY）。
    """
    from app.orchestrator.prompt_safety import sanitize_rag_chunks, sanitize_untrusted_content

    summary = conflict.get("summary", str(conflict))
    chunks = await retrieve_for_conflict(meeting_id, summary, top_k=5)
    # M1.4: RAG 检索结果经过指令注入防护
    chunks = sanitize_rag_chunks(chunks)
    evidence_chunks = [
        {
            "evidence_id": f"ev-{i}",
            "quote": sanitize_untrusted_content(ck.get("text", "")[:200]),
            "source": ck.get("source", "doc:unknown"),
            "char_range": [ck.get("char_start", 0), ck.get("char_end", 0)],
            # 附带邻居上下文（让 LLM 看到证据所在段落的上下文）
            "context": sanitize_untrusted_content(ck.get("neighbor_context", "")),
        }
        for i, ck in enumerate(chunks)
    ]
    if len(evidence_chunks) < 3:
        web_search = get_web_search()
        web_results = await web_search.search(summary, top_k=3, session_key=meeting_id)
        for i, wr in enumerate(web_results):
            evidence_chunks.append(
                {
                    "evidence_id": f"web-{i}",
                    "quote": sanitize_untrusted_content(wr.get("quote", "")[:200]),
                    "source": wr.get("source", "web:unknown"),
                    "char_range": [0, 0],
                }
            )
    if not evidence_chunks:
        evidence_chunks = _make_common_knowledge_evidence(conflict)
    return evidence_chunks


async def _prefetch_evidence(state: MeetingState, conflicts: list[dict]) -> dict[str, list[dict]]:
    """预检索所有冲突的证据（流水线优化：与借调发言并行）

    返回 {conflict_id: [evidence_chunks]} 字典，evidence_check 节点优先使用。
    """

    async def _retrieve_one(conflict: dict) -> tuple[str, list[dict]]:
        cid = conflict.get("id", "c0")
        chunks = await _collect_evidence(state.meeting_id, conflict)
        return cid, chunks

    # 并行检索所有冲突
    results = await asyncio.gather(*[_retrieve_one(c) for c in conflicts])
    return {cid: chunks for cid, chunks in results}
