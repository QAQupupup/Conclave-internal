# Shared helpers for pipeline stage nodes.
# 兼容层：内部实现已迁移到 stage_common.py，本文件仅保留旧符号导出。
from __future__ import annotations

from typing import Any, Awaitable, Callable

from app.models import MeetingState, Role, Stage
from app.orchestrator.stage_common import (
    emit_agent_spoke as _emit_agent_spoke,
    format_arbitrate_as_text as _format_arbitrate_as_text,
    format_claims_as_text as _format_claims_as_text,
    get_charter_anchor as _anchor,
    get_full_anchor as _full_anchor,
    match_role as _match_role,
    record_drift as _record_drift,
    record_message as _record_message,
    resolve_model_for_call as _resolve_model_for_call,
    run_with_consistency as _run_with_consistency,
    worst_confidence as _worst_confidence,
)

# 节点签名：async def(state) -> state
Node = Callable[[MeetingState], Awaitable[MeetingState]]

# 保留旧模块级变量别名
_ROLE_KEYWORDS: dict[str, list[str]] = {
    Role.PRODUCT_ARCHITECT.value: ["product", "architect", "产品", "架构", "pm", "产品经理", "产品架构"],
    Role.SECURITY_EXPERT.value: ["security", "安全", "风控", "sec"],
    Role.DATA_ENGINEER.value: ["data", "数据", "analytics", "分析"],
    Role.UX_DESIGNER.value: ["ux", "design", "设计", "体验", "ui"],
    Role.MARKETING_EXPERT.value: ["marketing", "市场", "营销", "brand", "growth"],
    Role.ENGINEER.value: ["engineer", "develop", "开发", "工程", "后端", "前端", "技术"],
    Role.MODERATOR.value: ["moderator", "host", "主持", "协调", "facilitator"],
}


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
