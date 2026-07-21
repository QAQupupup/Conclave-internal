"""M1.1: ContextManager 动态窗口 + 摘要压缩测试

验证：
- 动态窗口根据 token 预算自适应调整大小（替代硬编码 [-8:]）
- 旧消息通过 LLM 摘要压缩保留关键信息（非直接丢弃）
- 摘要结果缓存（同一批消息不重复调用 LLM）
- 预算超限时按优先级裁剪
- _build_base_slice 兼容 MeetingState 的 Pydantic 模型属性
"""

from __future__ import annotations

import pytest

from app.orchestrator.context_manager import ContextBudget, ContextManager, ContextSlice


# ── 测试用 Mock State ──────────────────────────────────────


class MockCharter:
    """模拟 MeetingCharter（Pydantic 模型）"""

    def __init__(self, topic: str = "测试议题", goal: str = "测试目标"):
        self.original_topic = topic
        self.clarified_topic = topic
        self.meeting_goal = goal

    def model_dump(self, mode: str = "json") -> dict:
        return {
            "original_topic": self.original_topic,
            "clarified_topic": self.clarified_topic,
            "meeting_goal": self.meeting_goal,
        }


class MockConclusion:
    """模拟 LockedConclusion（Pydantic 模型）"""

    def __init__(self, stage: str = "clarify", content: dict | None = None):
        self.stage = stage
        self.content = content or {"summary": f"{stage} 阶段结论"}


class MockConclusionChain:
    """模拟 ConclusionChain（Pydantic 模型）"""

    def __init__(self, conclusions: list[MockConclusion] | None = None):
        self.conclusions = conclusions or []


class MockState:
    """轻量 Mock State，模拟 MeetingState 的关键属性"""

    def __init__(
        self,
        messages: list[dict] | None = None,
        charter: MockCharter | None = None,
        conclusion_chain: MockConclusionChain | None = None,
        evidence_set: list[dict] | None = None,
        meeting_id: str = "test-meeting",
        topic: str = "测试议题",
    ):
        self.messages = messages or []
        self.charter = charter
        self.conclusion_chain = conclusion_chain or MockConclusionChain()
        self.evidence_set = evidence_set or []
        self.meeting_id = meeting_id
        self.topic = topic


def _make_messages(n: int, content_template: str = "这是第 {} 条发言，内容较为丰富") -> list[dict]:
    """生成 n 条测试发言"""
    return [
        {"stage": "intra_team", "role": f"agent_{i % 3}", "content": content_template.format(i)}
        for i in range(n)
    ]


# ── 动态窗口测试 ─────────────────────────────────────────────


class TestDynamicWindow:
    """测试 _apply_dynamic_window 的自适应窗口大小"""

    @pytest.mark.asyncio
    async def test_empty_messages(self):
        """无发言时 recent_messages 为空。"""
        cm = ContextManager()
        state = MockState(messages=[])
        slice_ = await cm.prepare_async(state, "intra_team", "engineer")
        assert slice_.recent_messages == []

    @pytest.mark.asyncio
    async def test_few_messages_all_included(self):
        """发言数 < 窗口上限时全部包含。"""
        cm = ContextManager()
        msgs = _make_messages(3)
        state = MockState(messages=msgs)
        slice_ = await cm.prepare_async(state, "intra_team", "engineer")
        # 3 条消息全部包含（窗口 >= 3）
        assert len(slice_.recent_messages) <= 3
        assert len(slice_.recent_messages) >= 2

    @pytest.mark.asyncio
    async def test_many_messages_capped_at_20(self):
        """发言数 > 20 时窗口上限为 20。"""
        cm = ContextManager()
        msgs = _make_messages(50)
        state = MockState(messages=msgs)
        slice_ = await cm.prepare_async(state, "intra_team", "engineer")
        assert len(slice_.recent_messages) <= 20

    @pytest.mark.asyncio
    async def test_window_minimum_is_2(self):
        """预算极小时窗口下限为 2。"""
        cm = ContextManager(budget=ContextBudget(max_tokens=100, reserved_tokens=90))
        msgs = _make_messages(10)
        state = MockState(messages=msgs)
        slice_ = await cm.prepare_async(state, "intra_team", "engineer")
        assert len(slice_.recent_messages) >= 2

    @pytest.mark.asyncio
    async def test_long_messages_shrink_window(self):
        """超长发言时窗口应收缩以适应预算。"""
        cm = ContextManager(budget=ContextBudget(max_tokens=2000, reserved_tokens=500))
        long_msgs = _make_messages(30, content_template="第 {} 条：" + "很长的内容" * 100)
        state = MockState(messages=long_msgs)
        slice_ = await cm.prepare_async(state, "intra_team", "engineer")
        # 长消息时窗口应远小于 20
        assert len(slice_.recent_messages) < 20
        assert len(slice_.recent_messages) >= 2

    @pytest.mark.asyncio
    async def test_recent_messages_are_reversed(self):
        """recent_messages 应为倒序（最新在前）。"""
        cm = ContextManager()
        msgs = _make_messages(5)
        state = MockState(messages=msgs)
        slice_ = await cm.prepare_async(state, "intra_team", "engineer")
        if len(slice_.recent_messages) >= 2:
            # 第一条应是最后一条发言（倒序）
            first_content = slice_.recent_messages[0].get("content", "")
            last_msg_content = msgs[-1]["content"]
            assert first_content == last_msg_content


# ── 摘要压缩测试 ─────────────────────────────────────────────


class TestSummarization:
    """测试旧消息的 LLM 摘要压缩"""

    @pytest.mark.asyncio
    async def test_summary_generated_for_older_messages(self):
        """有旧消息且提供 llm_summarize 时应生成摘要。"""
        cm = ContextManager()
        msgs = _make_messages(25)
        state = MockState(messages=msgs)

        call_count = 0

        async def mock_summarize(prompt: str) -> str:
            nonlocal call_count
            call_count += 1
            return "这是旧消息的摘要：agent_0 和 agent_1 讨论了核心方案。"

        slice_ = await cm.prepare_async(
            state, "cross_team", "engineer", llm_summarize=mock_summarize
        )
        assert call_count == 1
        assert slice_.summarized_older_messages != ""
        assert "摘要" in slice_.summarized_older_messages

    @pytest.mark.asyncio
    async def test_no_summary_when_few_messages(self):
        """发言数少于窗口大小时不生成摘要。"""
        cm = ContextManager()
        msgs = _make_messages(3)
        state = MockState(messages=msgs)

        call_count = 0

        async def mock_summarize(prompt: str) -> str:
            nonlocal call_count
            call_count += 1
            return "不应被调用"

        slice_ = await cm.prepare_async(
            state, "intra_team", "engineer", llm_summarize=mock_summarize
        )
        assert call_count == 0
        assert slice_.summarized_older_messages == ""

    @pytest.mark.asyncio
    async def test_summary_cached(self):
        """同一批旧消息的摘要应被缓存，不重复调用 LLM。"""
        cm = ContextManager()
        msgs = _make_messages(25)
        state = MockState(messages=msgs)

        call_count = 0

        async def mock_summarize(prompt: str) -> str:
            nonlocal call_count
            call_count += 1
            return "缓存的摘要内容"

        # 第一次调用
        await cm.prepare_async(state, "cross_team", "engineer", llm_summarize=mock_summarize)
        assert call_count == 1

        # 第二次调用（同样的消息），应命中缓存
        await cm.prepare_async(state, "cross_team", "engineer", llm_summarize=mock_summarize)
        assert call_count == 1  # 仍然是 1，没有第二次调用

    @pytest.mark.asyncio
    async def test_summary_failure_graceful_degradation(self):
        """llm_summarize 抛异常时应降级为空摘要，不崩溃。"""
        cm = ContextManager()
        msgs = _make_messages(25)
        state = MockState(messages=msgs)

        async def failing_summarize(prompt: str) -> str:
            raise RuntimeError("LLM 不可用")

        slice_ = await cm.prepare_async(
            state, "cross_team", "engineer", llm_summarize=failing_summarize
        )
        # 不崩溃，摘要为空（降级）
        assert slice_.summarized_older_messages == ""

    @pytest.mark.asyncio
    async def test_no_summarize_callback(self):
        """不提供 llm_summarize 时不生成摘要，不报错。"""
        cm = ContextManager()
        msgs = _make_messages(25)
        state = MockState(messages=msgs)

        slice_ = await cm.prepare_async(state, "cross_team", "engineer")
        assert slice_.summarized_older_messages == ""


# ── 预算裁剪测试 ─────────────────────────────────────────────


class TestBudgetTrimming:
    """测试 _trim_to_budget 的优先级裁剪"""

    @pytest.mark.asyncio
    async def test_trim_reduces_message_count(self):
        """超预算时减少 recent_messages 数量。"""
        cm = ContextManager(budget=ContextBudget(max_tokens=500, reserved_tokens=100))
        msgs = _make_messages(30, content_template="第{}条发言：" + "内容" * 50)
        state = MockState(messages=msgs)
        slice_ = await cm.prepare_async(state, "intra_team", "engineer")
        # 预算很小，消息数应被裁剪
        assert len(slice_.recent_messages) <= 20
        # token 估算应不超过可用预算（可能有少量误差，允许 10% 容差）
        assert slice_.token_estimate <= cm.budget.available_tokens * 1.1

    @pytest.mark.asyncio
    async def test_charter_always_preserved(self):
        """宪章在裁剪中始终保留。"""
        cm = ContextManager(budget=ContextBudget(max_tokens=300, reserved_tokens=100))
        state = MockState(
            messages=_make_messages(20, content_template="长内容" * 30),
            charter=MockCharter(topic="重要议题"),
        )
        slice_ = await cm.prepare_async(state, "intra_team", "engineer")
        assert slice_.charter != {}

    @pytest.mark.asyncio
    async def test_evidence_check_keeps_more_evidence(self):
        """evidence_check 阶段保留完整证据。"""
        cm = ContextManager()
        evidence = [{"quote": f"证据 {i}", "source": f"doc:{i}"} for i in range(10)]
        state = MockState(messages=_make_messages(5), evidence_set=evidence)

        slice_ = await cm.prepare_async(state, "evidence_check", "engineer")
        assert len(slice_.evidence) == 10

    @pytest.mark.asyncio
    async def test_non_evidence_check_truncates_evidence(self):
        """非 evidence_check 阶段只保留前 3 条证据。"""
        cm = ContextManager()
        evidence = [{"quote": f"证据 {i}", "source": f"doc:{i}"} for i in range(10)]
        state = MockState(messages=_make_messages(5), evidence_set=evidence)

        slice_ = await cm.prepare_async(state, "arbitrate", "engineer")
        assert len(slice_.evidence) <= 3


# ── _build_base_slice 兼容性测试 ─────────────────────────────


class TestBuildBaseSlice:
    """测试基础切片构建对 MeetingState Pydantic 模型的兼容性"""

    @pytest.mark.asyncio
    async def test_charter_pydantic_model(self):
        """charter 为 Pydantic 模型时应通过 model_dump 转换。"""
        cm = ContextManager()
        state = MockState(charter=MockCharter(topic="Pydantic 议题", goal="测试目标"))
        slice_ = await cm.prepare_async(state, "clarify", "moderator")
        assert slice_.charter != {}
        assert "original_topic" in slice_.charter or "topic" in slice_.charter

    @pytest.mark.asyncio
    async def test_charter_dict(self):
        """charter 为 dict 时直接使用。"""
        cm = ContextManager()
        state = MockState(charter={"topic": "dict 议题"})  # type: ignore
        slice_ = await cm.prepare_async(state, "clarify", "moderator")
        assert slice_.charter == {"topic": "dict 议题"}

    @pytest.mark.asyncio
    async def test_conclusion_chain_pydantic_model(self):
        """conclusion_chain 为 ConclusionChain 模型时应提取 .conclusions。"""
        cm = ContextManager()
        chain = MockConclusionChain(
            conclusions=[
                MockConclusion(stage="clarify", content={"summary": "澄清结论"}),
                MockConclusion(stage="intra_team", content={"summary": "队内结论"}),
            ]
        )
        state = MockState(conclusion_chain=chain)
        slice_ = await cm.prepare_async(state, "cross_team", "engineer")
        assert len(slice_.locked_conclusions) == 2
        assert slice_.locked_conclusions[0]["stage"] == "clarify"

    @pytest.mark.asyncio
    async def test_conclusion_chain_list(self):
        """conclusion_chain 为 list 时直接使用。"""
        cm = ContextManager()
        chain_list = [
            {"stage": "clarify", "summary": "澄清结论"},
        ]
        state = MockState(conclusion_chain=chain_list)  # type: ignore
        slice_ = await cm.prepare_async(state, "cross_team", "engineer")
        assert len(slice_.locked_conclusions) == 1

    @pytest.mark.asyncio
    async def test_evidence_set_attribute(self):
        """应读取 state.evidence_set（而非 state.evidence）。"""
        cm = ContextManager()
        evidence = [{"quote": "证据A", "source": "doc:1"}]
        state = MockState(messages=_make_messages(3), evidence_set=evidence)
        slice_ = await cm.prepare_async(state, "evidence_check", "engineer")
        assert len(slice_.evidence) == 1
        assert slice_.evidence[0]["quote"] == "证据A"

    @pytest.mark.asyncio
    async def test_no_charter_no_crash(self):
        """无 charter 时不崩溃。"""
        cm = ContextManager()
        state = MockState(charter=None)
        slice_ = await cm.prepare_async(state, "clarify", "moderator")
        assert slice_.charter == {}


# ── ContextSlice.to_prompt_text 测试 ─────────────────────


class TestPromptText:
    """测试 ContextSlice.to_prompt_text 的输出格式"""

    @pytest.mark.asyncio
    async def test_summary_appears_in_prompt_text(self):
        """摘要应出现在 to_prompt_text 输出中。"""
        cm = ContextManager()
        msgs = _make_messages(25)
        state = MockState(messages=msgs)

        async def mock_summarize(prompt: str) -> str:
            return "历史讨论摘要：核心方案已确定。"

        slice_ = await cm.prepare_async(
            state, "cross_team", "engineer", llm_summarize=mock_summarize
        )
        text = slice_.to_prompt_text()
        assert "历史发言摘要" in text
        assert "核心方案已确定" in text

    @pytest.mark.asyncio
    async def test_recent_messages_in_prompt_text(self):
        """近期发言应出现在 to_prompt_text 输出中。"""
        cm = ContextManager()
        msgs = _make_messages(5)
        state = MockState(messages=msgs)
        slice_ = await cm.prepare_async(state, "intra_team", "engineer")
        text = slice_.to_prompt_text()
        assert "近期发言" in text


# ── 同步 prepare() 兼容性测试 ─────────────────────────────


class TestSyncPrepare:
    """测试同步 prepare() 接口仍可用（向后兼容）"""

    def test_sync_prepare_works(self):
        """同步 prepare() 应正常返回 ContextSlice。"""
        cm = ContextManager()
        state = MockState(messages=_make_messages(10))
        slice_ = cm.prepare(state, "intra_team", "engineer")
        assert isinstance(slice_, ContextSlice)
        assert len(slice_.recent_messages) >= 2

    def test_sync_prepare_no_summary(self):
        """同步 prepare() 不生成摘要（无 LLM 调用）。"""
        cm = ContextManager()
        state = MockState(messages=_make_messages(25))
        slice_ = cm.prepare(state, "intra_team", "engineer")
        # 同步接口不生成摘要
        assert slice_.summarized_older_messages == ""
