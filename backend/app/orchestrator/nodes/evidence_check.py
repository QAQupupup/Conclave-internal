# Evidence check stage node + evidence retrieval helpers
from __future__ import annotations

import asyncio
from typing import Any

from app.agents.compute import get_compute, build_evidence_prompt
from app.agents.trace import set_current_trace
from app.models import MeetingState, Role
from app.rag.retriever import retrieve_for_conflict
from app.tools import get_web_search

from ._helpers import (
    _full_anchor,
    _run_with_consistency,
    _resolve_model_for_call,
)


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
    summary = conflict.get("summary", str(conflict))
    chunks = await retrieve_for_conflict(meeting_id, summary, top_k=5)
    evidence_chunks = [
        {
            "evidence_id": f"ev-{i}",
            "quote": ck.get("text", "")[:200],
            "source": ck.get("source", "doc:unknown"),
            "char_range": [ck.get("char_start", 0), ck.get("char_end", 0)],
            # 附带邻居上下文（让 LLM 看到证据所在段落的上下文）
            "context": ck.get("neighbor_context", ""),
        }
        for i, ck in enumerate(chunks)
    ]
    if len(evidence_chunks) < 3:
        web_search = get_web_search()
        web_results = await web_search.search(summary, top_k=3, session_key=meeting_id)
        for i, wr in enumerate(web_results):
            evidence_chunks.append({
                "evidence_id": f"web-{i}",
                "quote": wr.get("quote", "")[:200],
                "source": wr.get("source", "web:unknown"),
                "char_range": [0, 0],
            })
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


async def evidence_check_node(state: MeetingState) -> MeetingState:
    """EvidenceCheck 阶段：并行 RAG 检索证据 + 并行对照判断

    优化：逐冲突串行 → 全部并行（asyncio.gather）
    - 每个冲突独立做 RAG 检索 + Web Search + LLM 思考
    - 支持 ReactLoop 多轮工具调用（如果工具注册表可用）
    - 副作用（事件发布）串行收集
    """
    # 设置 trace 上下文
    set_current_trace(state.llm_trace)
    compute = get_compute()

    # ---- Phase 0：准备工具注册表（如果可用）----
    tool_registry = None
    try:
        from app.orchestrator.react_loop import ReactLoop, create_default_tool_registry
        tool_registry = create_default_tool_registry()
    except Exception:
        pass  # 工具注册失败时降级为无工具模式

    # ---- Phase 1：使用预检索结果或并行检索（流水线优化）----
    # cross_team 阶段已预检索的证据存在 state.prefetched_evidence
    # [UNIQ-07 修复] 旧版 _prefetched_evidence 字段名（下划线前缀）pydantic 不序列化，
    # 进程崩溃重启后丢失；改为 prefetched_evidence（无下划线）后持久化生效。
    # 兼容旧快照：getattr + None fallback
    prefetched = getattr(state, "prefetched_evidence", None) or getattr(
        state, "_prefetched_evidence", None
    )

    if prefetched:
        # 使用预检索结果（已由 cross_team 阶段提前完成）
        retrieval_results = [
            (conflict, prefetched.get(conflict.get("id", "c0"), []))
            for conflict in state.conflicts
        ]
    else:
        # 无预检索时，并行检索（兼容旧路径）
        async def _retrieve_evidence(conflict: dict) -> tuple[dict, list[dict]]:
            """为单个冲突检索证据（委托 _collect_evidence 统一流程）"""
            chunks = await _collect_evidence(state.meeting_id, conflict)
            return conflict, chunks

        retrieval_results = await asyncio.gather(
            *[_retrieve_evidence(c) for c in state.conflicts]
        )

    # ---- Phase 2：并行 LLM 思考（每个冲突独立思考，支持 ReactLoop）----
    async def _think_one_conflict(
        conflict: dict, evidence_chunks: list[dict]
    ) -> tuple[dict[str, Any], str, dict, list[dict]]:
        """对单个冲突做带一致性自检的 LLM 调用（支持 ReactLoop 多轮）"""
        # 如果工具注册表可用，使用 ReactLoop 多轮模式
        if tool_registry is not None:
            try:
                react = ReactLoop(
                    compute=compute,
                    tools=tool_registry,
                    meeting_id=state.meeting_id,
                )
                # 构建初始 prompt（含工具描述）
                anchor = _full_anchor(state, "evidence_check")
                req = build_evidence_prompt(conflict, evidence_chunks, anchor=anchor,
                                            available_tools=tool_registry.get_available_tools())
                req.model = _resolve_model_for_call(state, Role.MODERATOR.value, "evidence_check")
                # ReactLoop 多轮执行（默认 10 轮，可通过 REACT_MAX_ITERATIONS 环境变量配置）
                resp = await react.run(req)
                result = resp.result
                confidence = resp.confidence if hasattr(resp, 'confidence') else "high"
                return result, confidence, conflict, evidence_chunks
            except Exception:
                # ReactLoop 失败时降级到单次调用
                pass

        # 降级：单次 LLM 调用（无工具）
        async def call_fn(anchor: str, _conflict=conflict, _chunks=evidence_chunks) -> dict[str, Any]:
            req = build_evidence_prompt(_conflict, _chunks, anchor=anchor)
            req.model = _resolve_model_for_call(state, Role.MODERATOR.value, "evidence_check")
            resp = await compute.think(req)
            return resp.result

        result, confidence = await _run_with_consistency(state, "evidence_check", call_fn)
        return result, confidence, conflict, evidence_chunks

    # 并行思考所有冲突
    think_results = await asyncio.gather(
        *[_think_one_conflict(c, chunks) for c, chunks in retrieval_results]
    )

    # ---- Phase 3：串行收集结果 + 发布事件 ----
    conflict_results: list[dict[str, Any]] = [
        {
            "conflict": conflict,
            "evidence_chunks": evidence_chunks,
            "result": result,
            "confidence": confidence,
        }
        for result, confidence, conflict, evidence_chunks in think_results
    ]

    from app.orchestrator.stage_runners import run_evidence_check
    return await run_evidence_check(state, conflict_results)
