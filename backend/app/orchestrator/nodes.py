# 六阶段节点：每个 async def run(state) -> state，纯函数风格，副作用通过事件总线外溢
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Awaitable

from app.agents.compute import (
    get_compute,
    build_clarify_prompt,
    build_intra_prompt,
    build_intra_react_prompt,
    build_cross_team_prompt,
    build_evidence_prompt,
    build_arbitrate_prompt,
    build_produce_prompt,
)
from app.agents.trace import set_current_trace
from app.events import bus, make_event
from app.models import MeetingState, MeetingStatus, Role, Stage
from app.orchestrator.charter import build_charter_from_clarify
from app.rag.retriever import retrieve_for_conflict
from app.tools.web_search import get_web_search

# 节点签名：async def(state) -> state
Node = Callable[[MeetingState], Awaitable[MeetingState]]

# ---- 角色模糊匹配（模块级，支持中英文角色名）----
# 真实 LLM 可能返回中文角色名（"产品经理"、"后端架构师"等），
# StubLLM 返回英文角色名，此处统一模糊匹配。
_ROLE_KEYWORDS: dict[str, list[str]] = {
    Role.PRODUCT_ARCHITECT.value: ["product", "architect", "产品", "架构", "pm", "产品经理", "产品架构"],
    Role.SECURITY_EXPERT.value: ["security", "安全", "风控", "sec"],
    Role.DATA_ENGINEER.value: ["data", "数据", "analytics", "分析"],
    Role.UX_DESIGNER.value: ["ux", "design", "设计", "体验", "ui"],
    Role.MARKETING_EXPERT.value: ["marketing", "市场", "营销", "brand", "growth"],
    Role.ENGINEER.value: ["engineer", "develop", "开发", "工程", "后端", "前端", "技术"],
    Role.MODERATOR.value: ["moderator", "host", "主持", "协调", "facilitator"],
}


def _match_role(role_str: str) -> Role | None:
    """模糊匹配角色名（支持中英文）

    匹配规则：角色字符串（小写）中包含任一关键词即匹配。
    返回匹配的 Role 枚举，未匹配返回 None。
    """
    role_lower = role_str.lower()
    for role, keywords in _ROLE_KEYWORDS.items():
        for kw in keywords:
            if kw in role_lower:
                return Role(role)
    return None


def _anchor(state: MeetingState) -> str:
    """取会议宪章锚点文本，charter 不存在时返回空串"""
    if state.charter is None:
        return ""
    return state.charter.to_prompt_anchor()


def _record_drift(state: MeetingState, role: Role | str, stage: Stage, content: str) -> None:
    """对发言做宪章漂移检查并记录到 drift_log（非阻塞）

    role 支持枚举角色与借调角色的字符串角色名。
    """
    if state.charter is None or not content:
        return
    result = state.charter.check_drift(content)
    role_value = role.value if isinstance(role, Role) else str(role)
    state.drift_log.append(
        {
            "role": role_value,
            "stage": stage.value,
            "is_drift": result.is_drift,
            "severity": result.severity,
            "reason": result.reason,
            "content_preview": content[:120],
        }
    )


def _record_message(
    state: MeetingState,
    role: Role,
    stage: Stage,
    content: str,
    claim_refs: list[str] | None = None,
    evidence_refs: list[str] | None = None,
) -> dict[str, Any]:
    """记录发言到 state.messages 并返回消息字典（供事件 payload 复用）"""
    msg = {
        "id": f"msg-{uuid.uuid4().hex[:8]}",
        "meeting_id": state.meeting_id,
        "agent_role": role.value,
        "stage": stage.value,
        "content": content,
        "claim_refs": claim_refs or [],
        "evidence_refs": evidence_refs or [],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    state.messages.append(msg)
    return msg


async def _emit_agent_spoke(state: MeetingState, role: Role, stage: Stage, content: str,
                            claim_refs: list[str] | None = None) -> None:
    """发布 agent.spoke 事件"""
    msg = _record_message(state, role, stage, content, claim_refs)
    await bus.publish(
        make_event(
            "agent.spoke",
            state.meeting_id,
            {
                "meeting_id": state.meeting_id,
                "role": role.value,
                "stage": stage.value,
                "content": content,
                "claim_refs": claim_refs or [],
                "message_id": msg["id"],
            },
        )
    )


# ---------- 改造三：借调 agent 发言 ----------

# 迭代二：借调角色 prompt 改为从动态角色库获取（替换原硬编码 BORROW_ROLE_PROMPTS）
from app.agents.role_templates import get_borrow_prompt


async def _let_borrowed_agents_speak(state: MeetingState, stage: Stage) -> None:
    """让待发言（spoken=False）的借调 agent 发言一次，然后标记 spoken=True

    借调的 agent 不立即加入 frozen scope，而是在下一个 intra_team / evidence_check
    节点执行时检查 borrowed_agents，对待发言的用对应角色模板发一次言。
    借调角色不在 Role 枚举中，直接构造消息并发布事件。
    """
    if not state.borrowed_agents:
        return
    topic = state.clarified_topic or state.topic
    for agent_info in state.borrowed_agents:
        if agent_info.get("spoken"):
            continue
        role_str = agent_info.get("role", "")
        prompt = get_borrow_prompt(role_str)
        content = (
            f"【借调发言 - {role_str}】\n"
            f"{prompt}\n"
            f"针对议题「{topic}」，我基于上述专业偏置补充意见："
            f"建议在决策中重点考虑本领域的关键风险与约束，避免遗漏。"
        )
        # 直接构造消息（借调角色不在 Role 枚举中，不走 _record_message）
        msg = {
            "id": f"msg-{uuid.uuid4().hex[:8]}",
            "meeting_id": state.meeting_id,
            "agent_role": role_str,
            "stage": stage.value,
            "content": content,
            "claim_refs": [],
            "evidence_refs": [],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        state.messages.append(msg)
        await bus.publish(
            make_event(
                "agent.spoke",
                state.meeting_id,
                {
                    "meeting_id": state.meeting_id,
                    "role": role_str,
                    "stage": stage.value,
                    "content": content,
                    "claim_refs": [],
                    "message_id": msg["id"],
                    "borrowed": True,
                },
            )
        )
        _record_drift(state, role_str, stage, content)
        agent_info["spoken"] = True


# ---------- 第3层：一致性自检 + 结论锁定辅助 ----------

# 置信度等级排序（值越大越差）
_CONFIDENCE_RANK: dict[str, int] = {"high": 0, "low": 1, "fallback": 2}


def _full_anchor(state: MeetingState, stage: str) -> str:
    """构造完整锚点：宪章锚点 + 已锁定结论上下文

    第3层：每个节点调 agent 前把 chain.get_locked_context(stage) 注入到 anchor 里
    （和 charter anchor 一起拼到 prompt 前）。
    """
    parts: list[str] = []
    charter_anchor = _anchor(state)
    if charter_anchor:
        parts.append(charter_anchor)
    locked_context = state.conclusion_chain.get_locked_context(stage)
    if locked_context:
        parts.append(locked_context)
    return "\n\n".join(parts) if parts else ""


def _worst_confidence(a: str, b: str) -> str:
    """返回两个置信度中较差的一个"""
    return a if _CONFIDENCE_RANK.get(a, 0) >= _CONFIDENCE_RANK.get(b, 0) else b


def _update_trace_consistency(state: MeetingState, start_pos: int, status: str) -> None:
    """更新 trace 中自 start_pos 以来所有记录的 consistency_status"""
    for call in state.llm_trace.calls[start_pos:]:
        call.consistency_status = status


async def _run_with_consistency(
    state: MeetingState,
    stage: str,
    call_fn: Callable[[str], Awaitable[dict[str, Any]]],
) -> tuple[dict[str, Any], str]:
    """带一致性自检的 LLM 调用

    流程：
    1. 用完整锚点（宪章 + 已锁定结论上下文）调 LLM
    2. 调 chain.check_consistency(result, stage) 检查一致性
    3. 如果不一致：把矛盾信息追加到 anchor 重调 LLM（最多 2 次重试）
    4. 重试后仍不一致：标记为 low_confidence，记录到 state 但不中断流程
    5. 如果一致：返回结果和置信度

    返回 (最终结果, confidence: "high" | "low" | "fallback")
    """
    chain = state.conclusion_chain
    base_anchor = _full_anchor(state, stage)

    # 记录 trace 起始位置（用于后续更新一致性状态）
    start_pos = len(state.llm_trace.calls)

    # 首次调用
    result = await call_fn(base_anchor)
    consistency = chain.check_consistency(result, stage)

    retries = 0
    while not consistency.is_consistent and retries < 2:
        retries += 1
        # 把矛盾信息追加到 anchor 重调
        contradiction = "；".join(consistency.violations)
        augmented_anchor = (
            f"{base_anchor}\n\n"
            f"【一致性警告】你的输出与已确认结论矛盾：{contradiction}。"
            f"请基于已确认结论重新输出，不得与之矛盾。"
        )
        result = await call_fn(augmented_anchor)
        consistency = chain.check_consistency(result, stage)

    # 确定置信度并更新 trace 一致性状态
    if not consistency.is_consistent:
        # 重试后仍不一致：标记 low_confidence，不中断流程
        _update_trace_consistency(state, start_pos, "low_confidence")
        confidence = "low"
    elif retries > 0:
        # 重试后通过
        _update_trace_consistency(state, start_pos, "inconsistent_retry")
        confidence = "low"
    else:
        # 首次即通过
        _update_trace_consistency(state, start_pos, "consistent")
        confidence = "high"

    # 检查是否有降级到 stub（仅 RealLLM 会记录 fallback_stub）
    if any(
        c.validation_status == "fallback_stub"
        for c in state.llm_trace.calls[start_pos:]
    ):
        confidence = "fallback"

    return result, confidence


async def clarify_node(state: MeetingState) -> MeetingState:
    """Clarify 阶段：主持人澄清议题，确认团队组成，构造会议宪章"""
    # 设置 trace 上下文（RealLLM 会记录调用，stub 静默跳过）
    set_current_trace(state.llm_trace)
    compute = get_compute()

    # 带一致性自检的 LLM 调用：构造 ThinkRequest 并经 compute 接口执行
    async def call_fn(anchor: str) -> dict[str, Any]:
        req = build_clarify_prompt(state.topic, state.doc_summaries, anchor=anchor)
        resp = await compute.think(req)
        return resp.result

    result, confidence = await _run_with_consistency(state, "clarify", call_fn)

    state.clarified_topic = result.get("clarified_topic", state.topic)
    state.key_questions = result.get("key_questions", [])
    state.team_config = result.get("team_config", [])
    # 构造会议宪章（不可变锚点），注入后续所有阶段防漂移
    state.charter = build_charter_from_clarify(
        meeting_id=state.meeting_id,
        original_topic=state.topic,
        clarified_topic=state.clarified_topic,
        key_questions=state.key_questions,
    )
    # 第2层：锁定 clarify 结论
    state.conclusion_chain.lock("clarify", result)
    # 第5层：记录置信度
    state.confidence_flags["clarify"] = confidence
    # 主持人发言
    summary = (
        f"议题已澄清：{state.clarified_topic}。"
        f"关键问题 {len(state.key_questions)} 个，团队 {len(state.team_config)} 人。"
    )
    await _emit_agent_spoke(state, Role.MODERATOR, Stage.CLARIFY, summary)
    _record_drift(state, Role.MODERATOR, Stage.CLARIFY, summary)
    state.stage = Stage.INTRA_TEAM
    return state


async def intra_team_node(state: MeetingState) -> MeetingState:
    """IntraTeam 阶段：混合模式思考（前 N-1 并行 + 最后 1 反应）

    优化策略：
    - 前 N-1 个角色并行独立思考（互不可见，速度快）
    - 最后 1 个角色等前面完成后，基于全部前序结论做反应性思考（看到其他人观点）
    - 兼顾速度和辩论质量：O(max(T1..Tn-1) + Tn) 而非 O(T1+T2+...+Tn)
    - 只有 1 个角色时退化为纯并行（无反应环节）

    副作用（claims/事件/漂移）串行执行，保持顺序与 team_config 一致。
    """
    # 设置 trace 上下文
    set_current_trace(state.llm_trace)
    compute = get_compute()
    if not state.team_config:
        # 兜底：默认两角色
        state.team_config = [
            {"role": "product_architect", "stance": "重价值与边界"},
            {"role": "engineer", "stance": "重可行性与风险"},
        ]
    # 解析 team_config 为 (role, stance) 列表，保持顺序
    # 支持模糊匹配：LLM 可能返回中文角色名（"产品经理"、"后端架构师"等）
    # _ROLE_KEYWORDS 和 _match_role 已提升为模块级函数

    members: list[tuple[Role, str]] = []
    for member in state.team_config:
        role_str = member.get("role", "")
        stance = member.get("stance", "")
        matched = _match_role(role_str)
        if matched is not None:
            members.append((matched, stance))
        # 未匹配的角色跳过（当前支持 7 种角色，其他角色可作为借调处理）

    # 兜底：如果模糊匹配后没有有效角色，使用默认配置
    if not members:
        members = [(Role.PRODUCT_ARCHITECT, "重价值与边界"), (Role.ENGINEER, "重可行性与风险")]

    # ---- Phase 1：前 N-1 个角色并行独立思考 ----
    parallel_members = members[:-1] if len(members) > 1 else members
    last_member = members[-1] if len(members) > 1 else None

    async def _think_one(role: Role, stance: str) -> tuple[dict[str, Any], str]:
        async def call_fn(anchor: str) -> dict[str, Any]:
            req = build_intra_prompt(role, state.clarified_topic or state.topic, stance, anchor=anchor)
            resp = await compute.think(req)
            return resp.result
        return await _run_with_consistency(state, "intra_team", call_fn)

    # 并行思考前 N-1 个角色
    parallel_results = await asyncio.gather(
        *[_think_one(r, s) for r, s in parallel_members]
    )

    # ---- 串行收集前 N-1 个角色的结论（构造 prior_conclusions 供反应角色使用）----
    conclusions: list[dict[str, Any]] = []
    worst_confidence = "high"
    prior_conclusions_for_react: list[dict[str, Any]] = []

    for (role, stance), (result, confidence) in zip(parallel_members, parallel_results):
        worst_confidence = _worst_confidence(worst_confidence, confidence)
        claims = result.get("claims", [])
        claim_ids = []
        for c in claims:
            cid = f"claim-{uuid.uuid4().hex[:8]}"
            c["id"] = cid
            c["agent_role"] = role.value
            state.claims.append(c)
            claim_ids.append(cid)
        conclusion = {"role": role.value, "stance": stance, "claims": claims}
        conclusions.append(conclusion)
        prior_conclusions_for_react.append(conclusion)
        content = json.dumps(claims, ensure_ascii=False)
        await _emit_agent_spoke(state, role, Stage.INTRA_TEAM, content, claim_refs=claim_ids)
        _record_drift(state, role, Stage.INTRA_TEAM, content)

    # ---- Phase 2：最后 1 个角色基于前序结论做反应性思考 ----
    if last_member is not None:
        last_role, last_stance = last_member
        async def _think_react(role: Role, stance: str, prior: list[dict]) -> tuple[dict[str, Any], str]:
            async def call_fn(anchor: str) -> dict[str, Any]:
                req = build_intra_react_prompt(
                    role, state.clarified_topic or state.topic, stance, prior, anchor=anchor
                )
                resp = await compute.think(req)
                return resp.result
            return await _run_with_consistency(state, "intra_team", call_fn)

        react_result, react_confidence = await _think_react(last_role, last_stance, prior_conclusions_for_react)
        worst_confidence = _worst_confidence(worst_confidence, react_confidence)
        # 收集反应角色的结论
        react_claims = react_result.get("claims", [])
        react_claim_ids = []
        for c in react_claims:
            cid = f"claim-{uuid.uuid4().hex[:8]}"
            c["id"] = cid
            c["agent_role"] = last_role.value
            state.claims.append(c)
            react_claim_ids.append(cid)
        conclusion = {"role": last_role.value, "stance": last_stance, "claims": react_claims}
        conclusions.append(conclusion)
        content = json.dumps(react_claims, ensure_ascii=False)
        await _emit_agent_spoke(state, last_role, Stage.INTRA_TEAM, content, claim_refs=react_claim_ids)
        _record_drift(state, last_role, Stage.INTRA_TEAM, content)

    state.team_conclusions = conclusions
    # 第2层：锁定 intra_team 结论
    state.conclusion_chain.lock("intra_team", {"claims": state.claims, "team_conclusions": conclusions})
    # 第5层：记录置信度（取最差值）
    state.confidence_flags["intra_team"] = worst_confidence
    # 改造三：让待发言的借调 agent 在队内讨论末尾发言一次
    await _let_borrowed_agents_speak(state, Stage.INTRA_TEAM)
    state.stage = Stage.CROSS_TEAM
    return state


async def cross_team_node(state: MeetingState) -> MeetingState:
    """CrossTeam 阶段：跨队辩论，暴露冲突点

    流水线优化：冲突产生后，后台预启动 evidence_check 的 RAG 检索，
    与后续的借调发言 + 阶段切换事件并行，减少 evidence_check 等待时间。
    """
    # 设置 trace 上下文
    set_current_trace(state.llm_trace)
    compute = get_compute()
    # 带一致性自检的 LLM 调用
    async def call_fn(anchor: str) -> dict[str, Any]:
        req = build_cross_team_prompt(state.team_conclusions, anchor=anchor)
        resp = await compute.think(req)
        return resp.result

    result, confidence = await _run_with_consistency(state, "cross_team", call_fn)
    conflicts = result.get("conflicts", [])
    # 规范化冲突类型
    for c in conflicts:
        if "conflict_type" not in c and "type" in c:
            c["conflict_type"] = c.pop("type")
    state.conflicts = conflicts
    # 第2层：锁定 cross_team 结论
    state.conclusion_chain.lock("cross_team", {"conflicts": conflicts})
    # 第5层：记录置信度
    state.confidence_flags["cross_team"] = confidence
    content = json.dumps(conflicts, ensure_ascii=False)
    await _emit_agent_spoke(state, Role.MODERATOR, Stage.CROSS_TEAM, content)
    _record_drift(state, Role.MODERATOR, Stage.CROSS_TEAM, content)

    # ---- 流水线优化：后台预检索 evidence（与借调发言并行）----
    # 冲突已确定，RAG 检索是 I/O 密集型，可以提前启动
    # 检索结果存入 state._prefetched_evidence，evidence_check 节点优先使用
    if conflicts:
        state._prefetched_evidence = await _prefetch_evidence(state, conflicts)

    state.stage = Stage.EVIDENCE_CHECK
    return state


async def _prefetch_evidence(state: MeetingState, conflicts: list[dict]) -> dict[str, list[dict]]:
    """预检索所有冲突的证据（流水线优化：与借调发言并行）

    返回 {conflict_id: [evidence_chunks]} 字典，evidence_check 节点优先使用。
    """
    async def _retrieve_one(conflict: dict) -> tuple[str, list[dict]]:
        cid = conflict.get("id", "c0")
        summary = conflict.get("summary", str(conflict))
        chunks = retrieve_for_conflict(state.meeting_id, summary, top_k=5)
        evidence_chunks = [
            {
                "evidence_id": f"ev-{i}",
                "quote": ck.get("text", "")[:200],
                "source": ck.get("source", "doc:unknown"),
                "char_range": [ck.get("char_start", 0), ck.get("char_end", 0)],
            }
            for i, ck in enumerate(chunks)
        ]
        if len(evidence_chunks) < 3:
            web_search = get_web_search()
            web_results = await web_search.search(summary, top_k=3)
            for i, wr in enumerate(web_results):
                evidence_chunks.append({
                    "evidence_id": f"web-{i}",
                    "quote": wr.get("quote", "")[:200],
                    "source": wr.get("source", "web:unknown"),
                    "char_range": [0, 0],
                })
        if not evidence_chunks:
            evidence_chunks = [
                {
                    "evidence_id": "ev-0",
                    "quote": "（无上传文档证据，以下结论基于通用工程实践，需用户验证）",
                    "source": "common_knowledge:none",
                    "char_range": [0, 0],
                }
            ]
        return cid, evidence_chunks

    # 并行检索所有冲突
    results = await asyncio.gather(*[_retrieve_one(c) for c in conflicts])
    return {cid: chunks for cid, chunks in results}


async def evidence_check_node(state: MeetingState) -> MeetingState:
    """EvidenceCheck 阶段：并行 RAG 检索证据 + 并行对照判断

    优化：逐冲突串行 → 全部并行（asyncio.gather）
    - 每个冲突独立做 RAG 检索 + Web Search + LLM 思考
    - think_batch 并行执行，保序返回
    - 副作用（事件发布）串行收集
    """
    # 设置 trace 上下文
    set_current_trace(state.llm_trace)
    compute = get_compute()
    worst_confidence = "high"

    # ---- Phase 1：使用预检索结果或并行检索（流水线优化）----
    # cross_team 阶段已预检索的证据存在 state._prefetched_evidence
    prefetched = getattr(state, "_prefetched_evidence", None)

    if prefetched:
        # 使用预检索结果（已由 cross_team 阶段提前完成）
        retrieval_results = [
            (conflict, prefetched.get(conflict.get("id", "c0"), []))
            for conflict in state.conflicts
        ]
    else:
        # 无预检索时，并行检索（兼容旧路径）
        async def _retrieve_evidence(conflict: dict) -> tuple[dict, list[dict]]:
            """为单个冲突检索证据（RAG + Web Search）"""
            cid = conflict.get("id", "c0")
            summary = conflict.get("summary", str(conflict))
            chunks = retrieve_for_conflict(state.meeting_id, summary, top_k=5)
            evidence_chunks = [
                {
                    "evidence_id": f"ev-{i}",
                    "quote": ck.get("text", "")[:200],
                    "source": ck.get("source", "doc:unknown"),
                    "char_range": [ck.get("char_start", 0), ck.get("char_end", 0)],
                }
                for i, ck in enumerate(chunks)
            ]
            if len(evidence_chunks) < 3:
                web_search = get_web_search()
                web_results = await web_search.search(summary, top_k=3)
                for i, wr in enumerate(web_results):
                    evidence_chunks.append({
                        "evidence_id": f"web-{i}",
                        "quote": wr.get("quote", "")[:200],
                        "source": wr.get("source", "web:unknown"),
                        "char_range": [0, 0],
                    })
            if not evidence_chunks:
                evidence_chunks = [
                    {
                        "evidence_id": "ev-0",
                        "quote": "（无上传文档证据，以下结论基于通用工程实践，需用户验证）",
                        "source": "common_knowledge:none",
                        "char_range": [0, 0],
                    }
                ]
            return conflict, evidence_chunks

        retrieval_results = await asyncio.gather(
            *[_retrieve_evidence(c) for c in state.conflicts]
        )

    # ---- Phase 2：并行 LLM 思考（每个冲突独立思考，互不阻塞）----
    async def _think_one_conflict(
        conflict: dict, evidence_chunks: list[dict]
    ) -> tuple[dict[str, Any], str, dict, list[dict]]:
        """对单个冲突做带一致性自检的 LLM 调用"""
        async def call_fn(anchor: str, _conflict=conflict, _chunks=evidence_chunks) -> dict[str, Any]:
            req = build_evidence_prompt(_conflict, _chunks, anchor=anchor)
            resp = await compute.think(req)
            return resp.result

        result, confidence = await _run_with_consistency(state, "evidence_check", call_fn)
        return result, confidence, conflict, evidence_chunks

    # 并行思考所有冲突
    think_results = await asyncio.gather(
        *[_think_one_conflict(c, chunks) for c, chunks in retrieval_results]
    )

    # ---- Phase 3：串行收集结果 + 发布事件 ----
    evidence_set: list[dict[str, Any]] = []
    for result, confidence, conflict, evidence_chunks in think_results:
        cid = conflict.get("id", "c0")
        worst_confidence = _worst_confidence(worst_confidence, confidence)
        assessments = result.get("evidence_assessments", [])
        es = {
            "conflict_id": result.get("conflict_id", cid),
            "assessments": assessments,
        }
        evidence_set.append(es)
        # 发布 evidence.attached 事件（逐条证据）
        for a in assessments:
            await bus.publish(
                make_event(
                    "evidence.attached",
                    state.meeting_id,
                    {
                        "meeting_id": state.meeting_id,
                        "conflict_id": es["conflict_id"],
                        "quote": a.get("quote", ""),
                        "source": a.get("source", ""),
                        "supports": a.get("supports", "neutral"),
                    },
                )
            )
    state.evidence_set = evidence_set
    # 第2层：锁定 evidence_check 结论
    state.conclusion_chain.lock("evidence_check", {"evidence_set": evidence_set})
    # 第5层：记录置信度（取最差值）
    state.confidence_flags["evidence_check"] = worst_confidence
    # 改造三：让待发言的借调 agent 在证据对照阶段也发言一次（兜底）
    await _let_borrowed_agents_speak(state, Stage.EVIDENCE_CHECK)
    state.stage = Stage.ARBITRATE
    return state


async def arbitrate_node(state: MeetingState) -> MeetingState:
    """Arbitrate 阶段：仲裁者裁决，形成结论"""
    # 设置 trace 上下文
    set_current_trace(state.llm_trace)
    compute = get_compute()
    # 带一致性自检的 LLM 调用
    async def call_fn(anchor: str) -> dict[str, Any]:
        req = build_arbitrate_prompt(state.evidence_set, anchor=anchor)
        resp = await compute.think(req)
        return resp.result

    result, confidence = await _run_with_consistency(state, "arbitrate", call_fn)
    state.decision_record = {
        "decisions": result.get("decisions", []),
        "adopted_claims": result.get("adopted_claims", []),
    }
    # 第2层：锁定 arbitrate 结论
    state.conclusion_chain.lock("arbitrate", state.decision_record)
    # 第5层：记录置信度
    state.confidence_flags["arbitrate"] = confidence
    content = json.dumps(state.decision_record, ensure_ascii=False)
    await _emit_agent_spoke(state, Role.MODERATOR, Stage.ARBITRATE, content)
    _record_drift(state, Role.MODERATOR, Stage.ARBITRATE, content)
    state.stage = Stage.PRODUCE
    return state


async def produce_node(state: MeetingState) -> MeetingState:
    """Produce 阶段：生成结构化 PRD 与 OpenAPI 片段"""
    # 设置 trace 上下文
    set_current_trace(state.llm_trace)
    compute = get_compute()
    # 带一致性自检的 LLM 调用
    async def call_fn(anchor: str) -> dict[str, Any]:
        req = build_produce_prompt(state.decision_record or {}, anchor=anchor)
        resp = await compute.think(req)
        return resp.result

    result, confidence = await _run_with_consistency(state, "produce", call_fn)
    from app.observability.log_bus import log_bus as _lb
    _lb.info("produce: LLM 调用+一致性检查完成", logger="orchestrator.nodes.produce",
             extra={"confidence": confidence, "has_prd": bool(result.get("prd")), "openapi_len": len(result.get("openapi", ""))})
    prd = result.get("prd", {})
    openapi = result.get("openapi", "")
    state.artifact = {
        "meeting_id": state.meeting_id,
        "prd": prd,
        "openapi": openapi,
    }
    # 第2层：锁定 produce 结论
    state.conclusion_chain.lock("produce", state.artifact)
    # 第5层：记录置信度
    state.confidence_flags["produce"] = confidence
    _lb.info("produce: artifact 已构造, 锁定结论完成", logger="orchestrator.nodes.produce",
             extra={"prd_title": prd.get("title", "?"), "openapi_len": len(openapi)})
    # 发布 artifact.generated 事件
    await bus.publish(
        make_event(
            "artifact.generated",
            state.meeting_id,
            {
                "meeting_id": state.meeting_id,
                "prd": prd,
                "openapi": openapi,
            },
        )
    )
    _lb.info("produce: artifact.generated 事件已发布", logger="orchestrator.nodes.produce")
    # 产物阶段也做一次漂移检查（针对 PRD 文本）
    prd_text = json.dumps(prd, ensure_ascii=False)
    _record_drift(state, Role.MODERATOR, Stage.PRODUCE, prd_text)
    _lb.info("produce: 漂移检查完成", logger="orchestrator.nodes.produce")
    # 终态
    state.stage = Stage.PRODUCE
    state.status = MeetingStatus.DONE
    _lb.info("produce: 状态已设为 DONE", logger="orchestrator.nodes.produce")
    # 迭代二：会议结束后触发记忆提取（失败不影响主流程）
    from app.memory.profile import trigger_extraction
    trigger_extraction(state)
    _lb.info("produce: 记忆提取完成, 准备返回", logger="orchestrator.nodes.produce")
    return state


# 节点注册表：阶段 -> 节点函数
NODES: dict[Stage, Node] = {
    Stage.CLARIFY: clarify_node,
    Stage.INTRA_TEAM: intra_team_node,
    Stage.CROSS_TEAM: cross_team_node,
    Stage.EVIDENCE_CHECK: evidence_check_node,
    Stage.ARBITRATE: arbitrate_node,
    Stage.PRODUCE: produce_node,
}
