# Evidence helpers: 证据检索 + 预检索辅助函数
# 从 nodes/evidence_check.py 提取到 orchestrator 层，消除 stage_runners 对 nodes/ 的反向依赖。
# nodes/evidence_check.py 保留 re-export 以向后兼容。
from __future__ import annotations

import asyncio

from app.models import MeetingState
from app.rag.retriever import retrieve_for_conflict
from app.tools import get_web_search


def _make_common_knowledge_evidence(conflict: dict) -> list[dict]:
    """无文档/网络证据时的降级：明确标注无证据，不制造伪引用。

    返回空 quote 占位，让 arbitrate 基于 side_a/side_b 论点本身质量裁决。
    strength=none 触发 prompts.py 的"无外部证据，低置信度裁决"路径。
    """
    return [
        {
            "evidence_id": "none-a",
            "quote": "",
            "source": "common_knowledge:none",
            "char_range": [0, 0],
            "strength": "none",
            "fact_check_status": "unverifiable",
        },
        {
            "evidence_id": "none-b",
            "quote": "",
            "source": "common_knowledge:none",
            "char_range": [0, 0],
            "strength": "none",
            "fact_check_status": "unverifiable",
        },
    ]


def _preliminary_fact_check_status(source: str) -> str:
    """M1.2: 根据来源类型预分配事实核查状态（LLM 可覆盖）。

    - doc:* → verified（用户上传文档视为可信事实）
    - web:* → unverifiable（网络来源需 LLM 根据 Signals Bag 判断）
    - common_knowledge:* → unverifiable
    - 其他 → unverifiable
    """
    if source.startswith("doc:"):
        return "verified"
    return "unverifiable"


async def _collect_evidence(meeting_id: str, conflict: dict) -> list[dict]:
    """为单个冲突检索证据（RAG + Web Search + 通用知识降级）

    统一检索流程：cross_team 预检索和 evidence_check 实时检索共用此函数（DRY）。
    M1.2: 每条证据附带初步 fact_check_status（LLM 可在评估时覆盖）。
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
            # M1.2: 预分配事实核查状态
            "fact_check_status": _preliminary_fact_check_status(ck.get("source", "doc:unknown")),
        }
        for i, ck in enumerate(chunks)
    ]
    if len(evidence_chunks) < 3:
        web_search = get_web_search()
        web_results = await web_search.search(summary, top_k=3, session_key=meeting_id)
        for i, wr in enumerate(web_results):
            wr_source = wr.get("source", "web:unknown")
            evidence_chunks.append(
                {
                    "evidence_id": f"web-{i}",
                    "quote": sanitize_untrusted_content(wr.get("quote", "")[:200]),
                    "source": wr_source,
                    "char_range": [0, 0],
                    "fact_check_status": _preliminary_fact_check_status(wr_source),
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
