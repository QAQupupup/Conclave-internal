# Shared helpers for pipeline stage nodes.
# 兼容层：纯算法实现已迁移到 conclave_core/，副作用函数保留在 app.orchestrator.stage_common。
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

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
    "_build_tool_registry",
    "_emit_agent_spoke",
    "_format_arbitrate_as_text",
    "_format_claims_as_text",
    "_full_anchor",
    "_match_role",
    "_record_drift",
    "_record_message",
    "_resolve_model_for_call",
    "_run_stage_step",
    "_run_with_consistency",
    "_worst_confidence",
]


# ---- 带可选工具的 LLM 步骤执行（工具在全部环节可用）----


def _build_tool_registry() -> Any:
    """尝试构建默认工具注册表（web_search/web_fetch/browser/workspace）。

    构建失败（如依赖缺失）时返回 None，调用方降级为单次 LLM 调用。
    每个节点执行时调用一次，避免全局单例带来的测试隔离问题。
    """
    try:
        from app.orchestrator.react_loop import create_default_tool_registry

        return create_default_tool_registry()
    except Exception:
        return None


async def _run_stage_step(
    state: MeetingState,
    stage: str,
    role: str,
    build_prompt: Callable[[str, Any], Any],
    tool_registry: Any = None,
    on_token: Callable[..., Awaitable[None]] | None = None,
) -> tuple[dict[str, Any], str]:
    """执行带可选工具的 LLM 步骤。

    tool_registry 非空时走 ReactLoop 多轮工具调用（遵循 evidence_check 既有行为，
    不做一致性自检）；否则回退到单次调用 + 一致性自检。

    build_prompt(anchor, available_tools) 返回 ThinkRequest。
    返回 (result, confidence)。
    """
    import contextlib

    if tool_registry is not None:
        try:
            from app.agents.compute import get_compute
            from app.events import bus as _bus
            from app.events import make_event as _make_event
            from app.orchestrator.react_loop import ReactLoop

            async def _on_tool_event(event_type: str, payload: dict[str, Any]) -> None:
                with contextlib.suppress(Exception):
                    await _bus.publish(_make_event(event_type, state.meeting_id, payload))

            anchor = _full_anchor(state, stage)
            react = ReactLoop(
                compute=get_compute(),
                tools=tool_registry,
                meeting_id=state.meeting_id,
                on_tool_event=_on_tool_event,
            )
            req = build_prompt(anchor, tool_registry.get_available_tools())
            req.model = _resolve_model_for_call(state, role, stage)
            if on_token is not None:
                req.on_token = on_token
            resp = await react.run(req)
            return resp.result, "high"
        except Exception:
            pass  # ReactLoop 失败时降级到单次调用（与 evidence_check 行为一致）

    async def call_fn(anchor: str) -> dict[str, Any]:
        from app.agents.compute import execute_think

        req = build_prompt(anchor, None)
        req.model = _resolve_model_for_call(state, role, stage)
        if on_token is not None:
            req.on_token = on_token
        resp = await execute_think(req)
        return resp.result

    return await _run_with_consistency(state, stage, call_fn)
