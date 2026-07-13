# 阶段共享辅助函数（保留依赖 app.events / app.models 运行时代码的副作用函数）
# 纯算法/无副作用函数已迁移到 conclave_core/ 包。
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from app.events import bus, make_event
from app.models import MeetingState, Role, Stage

from conclave_core.anchor import get_charter_anchor, get_full_anchor
from conclave_core.charter_logic import check_drift
from conclave_core.conclusion_logic import check_consistency
from conclave_core.confidence import worst_confidence
from conclave_core.roles import _ROLE_KEYWORDS, match_role
from conclave_core.text import (
    compress_decisions_to_brief,
    format_arbitrate_as_text,
    format_claims_as_text,
)

# 向后兼容：继续导出部分旧符号（这些函数的实现现位于 conclave_core）
__all__ = [
    "emit_agent_spoke",
    "record_drift",
    "record_message",
    "run_with_consistency",
    "resolve_model_for_call",
    "get_charter_anchor",
    "get_full_anchor",
    "worst_confidence",
    "match_role",
    "_ROLE_KEYWORDS",
    "format_claims_as_text",
    "format_arbitrate_as_text",
    "compress_decisions_to_brief",
]


# ---- 消息与事件 ----

def record_message(
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


async def emit_agent_spoke(
    state: MeetingState,
    role: Role,
    stage: Stage,
    content: str,
    claim_refs: list[str] | None = None,
    borrowed: bool = False,
) -> dict[str, Any]:
    """发布 agent.spoke 事件并记录消息"""
    msg = record_message(state, role, stage, content, claim_refs)
    payload = {
        "meeting_id": state.meeting_id,
        "role": role.value,
        "stage": stage.value,
        "content": content,
        "claim_refs": claim_refs or [],
        "message_id": msg["id"],
    }
    if borrowed:
        payload["borrowed"] = True
    await bus.publish(make_event("agent.spoke", state.meeting_id, payload))
    return msg


# ---- 漂移检查 ----

def record_drift(state: MeetingState, role: Role | str, stage: Stage, content: str) -> None:
    """对发言做宪章漂移检查并记录到 drift_log（非阻塞）"""
    if state.charter is None or not content:
        return
    result = check_drift(state.charter, content)
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


# ---- 模型解析 ----

def resolve_model_for_call(state: MeetingState, role: str = "", stage: str = "") -> str:
    """从 resolved_models 快照解析当前 LLM 调用应使用的模型"""
    from app.llm_providers import resolve_model_from_snapshot
    return resolve_model_from_snapshot(state.resolved_models, agent_role=role, stage=stage)


# ---- 一致性自检 ----

def _update_trace_consistency(state: MeetingState, start_pos: int, status: str) -> None:
    """更新 trace 中自 start_pos 以来所有记录的 consistency_status"""
    for call in state.llm_trace.calls[start_pos:]:
        call.consistency_status = status


async def run_with_consistency(
    state: MeetingState,
    stage: str,
    call_fn: Callable[[str], Awaitable[dict[str, Any]]],
) -> tuple[dict[str, Any], str]:
    """带一致性自检的 LLM 调用

    返回 (最终结果, confidence: "high" | "low" | "fallback")
    """
    chain = state.conclusion_chain
    base_anchor = get_full_anchor(state, stage)
    start_pos = len(state.llm_trace.calls)

    result = await call_fn(base_anchor)
    consistency = check_consistency(chain, result, stage)

    retries = 0
    while not consistency.is_consistent and retries < 2:
        retries += 1
        contradiction = "；".join(consistency.violations)
        augmented_anchor = (
            f"{base_anchor}\n\n"
            f"【一致性警告】你的输出与已确认结论矛盾：{contradiction}。"
            f"请基于已确认结论重新输出，不得与之矛盾。"
        )
        result = await call_fn(augmented_anchor)
        consistency = check_consistency(chain, result, stage)

    if not consistency.is_consistent:
        _update_trace_consistency(state, start_pos, "low_confidence")
        confidence = "low"
    elif retries > 0:
        _update_trace_consistency(state, start_pos, "inconsistent_retry")
        confidence = "low"
    else:
        _update_trace_consistency(state, start_pos, "consistent")
        confidence = "high"

    if any(c.validation_status == "fallback_stub" for c in state.llm_trace.calls[start_pos:]):
        confidence = "fallback"

    return result, confidence
