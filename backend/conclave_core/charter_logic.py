# 会议宪章业务逻辑（从 MeetingCharter Pydantic 模型中拆分出的无状态函数）
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from conclave_core.charter import DriftCheck, MeetingCharter

# 关键词提取时需要过滤的填充字符（中文常见虚词/单字）
_FILLER_CHARS = set("的了是这一个那和与及或等在对为地把被将又也都很已还就这那之其而")


def to_prompt_anchor(charter: "MeetingCharter") -> str:
    """生成注入每个 agent prompt 的锚点文本"""
    lines: list[str] = ["【会议宪章锚点 - 请严格遵守，不得漂移】"]
    lines.append(f"原始议题：{charter.original_topic}")
    if charter.clarified_topic:
        lines.append(f"澄清议题：{charter.clarified_topic}")
    if charter.meeting_goal:
        lines.append(f"会议目标：{charter.meeting_goal}")
    lines.append(f"议题边界：{('；'.join(charter.scope)) if charter.scope else '未限定'}")
    lines.append(
        f"行为约束：{('；'.join(charter.constraints)) if charter.constraints else '无'}"
    )
    if charter.forbidden_topics:
        lines.append(f"禁止话题：{('，'.join(charter.forbidden_topics))}")
    if charter.borrow_history:
        lines.append(f"已处理借调：{('，'.join(charter.borrow_history))}")
    lines.append("请确保发言与上述宪章一致，不得扩展到边界外或触及禁止话题。")
    return "\n".join(lines)


def check_drift(charter: "MeetingCharter", content: str) -> "DriftCheck":
    """检查发言是否偏离宪章

    首期简单实现：
    - 触及 forbidden_topics -> major drift
    - 若 scope 非空且发言不含任何 scope 关键词 -> minor drift
    - 否则无漂移
    """
    from conclave_core.charter import DriftCheck

    if not content:
        return DriftCheck(is_drift=False, reason="空内容", severity="none")

    content_lower = content.lower()

    # 1) 禁止话题 -> 重大漂移
    for ft in charter.forbidden_topics:
        if ft and ft.lower() in content_lower:
            return DriftCheck(
                is_drift=True,
                reason=f"触及禁止话题：{ft}",
                severity="major",
            )

    # 2) scope 关键词匹配 -> 轻微漂移
    keywords = _scope_keywords(charter)
    if keywords:
        matched = any(kw.lower() in content_lower for kw in keywords)
        if not matched:
            return DriftCheck(
                is_drift=True,
                reason="发言未触及议题范围内任何关键词",
                severity="minor",
            )

    return DriftCheck(is_drift=False, reason="符合宪章", severity="none")


def _scope_keywords(charter: "MeetingCharter") -> list[str]:
    """从 clarified_topic 与 scope 中抽取 2-gram 关键词，过滤填充字"""
    raw = charter.clarified_topic + " " + " ".join(charter.scope)
    # 去掉中英文标点与空白
    cleaned: list[str] = []
    for ch in raw:
        if ch.isalnum():
            cleaned.append(ch)
    text = "".join(cleaned)
    keywords: list[str] = []
    seen: set[str] = set()
    # 2-gram 滑动窗口
    for i in range(len(text) - 1):
        gram = text[i : i + 2]
        if any(c in _FILLER_CHARS for c in gram):
            continue
        if gram in seen:
            continue
        seen.add(gram)
        keywords.append(gram)
    return keywords


def register_borrow(charter: "MeetingCharter", target_role: str, verdict: str) -> None:
    """记录借调裁决，防重复"""
    if not target_role:
        return
    entry = f"{target_role}::{verdict}"
    if not is_already_borrowed(charter, target_role):
        charter.borrow_history.append(entry)


def is_already_borrowed(charter: "MeetingCharter", target_role: str) -> bool:
    """检查是否已借调过该角色"""
    if not target_role:
        return False
    prefix = f"{target_role}::"
    return any(e.startswith(prefix) for e in charter.borrow_history)
