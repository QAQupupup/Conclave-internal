# Evidence helpers: 证据检索 + 预检索辅助函数
# 从 nodes/evidence_check.py 提取到 orchestrator 层，消除 stage_runners 对 nodes/ 的反向依赖。
# nodes/evidence_check.py 保留 re-export 以向后兼容。
from __future__ import annotations

import asyncio
import re

from app.models import MeetingState
from app.rag.retriever import retrieve_for_conflict
from app.tools import get_web_search

# Web 证据定界符（与 playwright_search.py 保持一致）
_EVIDENCE_BEGIN = "[EVIDENCE_DATA_BEGIN]"
_EVIDENCE_END = "[EVIDENCE_DATA_END]"


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


def _strength_from_tier(source_tier: str | None) -> str:
    """根据 web 来源 tier 推断证据强度。"""
    if not source_tier:
        return "medium"
    tier = source_tier.upper()
    if tier in ("S", "A"):
        return "strong"
    if tier == "B":
        return "medium"
    return "weak"


def _extract_quote_delimited(raw_quote: str) -> str:
    """从带定界符的 quote 中提取正文。

    Playwright 搜索用 [EVIDENCE_DATA_BEGIN]...[EVIDENCE_DATA_END] 包裹正文，
    以防御 prompt 注入。如果定界符完整则提取正文，否则原样返回（截断场景）。
    """
    if not raw_quote:
        return ""
    begin_pos = raw_quote.find(_EVIDENCE_BEGIN)
    end_pos = raw_quote.rfind(_EVIDENCE_END)
    if begin_pos >= 0 and end_pos > begin_pos:
        return raw_quote[begin_pos + len(_EVIDENCE_BEGIN) : end_pos]
    # 定界符被截断（如 [:200] 切断了闭合标记），清理残留的起始标记
    cleaned = raw_quote
    if begin_pos >= 0:
        cleaned = cleaned[begin_pos + len(_EVIDENCE_BEGIN) :]
    # 移除可能残留的闭合标记片段
    cleaned = re.sub(r"\[EVIDENCE_DATA_END\]?$", "", cleaned)
    return cleaned


async def _collect_evidence(meeting_id: str, conflict: dict) -> list[dict]:
    """为单个冲突检索证据（RAG + Web Search + 通用知识降级）

    统一检索流程：cross_team 预检索和 evidence_check 实时检索共用此函数（DRY）。
    M1.2: 每条证据附带初步 fact_check_status（LLM 可在评估时覆盖）。
    修复: Web 证据 signals/source_tier/strength 字段正确传递，quote 定界符安全处理。
    """
    from app.orchestrator.prompt_safety import sanitize_rag_chunks, sanitize_untrusted_content

    summary = conflict.get("summary", str(conflict))
    chunks = await retrieve_for_conflict(meeting_id, summary, top_k=5)
    # M1.4: RAG 检索结果经过指令注入防护
    chunks = sanitize_rag_chunks(chunks)
    evidence_chunks = [
        {
            "evidence_id": f"ev-{i}",
            "quote": sanitize_untrusted_content(ck.get("text", "")[:400]),
            "source": ck.get("source", "doc:unknown"),
            "char_range": [ck.get("char_start", 0), ck.get("char_end", 0)],
            # 附带邻居上下文（让 LLM 看到证据所在段落的上下文）
            "context": sanitize_untrusted_content(ck.get("neighbor_context", "")),
            # M1.2: 预分配事实核查状态
            "fact_check_status": _preliminary_fact_check_status(ck.get("source", "doc:unknown")),
            # 用户上传文档为强证据
            "strength": "strong" if ck.get("source", "").startswith("doc:") else "medium",
            # RAG 来源的 signals 袋（简化版）
            "signals": {
                "source_type": "document",
                "char_range": [ck.get("char_start", 0), ck.get("char_end", 0)],
            },
        }
        for i, ck in enumerate(chunks)
    ]
    if len(evidence_chunks) < 3:
        web_search = get_web_search()
        web_results = await web_search.search(summary, top_k=3, session_key=meeting_id)
        for i, wr in enumerate(web_results):
            wr_source = wr.get("source", "web:unknown")
            # 安全提取 quote：Playwright 返回的 quote 带定界符，先提取正文再清洗再截断
            raw_quote = wr.get("quote", "")
            quote_text = _extract_quote_delimited(raw_quote)
            quote_text = sanitize_untrusted_content(quote_text)[:400]
            # 传递 signals 袋和 source_tier
            signals = wr.get("signals", {})
            source_tier = wr.get("source_tier") or signals.get("effective_tier")
            evidence_chunks.append(
                {
                    "evidence_id": f"web-{i}",
                    "quote": quote_text,
                    "source": wr_source,
                    "url": wr.get("url", ""),
                    "char_range": [0, 0],
                    "fact_check_status": _preliminary_fact_check_status(wr_source),
                    "strength": _strength_from_tier(source_tier),
                    "source_tier": source_tier,
                    "signals": signals,
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
