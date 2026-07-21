# § Context Manager：上下文治理组件
# 负责窗口监控、分层选择、摘要生成、跨会议记忆检索。
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.logging_config import get_logger

logger = get_logger("orchestrator.context_manager")


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
    # M1.1: 旧消息摘要（被压缩的消息的关键信息保留）
    summarized_older_messages: str = ""
    # 各切片 token 估算
    token_estimate: int = 0

    def to_prompt_text(self) -> str:
        parts = []
        if self.charter:
            parts.append(f"# 会议宪章\n{self.charter.get('topic', '')}")
        if self.locked_conclusions:
            parts.append(
                "# 已锁定结论\n"
                + "\n".join(f"- [{c.get('stage')}] {c.get('summary', '')}" for c in self.locked_conclusions)
            )
        if self.evidence:
            parts.append(
                "# 证据\n" + "\n".join(f"- {e.get('quote', '')[:200]} ({e.get('source', '')})" for e in self.evidence)
            )
        if self.material_snippets:
            parts.append("# 物料\n")
            for k, v in self.material_snippets.items():
                parts.append(f"## {k}\n{str(v)[:600]}")
        # M1.1: 旧消息摘要优先于近期发言（提供历史上下文）
        if self.summarized_older_messages:
            parts.append(f"# 历史发言摘要\n{self.summarized_older_messages}")
        if self.recent_messages:
            parts.append(
                "# 近期发言\n"
                + "\n".join(
                    f"[{m.get('stage')}] {m.get('role', '')}: {str(m.get('content', ''))[:200]}"
                    for m in self.recent_messages
                )
            )
        return "\n\n".join(parts)


class ContextManager:
    """上下文治理器

    设计原则：
    - 显式预算：每次 LLM 调用前估算 token，不超限
    - 优先级分层：宪章 > 结论 > 证据 > 物料 > 旧消息摘要 > 近期发言
    - 动态窗口：根据 budget.available_tokens 计算窗口大小，替代硬编码 [-8:]
    - 摘要压缩：超预算时对旧消息生成 LLM 摘要保留关键信息（非直接丢弃）

    M1.1 改进：
    - prepare_async(): 动态窗口 + 摘要压缩
    - prepare(): 保持同步接口（兼容性，仅动态窗口无摘要）
    - 摘要结果缓存（同一批消息不重复摘要）
    """

    # 摘要 prompt 模板
    _SUMMARIZE_PROMPT = (
        "请将以下会议发言压缩为简洁摘要，保留：\n"
        "1. 每位发言者的核心观点（1-2 句）\n"
        "2. 关键决策和结论\n"
        "3. 未解决的分歧\n"
        "丢弃：寒暄、重复内容、无关细节。\n\n"
        "发言内容：\n{messages}\n\n摘要："
    )
    # 单条消息的最小 token 估算（用于动态窗口计算）
    _MIN_MSG_TOKENS = 50
    # 摘要最大 token（控制摘要长度）
    _MAX_SUMMARY_TOKENS = 500

    def __init__(self, budget: ContextBudget | None = None):
        self.budget = budget or ContextBudget()
        # 摘要缓存：key = 消息内容的 hash，value = 摘要文本
        self._summary_cache: dict[str, str] = {}

    def prepare(
        self,
        state: Any,
        stage: str,
        role: str,
        extra_materials: dict[str, Any] | None = None,
    ) -> ContextSlice:
        """为某个 Agent 调用准备上下文切片（同步，仅动态窗口，无摘要压缩）。

        保持同步接口兼容性。需要摘要压缩时用 prepare_async()。
        """
        slice_ = self._build_base_slice(state, stage, extra_materials)
        # 动态窗口：根据预算计算窗口大小
        slice_ = self._apply_dynamic_window(slice_, state, stage)
        # 预算裁剪（降级：直接丢弃低优先级内容）
        slice_ = self._trim_to_budget(slice_, stage)
        slice_.token_estimate = self._estimate_tokens(slice_)
        return slice_

    async def prepare_async(
        self,
        state: Any,
        stage: str,
        role: str,
        extra_materials: dict[str, Any] | None = None,
        llm_summarize: Any | None = None,
    ) -> ContextSlice:
        """为某个 Agent 调用准备上下文切片（异步，动态窗口 + 摘要压缩）。

        Args:
            llm_summarize: 可选的异步回调，签名 async (prompt: str) -> str
                           用于生成旧消息摘要。为 None 时降级为裁剪。
        """
        slice_ = self._build_base_slice(state, stage, extra_materials)
        # 动态窗口：根据预算计算窗口大小
        slice_ = self._apply_dynamic_window(slice_, state, stage)

        # 摘要压缩：如果仍有旧消息被丢弃且提供了 llm_summarize，生成摘要
        older_messages = self._get_older_messages(state, slice_)
        if older_messages and llm_summarize:
            try:
                slice_.summarized_older_messages = await self._summarize_messages(older_messages, llm_summarize)
            except Exception as e:
                logger.warning("ContextManager 摘要生成失败，降级为裁剪: %s", e)
                # 降级：不做摘要

        # 预算裁剪
        slice_ = self._trim_to_budget(slice_, stage)
        slice_.token_estimate = self._estimate_tokens(slice_)
        return slice_

    def _build_base_slice(
        self,
        state: Any,
        stage: str,
        extra_materials: dict[str, Any] | None,
    ) -> ContextSlice:
        """构建基础切片（宪章、结论、证据、物料）。

        兼容多种 state 类型：MeetingState（Pydantic 模型属性）和简单 dict/list。
        """
        slice_ = ContextSlice()

        # 1. 宪章（最高优先级，始终保留）
        if hasattr(state, "charter") and state.charter:
            charter = state.charter
            if isinstance(charter, dict):
                slice_.charter = charter
            elif hasattr(charter, "model_dump"):
                # MeetingCharter Pydantic 模型
                slice_.charter = charter.model_dump(mode="json")
            else:
                slice_.charter = {"topic": str(charter)}

        # 2. 已锁定结论（兼容 list / ConclusionChain Pydantic 模型）
        if hasattr(state, "conclusion_chain"):
            chain = state.conclusion_chain
            if isinstance(chain, list):
                conclusions = chain
            elif hasattr(chain, "conclusions"):
                # ConclusionChain.conclusions: list[LockedConclusion]
                conclusions = chain.conclusions
            else:
                conclusions = []
            slice_.locked_conclusions = [
                {
                    "stage": c.get("stage", "") if isinstance(c, dict) else getattr(c, "stage", ""),
                    "summary": (
                        c.get("summary", str(c.get("content", ""))[:120])
                        if isinstance(c, dict)
                        else str(getattr(c, "content", ""))[:120]
                    ),
                }
                for c in (conclusions if isinstance(conclusions, list) else [])
            ]

        # 3. 证据（兼容 state.evidence / state.evidence_set）
        evidence_list: list[dict[str, Any]] = []
        for attr in ("evidence", "evidence_set"):
            if hasattr(state, attr):
                val = getattr(state, attr)
                if isinstance(val, list):
                    evidence_list = val
                    break
        if stage == "evidence_check":
            slice_.evidence = evidence_list
        else:
            slice_.evidence = evidence_list[:3]

        # 4. 物料（RAG/搜索/产物）
        slice_.material_snippets = extra_materials or {}

        return slice_

    def _apply_dynamic_window(self, slice_: ContextSlice, state: Any, stage: str) -> ContextSlice:
        """M1.1: 根据预算动态计算窗口大小，替代硬编码 [-8:]。

        策略：
        1. 计算非消息部分（宪章+结论+证据+物料）已占用的 token
        2. 剩余可用 token 除以平均消息 token 估算窗口大小
        3. 窗口大小限制在 [2, 20] 之间
        """
        if not hasattr(state, "messages") or not isinstance(state.messages, list):
            return slice_

        all_messages = state.messages
        if not all_messages:
            return slice_

        # 计算非消息部分占用 token
        non_msg_slice = ContextSlice(
            charter=slice_.charter,
            locked_conclusions=slice_.locked_conclusions,
            evidence=slice_.evidence,
            material_snippets=slice_.material_snippets,
        )
        non_msg_tokens = self._estimate_tokens(non_msg_slice)
        remaining_tokens = self.budget.available_tokens - non_msg_tokens

        if remaining_tokens <= 0:
            # 非消息部分已超预算，只保留最近 2 条
            window_size = 2
        else:
            # 估算单条消息平均 token
            sample_msgs = all_messages[-10:] if len(all_messages) > 10 else all_messages
            avg_msg_tokens = max(
                self._MIN_MSG_TOKENS,
                int(
                    sum(self._estimate_text_tokens(str(m.get("content", ""))) for m in sample_msgs)
                    / max(len(sample_msgs), 1)
                ),
            )
            # 动态窗口大小 = 剩余 token / 平均消息 token，限制在 [2, 20]
            window_size = max(2, min(20, remaining_tokens // avg_msg_tokens))

        slice_.recent_messages = list(reversed(all_messages[-window_size:]))
        return slice_

    def _get_older_messages(self, state: Any, slice_: ContextSlice) -> list[dict[str, Any]]:
        """获取被动态窗口排除的旧消息（用于摘要压缩）。"""
        if not hasattr(state, "messages") or not isinstance(state.messages, list):
            return []

        all_messages = state.messages
        if not all_messages:
            return []

        # recent_messages 是倒序的，取原始列表中未被包含的部分
        window_size = len(slice_.recent_messages)
        if window_size >= len(all_messages):
            return []

        # 旧消息 = 除最近 window_size 条之外的所有消息
        older = all_messages[:-window_size] if window_size > 0 else all_messages
        return older

    async def _summarize_messages(
        self,
        messages: list[dict[str, Any]],
        llm_summarize: Any,
    ) -> str:
        """调用 LLM 生成旧消息摘要，带缓存。

        Args:
            messages: 旧消息列表
            llm_summarize: async (prompt: str) -> str 回调

        Returns:
            摘要文本
        """
        # 缓存 key：消息内容的 hash
        cache_key = str(hash(tuple(str(m.get("content", ""))[:100] for m in messages)))
        if cache_key in self._summary_cache:
            return self._summary_cache[cache_key]

        # 构造摘要 prompt
        msg_text = "\n".join(
            f"[{m.get('stage', '')}] {m.get('role', '')}: {str(m.get('content', ''))[:300]}"
            for m in messages[-20:]  # 最多摘要最近 20 条旧消息
        )
        prompt = self._SUMMARIZE_PROMPT.format(messages=msg_text)

        # 调用 LLM 生成摘要
        summary = await llm_summarize(prompt)
        # 截断摘要（防止过长）
        if len(summary) > self._MAX_SUMMARY_TOKENS * 4:  # 粗略 token→字符转换
            summary = summary[: self._MAX_SUMMARY_TOKENS * 4] + "..."

        # 缓存
        self._summary_cache[cache_key] = summary
        return summary

    def _trim_to_budget(self, slice_: ContextSlice, stage: str) -> ContextSlice:
        """预算裁剪：超预算时按优先级丢弃低优先级内容。

        优先级（从低到高丢弃）：近期发言 > 旧消息摘要 > 物料 > 证据 > 结论 > 宪章
        """
        while self._estimate_tokens(slice_) > self.budget.available_tokens:
            if len(slice_.recent_messages) > 2:
                slice_.recent_messages = slice_.recent_messages[:-1]
            elif slice_.summarized_older_messages:
                # 截断摘要
                slice_.summarized_older_messages = slice_.summarized_older_messages[
                    : len(slice_.summarized_older_messages) // 2
                ]
                if len(slice_.summarized_older_messages) < 50:
                    slice_.summarized_older_messages = ""
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
    def _estimate_text_tokens(text: str) -> int:
        """估算单段文本的 token 数。"""
        cn = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
        other = len(text) - cn
        return int(cn / 1.5 + other / 4)

    @classmethod
    def _estimate_tokens(cls, slice_: ContextSlice) -> int:
        """估算整个切片的 token 数。"""
        text = slice_.to_prompt_text()
        return cls._estimate_text_tokens(text)
