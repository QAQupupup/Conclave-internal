# § Context Manager：上下文治理组件
# 负责窗口监控、分层选择、摘要生成、跨会议记忆检索。
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ContextBudget:
    """上下文预算"""
    max_tokens: int = 8000
    reserved_tokens: int = 1500  # 留给 system/role/instruction
    @property
    def available_tokens(self) -> int:
        return self.max_tokens - self.reserved_tokens


@dataclass
class ContextSlice:
    """准备好喂给 Agent 的上下文切片"""
    charter: dict[str, Any] = field(default_factory=dict)
    locked_conclusions: list[dict[str, Any]] = field(default_factory=list)
    recent_messages: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    material_snippets: dict[str, Any] = field(default_factory=dict)
    # 各切片 token 估算
    token_estimate: int = 0

    def to_prompt_text(self) -> str:
        parts = []
        if self.charter:
            parts.append(f"# 会议宪章\n{self.charter.get('topic', '')}")
        if self.locked_conclusions:
            parts.append("# 已锁定结论\n" + "\n".join(
                f"- [{c.get('stage')}] {c.get('summary', '')}" for c in self.locked_conclusions
            ))
        if self.evidence:
            parts.append("# 证据\n" + "\n".join(
                f"- {e.get('quote', '')[:200]} ({e.get('source', '')})" for e in self.evidence
            ))
        if self.material_snippets:
            parts.append("# 物料\n")
            for k, v in self.material_snippets.items():
                parts.append(f"## {k}\n{str(v)[:600]}")
        if self.recent_messages:
            parts.append("# 近期发言\n" + "\n".join(
                f"[{m.get('stage')}] {m.get('role', '')}: {str(m.get('content', ''))[:200]}"
                for m in self.recent_messages
            ))
        return "\n\n".join(parts)


class ContextManager:
    """上下文治理器

    设计原则：
    - 显式预算：每次 LLM 调用前估算 token，不超限
    - 优先级分层：宪章 > 结论 > 证据 > 物料 > 近期发言
    - 可摘要：长内容按重要性/时间距离压缩
    """

    def __init__(self, budget: ContextBudget | None = None):
        self.budget = budget or ContextBudget()

    def prepare(
        self,
        state: Any,
        stage: str,
        role: str,
        extra_materials: dict[str, Any] | None = None,
    ) -> ContextSlice:
        """为某个 Agent 调用准备上下文切片"""
        slice_ = ContextSlice()

        # 1. 宪章（最高优先级，始终保留）
        if hasattr(state, "charter") and state.charter:
            slice_.charter = state.charter if isinstance(state.charter, dict) else {"topic": str(state.charter)}

        # 2. 已锁定结论
        if hasattr(state, "conclusion_chain"):
            chain = state.conclusion_chain
            if isinstance(chain, list):
                slice_.locked_conclusions = [
                    {"stage": c.get("stage", ""), "summary": c.get("summary", str(c)[:120])}
                    for c in chain
                ]

        # 3. 证据（仅 evidence_check 阶段保留完整，其他阶段摘要）
        if hasattr(state, "evidence"):
            evidence_list = state.evidence if isinstance(state.evidence, list) else []
            if stage == "evidence_check":
                slice_.evidence = evidence_list
            else:
                slice_.evidence = evidence_list[:3]

        # 4. 物料（RAG/搜索/产物）
        slice_.material_snippets = extra_materials or {}

        # 5. 近期发言（按时间倒序，根据预算决定数量）
        if hasattr(state, "messages") and isinstance(state.messages, list):
            slice_.recent_messages = list(reversed(state.messages[-8:]))

        # 6. 预算裁剪
        slice_ = self._trim_to_budget(slice_, stage)
        slice_.token_estimate = self._estimate_tokens(slice_)
        return slice_

    def _trim_to_budget(self, slice_: ContextSlice, stage: str) -> ContextSlice:
        # 简单策略：按优先级保留，超限时先裁剪 recent_messages，再裁剪 evidence
        while self._estimate_tokens(slice_) > self.budget.available_tokens:
            if len(slice_.recent_messages) > 2:
                slice_.recent_messages = slice_.recent_messages[:-1]
            elif len(slice_.evidence) > 1 and stage != "evidence_check":
                slice_.evidence = slice_.evidence[:-1]
            elif slice_.material_snippets:
                # 截断最长的物料
                longest = max(slice_.material_snippets, key=lambda k: len(str(slice_.material_snippets[k])))
                text = str(slice_.material_snippets[longest])
                slice_.material_snippets[longest] = text[: len(text) // 2]
            else:
                break
        return slice_

    @staticmethod
    def _estimate_tokens(slice_: ContextSlice) -> int:
        # 粗略估算：1 token ≈ 1.5 中文字符 或 4 英文字符
        text = slice_.to_prompt_text()
        cn = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
        other = len(text) - cn
        return int(cn / 1.5 + other / 4)
