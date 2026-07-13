# Shared helpers for pipeline stage nodes.
# 兼容层：纯算法实现已迁移到 conclave_core/，副作用函数保留在 app.orchestrator.stage_common。
from __future__ import annotations

from typing import Awaitable, Callable

from app.models import MeetingState
from app.orchestrator.stage_common import (
    emit_agent_spoke as _emit_agent_spoke,
    record_drift as _record_drift,
    record_message as _record_message,
    resolve_model_for_call as _resolve_model_for_call,
    run_with_consistency as _run_with_consistency,
)
from conclave_core.anchor import (
    get_charter_anchor as _anchor,
    get_full_anchor as _full_anchor,
)
from conclave_core.confidence import worst_confidence as _worst_confidence
from conclave_core.roles import _ROLE_KEYWORDS, match_role as _match_role
from conclave_core.text import (
    format_arbitrate_as_text as _format_arbitrate_as_text,
    format_claims_as_text as _format_claims_as_text,
)

# 节点签名：async def(state) -> state
Node = Callable[[MeetingState], Awaitable[MeetingState]]


__all__ = [
    "Node",
    "_match_role",
    "_ROLE_KEYWORDS",
    "_anchor",
    "_record_drift",
    "_record_message",
    "_emit_agent_spoke",
    "_format_claims_as_text",
    "_format_arbitrate_as_text",
    "_resolve_model_for_call",
    "_full_anchor",
    "_worst_confidence",
    "_run_with_consistency",
]
