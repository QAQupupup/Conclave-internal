# Evidence check stage node
# 证据检索辅助函数已迁移到 orchestrator/evidence_helpers.py，消除 stage_runners 反向依赖。
from __future__ import annotations

import asyncio
from typing import Any

from app.agents.compute import execute_think, build_evidence_prompt
from app.agents.trace import set_current_trace
from app.models import MeetingState, Role

from ._helpers import (
    _full_anchor,
    _run_with_consistency,
    _resolve_model_for_call,
)

# 从 orchestrator 层导入证据检索辅助函数（向后兼容）
from app.orchestrator.evidence_helpers import (
    _make_common_knowledge_evidence,
    _collect_evidence,
    _prefetch_evidence,
)


async def evidence_check_node(state: MeetingState) -> MeetingState:
    """EvidenceCheck 阶段：并行 RAG 检索证据 + 并行对照判断

    优化：逐冲突串行 → 全部并行（asyncio.gather）
    - 每个冲突独立做 RAG 检索 + Web Search + LLM 思考
    - 支持 ReactLoop 多轮工具调用（如果工具注册表可用）
    - 副作用（事件发布）串行收集
    """
    # 设置 trace 上下文
    set_current_trace(state.llm_trace)

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
            resp = await execute_think(req)
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
