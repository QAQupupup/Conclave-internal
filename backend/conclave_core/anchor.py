# 宪章锚点构造（无副作用，只读 state）
from __future__ import annotations

from app.models import MeetingState


def get_charter_anchor(state: MeetingState) -> str:
    """取会议宪章锚点文本，charter 不存在时返回空串"""
    if state.charter is None:
        return ""
    return state.charter.to_prompt_anchor()


def get_full_anchor(state: MeetingState, stage: str) -> str:
    """构造完整锚点：宪章锚点 + 已锁定结论上下文 + 历史会议引用上下文"""
    parts: list[str] = []
    charter_anchor = get_charter_anchor(state)
    if charter_anchor:
        parts.append(charter_anchor)
    locked_context = state.conclusion_chain.get_locked_context(stage)
    if locked_context:
        parts.append(locked_context)
    if state.reference_context:
        parts.append(state.reference_context)
    return "\n\n".join(parts) if parts else ""
