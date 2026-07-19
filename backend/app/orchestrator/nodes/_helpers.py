# Shared helpers for pipeline stage nodes.
# 兼容层：纯算法实现已迁移到 conclave_core/，副作用函数保留在 app.orchestrator.stage_common。
from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.models import MeetingState
from app.orchestrator.stage_common import (
    emit_agent_spoke as _emit_agent_spoke,
)
from app.orchestrator.stage_common import (
    record_drift as _record_drift,
)
from app.orchestrator.stage_common import (
    record_message as _record_message,
)
from app.orchestrator.stage_common import (
    resolve_model_for_call as _resolve_model_for_call,
)
from app.orchestrator.stage_common import (
    run_with_consistency as _run_with_consistency,
)
from conclave_core.anchor import (
    get_charter_anchor as _anchor,
)
from conclave_core.anchor import (
    get_full_anchor as _full_anchor,
)
from conclave_core.confidence import worst_confidence as _worst_confidence
from conclave_core.roles import _ROLE_KEYWORDS
from conclave_core.roles import match_role as _match_role
from conclave_core.text import (
    format_arbitrate_as_text as _format_arbitrate_as_text,
)
from conclave_core.text import (
    format_claims_as_text as _format_claims_as_text,
)

# 节点签名：async def(state) -> state
Node = Callable[[MeetingState], Awaitable[MeetingState]]


__all__ = [
    "_ROLE_KEYWORDS",
    "Node",
    "_anchor",
    "_emit_agent_spoke",
    "_format_arbitrate_as_text",
    "_format_claims_as_text",
    "_full_anchor",
    "_match_role",
    "_record_drift",
    "_record_message",
    "_resolve_model_for_call",
    "_run_with_consistency",
    "_worst_confidence",
]
