# Conclave 核心算法与核心逻辑包
# 本包独立于 app.events / app.models 运行时副作用代码，为后续 Cython 编译保护做准备。
from __future__ import annotations

# 自包含模块（无 app.models/app.events 运行时依赖）直接导入
from conclave_core.charter import (
    DriftCheck,
    MeetingCharter,
    build_charter_from_clarify,
)
from conclave_core.charter_logic import (
    check_drift,
    is_already_borrowed,
    register_borrow,
    to_prompt_anchor,
)
from conclave_core.conclusion_chain import (
    ConclusionChain,
    ConsistencyResult,
    LockedConclusion,
)
from conclave_core.conclusion_logic import (
    check_consistency,
    get_chain_summary,
    get_locked_context,
    lock_conclusion,
)
from conclave_core.confidence import worst_confidence
from conclave_core.scheduler import ExecutionPlan, Scheduler, SubTask
from conclave_core.text import (
    compress_decisions_to_brief,
    format_arbitrate_as_text,
    format_claims_as_text,
)

# 以下模块在运行时需要 app.models 中的类型（MeetingState / Stage / Role / MeetingStatus），
# 但 app.models 也会反向引用本包的 charter / conclusion_chain。为避免循环导入，
# 对这部分符号采用 PEP 562 延迟导出（只在被访问时才导入）。
_LAZY_SYMBOLS: dict[str, str] = {
    # anchor
    "get_charter_anchor": "conclave_core.anchor",
    "get_full_anchor": "conclave_core.anchor",
    # evidence
    "_synthesize_evidence_for_produce": "conclave_core.evidence",
    # roles
    "_ROLE_KEYWORDS": "conclave_core.roles",
    "match_role": "conclave_core.roles",
    # state
    "VALID_SIGNALS": "conclave_core.state",
    "ControlError": "conclave_core.state",
    "apply_signal": "conclave_core.state",
    "STAGE_ORDER": "conclave_core.state",
    "get_skipped_stages": "conclave_core.state",
    "next_stage": "conclave_core.state",
    "is_terminal": "conclave_core.state",
    "should_pause": "conclave_core.state",
}


def __getattr__(name: str) -> object:
    if name not in _LAZY_SYMBOLS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name = _LAZY_SYMBOLS[name]
    import importlib

    module = importlib.import_module(module_name)
    return getattr(module, name)


__all__ = [
    "STAGE_ORDER",
    # state
    "VALID_SIGNALS",
    # roles
    "_ROLE_KEYWORDS",
    # conclusion_chain
    "ConclusionChain",
    "ConsistencyResult",
    "ControlError",
    # charter
    "DriftCheck",
    # scheduler
    "ExecutionPlan",
    "LockedConclusion",
    "MeetingCharter",
    "Scheduler",
    "SubTask",
    # evidence
    "_synthesize_evidence_for_produce",
    "apply_signal",
    "build_charter_from_clarify",
    "check_consistency",
    "check_drift",
    "compress_decisions_to_brief",
    "format_arbitrate_as_text",
    # text
    "format_claims_as_text",
    "get_chain_summary",
    # anchor
    "get_charter_anchor",
    "get_full_anchor",
    "get_locked_context",
    "get_skipped_stages",
    "is_already_borrowed",
    "is_terminal",
    # conclusion_logic
    "lock_conclusion",
    "match_role",
    "next_stage",
    "register_borrow",
    "should_pause",
    # charter_logic
    "to_prompt_anchor",
    # confidence
    "worst_confidence",
]
