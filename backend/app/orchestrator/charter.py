# §会议宪章：不可变锚点，每阶段注入 agent prompt 防止漂移
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


# 系统预设行为约束（clarify 阶段构造 charter 时写入，可追加）
DEFAULT_CONSTRAINTS: list[str] = [
    "只讨论与议题直接相关的内容",
    "不扩展到议题边界外的领域",
    "不重复已裁决的冲突",
    "借调需经三问法裁决",
    "每个 agent 发言必须与当前阶段目标一致",
]

# 关键词提取时需要过滤的填充字符（中文常见虚词/单字）
_FILLER_CHARS = set("的了是这一个那和与及或等在对为地把被将又也都很已还就这那之其而")


class DriftCheck(BaseModel):
    """漂移检查结果"""
    is_drift: bool = False
    reason: str = ""
    severity: str = "none"  # "none" | "minor" | "major"


class MeetingCharter(BaseModel):
    """会议宪章：不可变锚点，每阶段注入 agent prompt 防止漂移

    - original_topic：用户原始输入，不可篡改
    - clarified_topic：clarify 阶段 LLM 澄清后的议题
    - meeting_goal：会议目标
    - scope：议题边界短语（clarify 阶段确定）
    - constraints：行为约束（系统预设 + 可追加）
    - forbidden_topics：禁止话题（防漂移）
    - borrow_history：已拒绝/批准的借调角色记录（防重复借调）
    """
    meeting_id: str
    original_topic: str
    clarified_topic: str = ""
    meeting_goal: str = ""
    scope: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    forbidden_topics: list[str] = Field(default_factory=list)
    borrow_history: list[str] = Field(default_factory=list)

    # ---------- 锚点注入 ----------

    def to_prompt_anchor(self) -> str:
        """生成注入每个 agent prompt 的锚点文本"""
        lines: list[str] = ["【会议宪章锚点 - 请严格遵守，不得漂移】"]
        lines.append(f"原始议题：{self.original_topic}")
        if self.clarified_topic:
            lines.append(f"澄清议题：{self.clarified_topic}")
        if self.meeting_goal:
            lines.append(f"会议目标：{self.meeting_goal}")
        lines.append(f"议题边界：{('；'.join(self.scope)) if self.scope else '未限定'}")
        lines.append(
            f"行为约束：{('；'.join(self.constraints)) if self.constraints else '无'}"
        )
        if self.forbidden_topics:
            lines.append(f"禁止话题：{('，'.join(self.forbidden_topics))}")
        if self.borrow_history:
            lines.append(f"已处理借调：{('，'.join(self.borrow_history))}")
        lines.append("请确保发言与上述宪章一致，不得扩展到边界外或触及禁止话题。")
        return "\n".join(lines)

    # ---------- 漂移检查 ----------

    def check_drift(self, content: str) -> DriftCheck:
        """检查发言是否偏离宪章

        首期简单实现：
        - 触及 forbidden_topics -> major drift
        - 若 scope 非空且发言不含任何 scope 关键词 -> minor drift
        - 否则无漂移
        """
        if not content:
            return DriftCheck(is_drift=False, reason="空内容", severity="none")

        content_lower = content.lower()

        # 1) 禁止话题 -> 重大漂移
        for ft in self.forbidden_topics:
            if ft and ft.lower() in content_lower:
                return DriftCheck(
                    is_drift=True,
                    reason=f"触及禁止话题：{ft}",
                    severity="major",
                )

        # 2) scope 关键词匹配 -> 轻微漂移
        keywords = self._scope_keywords()
        if keywords:
            matched = any(kw.lower() in content_lower for kw in keywords)
            if not matched:
                return DriftCheck(
                    is_drift=True,
                    reason="发言未触及议题范围内任何关键词",
                    severity="minor",
                )

        return DriftCheck(is_drift=False, reason="符合宪章", severity="none")

    def _scope_keywords(self) -> list[str]:
        """从 clarified_topic 与 scope 中抽取 2-gram 关键词，过滤填充字"""
        raw = self.clarified_topic + " " + " ".join(self.scope)
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

    # ---------- 借调防重复 ----------

    def register_borrow(self, target_role: str, verdict: str) -> None:
        """记录借调裁决，防重复"""
        if not target_role:
            return
        entry = f"{target_role}::{verdict}"
        if not self.is_already_borrowed(target_role):
            self.borrow_history.append(entry)

    def is_already_borrowed(self, target_role: str) -> bool:
        """检查是否已借调过该角色"""
        if not target_role:
            return False
        prefix = f"{target_role}::"
        return any(e.startswith(prefix) for e in self.borrow_history)


def build_charter_from_clarify(
    meeting_id: str,
    original_topic: str,
    clarified_topic: str,
    key_questions: list[str] | None = None,
    extra_constraints: list[str] | None = None,
    forbidden_topics: list[str] | None = None,
) -> MeetingCharter:
    """clarify_node 调用：根据澄清结果构造会议宪章

    - meeting_goal 由澄清议题推导
    - scope 用关键问题 + 澄清议题作为边界短语
    - constraints 注入系统预设约束，可追加
    """
    key_questions = key_questions or []
    scope: list[str] = []
    if clarified_topic:
        scope.append(clarified_topic)
    scope.extend(q for q in key_questions if q)

    goal = f"针对「{clarified_topic or original_topic}」达成决策共识并产出 PRD 与 OpenAPI"

    constraints = list(DEFAULT_CONSTRAINTS)
    if extra_constraints:
        constraints.extend(extra_constraints)

    return MeetingCharter(
        meeting_id=meeting_id,
        original_topic=original_topic,
        clarified_topic=clarified_topic or original_topic,
        meeting_goal=goal,
        scope=scope,
        constraints=constraints,
        forbidden_topics=forbidden_topics or [],
        borrow_history=[],
    )
