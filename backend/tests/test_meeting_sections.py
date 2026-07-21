"""MeetingState sections 视图单元测试。

验证 sections property 和 snapshot_sections() 的字段映射正确性。
这是 P1 迁移（平铺字段 → sections 分组）的第一个迭代基础测试。
"""

from app.domain.meeting import (
    MeetingBorrowSection,
    MeetingCoreSection,
    MeetingDebateSection,
    MeetingIterationSection,
    MeetingObservabilitySection,
    MeetingState,
    MeetingStatus,
    Stage,
)


def _make_state() -> MeetingState:
    """构造一个各字段都有值的 MeetingState。"""
    state = MeetingState(
        meeting_id="mtg-sections-test",
        topic="测试 sections 视图",
        stage=Stage.CROSS_TEAM,
        status=MeetingStatus.RUNNING,
        clarified_topic="澄清后的议题",
        deliverable_type="prd_openapi",
        flow_plan="standard",
        debate_depth="deep",
        dynamic_routing=False,
        model_override="openai:gpt-4",
        owner_username="tester",
        owner_uid="uid-123",
        tenant_id=7,
    )
    # debate section 字段
    state.team_config = [{"role": "architect", "stance": "pro"}]
    state.role_configs = [{"id": "architect", "display_name": "架构师"}]
    state.key_questions = ["Q1?", "Q2?"]
    state.append_message({"id": "m1", "sender": "architect", "content": "hello"})
    state.injected_messages = [{"id": "inj1", "content": "注入"}]
    state.intervention_messages = [{"id": "iv1", "sender": "user", "content": "介入"}]
    state.team_conclusions = [{"team": "alpha", "conclusion": "C1"}]
    state.claims = [{"id": "cl1", "text": "声明1"}]
    state.conflicts = [{"id": "cf1", "text": "冲突1"}]
    state.evidence_set = [{"id": "ev1", "assessments": []}]
    state.prefetched_evidence = {"cf1": [{"text": "证据"}]}
    state.drift_log = [{"is_drift": False}]
    state.user_rejections = {"inj1": [{"agent_role": "architect", "reason": "偏题"}]}

    # borrow section 字段
    state.borrowed_agents = [{"role": "security_expert", "spoken": False}]
    state.auto_borrow_count = 1
    state.pending_borrow_request = {"id": "br1", "target_role": "security_expert"}
    state.borrow_frozen = False
    state.borrow_request_history = [{"id": "br1", "verdict": "auto_approved"}]

    # iteration section 字段
    state.iteration_count = 1
    state.max_iterations = 3
    state.quality_score = 75.5
    state.quality_feedback = "需要改进"
    state.iteration_history = [{"iteration": 0, "quality_score": 60.0}]
    state.auto_iterate = True
    state.checkpoint = {"stage": "cross_team", "completed_at": "2026-01-01T00:00:00Z"}
    state.stage_retry_count = {"clarify": 0, "intra_team": 1}
    state.max_stage_retries = 3

    # observability section 字段
    state.decision_record = {"type": "consensus"}
    state.artifact = {"title": "产出文档", "type": "prd"}
    state.doc_summaries = ["文档摘要1"]
    state.reference_meeting_ids = ["mtg-ref-1"]
    state.reference_context = "参考会议上下文"
    state.confidence_flags = {"clarify": "high", "intra_team": "low"}
    state.agent_evaluations = {"architect": {"overall_score": 0.8}}
    state.resolved_models = {"architect": "openai:gpt-4", "@arbitrate": "anthropic:claude-3"}
    state.paused_snapshot = {"stage": "intra_team"}
    state.participants = ["user1", "user2"]

    return state


class TestSectionsProperty:
    """sections property 基础测试。"""

    def test_sections_returns_all_five_groups(self):
        """sections 返回 5 个分组。"""
        state = _make_state()
        secs = state.sections
        assert set(secs.keys()) == {"core", "debate", "borrow", "iteration", "observability"}

    def test_core_section_type_and_fields(self):
        """core section 类型正确，字段映射正确。"""
        state = _make_state()
        core = state.sections["core"]
        assert isinstance(core, MeetingCoreSection)
        assert core.meeting_id == "mtg-sections-test"
        assert core.topic == "测试 sections 视图"
        assert core.stage == Stage.CROSS_TEAM
        assert core.status == MeetingStatus.RUNNING
        assert core.clarified_topic == "澄清后的议题"
        assert core.deliverable_type == "prd_openapi"
        assert core.flow_plan == "standard"
        assert core.debate_depth == "deep"
        assert core.dynamic_routing is False
        assert core.model_override == "openai:gpt-4"
        assert core.owner_username == "tester"
        assert core.owner_uid == "uid-123"
        assert core.tenant_id == 7

    def test_debate_section_type_and_fields(self):
        """debate section 类型正确，字段映射正确。"""
        state = _make_state()
        debate = state.sections["debate"]
        assert isinstance(debate, MeetingDebateSection)
        assert len(debate.team_config) == 1
        assert debate.team_config[0]["role"] == "architect"
        assert len(debate.role_configs) == 1
        assert len(debate.key_questions) == 2
        assert len(debate.messages) == 1
        assert debate.messages[0]["sender"] == "architect"
        assert len(debate.injected_messages) == 1
        assert len(debate.intervention_messages) == 1
        assert len(debate.team_conclusions) == 1
        assert len(debate.claims) == 1
        assert len(debate.conflicts) == 1
        assert len(debate.evidence_set) == 1
        assert debate.prefetched_evidence is not None
        assert "cf1" in debate.prefetched_evidence
        assert len(debate.drift_log) == 1
        assert "inj1" in debate.user_rejections

    def test_borrow_section_type_and_fields(self):
        """borrow section 类型正确，字段映射正确。"""
        state = _make_state()
        borrow = state.sections["borrow"]
        assert isinstance(borrow, MeetingBorrowSection)
        assert len(borrow.borrowed_agents) == 1
        assert borrow.borrowed_agents[0]["role"] == "security_expert"
        assert borrow.auto_borrow_count == 1
        assert borrow.pending_borrow_request is not None
        assert borrow.pending_borrow_request["target_role"] == "security_expert"
        assert borrow.borrow_frozen is False
        assert len(borrow.borrow_request_history) == 1

    def test_iteration_section_type_and_fields(self):
        """iteration section 类型正确，字段映射正确。"""
        state = _make_state()
        it = state.sections["iteration"]
        assert isinstance(it, MeetingIterationSection)
        assert it.iteration_count == 1
        assert it.max_iterations == 3
        assert it.quality_score == 75.5
        assert it.quality_feedback == "需要改进"
        assert len(it.iteration_history) == 1
        assert it.auto_iterate is True
        assert it.checkpoint is not None
        assert it.checkpoint["stage"] == "cross_team"
        assert it.stage_retry_count["intra_team"] == 1
        assert it.max_stage_retries == 3

    def test_observability_section_type_and_fields(self):
        """observability section 类型正确，字段映射正确。"""
        state = _make_state()
        obs = state.sections["observability"]
        assert isinstance(obs, MeetingObservabilitySection)
        assert obs.decision_record is not None
        assert obs.decision_record["type"] == "consensus"
        assert obs.artifact is not None
        assert obs.artifact["title"] == "产出文档"
        assert len(obs.doc_summaries) == 1
        assert len(obs.reference_meeting_ids) == 1
        assert obs.reference_context == "参考会议上下文"
        assert obs.confidence_flags["clarify"] == "high"
        assert obs.agent_evaluations is not None
        assert "architect" in obs.resolved_models
        assert obs.paused_snapshot is not None
        assert len(obs.participants) == 2


class TestSectionsReadonly:
    """sections 视图只读性测试。"""

    def test_sections_returns_copy_not_reference(self):
        """修改 section 视图不影响原始 state（视图是拷贝）。"""
        state = _make_state()
        core = state.sections["core"]
        core.clarified_topic = "被修改的议题"
        # 原始 state 不受影响
        assert state.clarified_topic == "澄清后的议题"

    def test_debate_messages_are_shallow_copy(self):
        """debate.messages 列表是浅拷贝（列表本身是新对象，但元素是共享引用）。

        这是 Pydantic model_copy 的默认行为。
        修改列表结构（append/remove）不影响原始 state，
        但修改列表内元素的字段会反映到原始 state（浅拷贝特性）。
        """
        state = _make_state()
        debate = state.sections["debate"]
        debate.messages.append({"id": "m2", "sender": "new"})
        # 原始 state 的 messages 列表不受影响
        assert len(state.messages) == 1


class TestSnapshotSections:
    """snapshot_sections() 方法测试。"""

    def test_snapshot_sections_returns_json_dict(self):
        """snapshot_sections 返回 JSON 可序列化的分组 dict。"""
        state = _make_state()
        result = state.snapshot_sections()
        assert isinstance(result, dict)
        assert set(result.keys()) == {"core", "debate", "borrow", "iteration", "observability"}

    def test_snapshot_sections_core_serialized(self):
        """core section 正确序列化为 JSON。"""
        state = _make_state()
        result = state.snapshot_sections()
        core = result["core"]
        assert core["meeting_id"] == "mtg-sections-test"
        assert core["stage"] == "cross_team"
        assert core["status"] == "running"
        assert core["clarified_topic"] == "澄清后的议题"

    def test_snapshot_sections_debate_serialized(self):
        """debate section 正确序列化为 JSON。"""
        state = _make_state()
        result = state.snapshot_sections()
        debate = result["debate"]
        assert len(debate["messages"]) == 1
        assert debate["messages"][0]["sender"] == "architect"
        assert len(debate["conflicts"]) == 1

    def test_snapshot_sections_borrow_serialized(self):
        """borrow section 正确序列化为 JSON。"""
        state = _make_state()
        result = state.snapshot_sections()
        borrow = result["borrow"]
        assert len(borrow["borrowed_agents"]) == 1
        assert borrow["auto_borrow_count"] == 1

    def test_snapshot_sections_all_json_serializable(self):
        """所有 section 数据可 JSON 序列化（无 datetime / Pydantic model 残留）。"""
        import json

        state = _make_state()
        result = state.snapshot_sections()
        # 如果包含不可序列化的对象，json.dumps 会抛 TypeError
        json.dumps(result, ensure_ascii=False)

    def test_snapshot_sections_vs_snapshot_consistency(self):
        """snapshot_sections() 与 snapshot() 的字段值一致。"""
        state = _make_state()
        flat = state.snapshot()
        grouped = state.snapshot_sections()

        # core 字段一致性
        assert grouped["core"]["meeting_id"] == flat["meeting_id"]
        assert grouped["core"]["stage"] == flat["stage"]
        assert grouped["core"]["status"] == flat["status"]

        # debate 字段一致性
        assert len(grouped["debate"]["messages"]) == len(flat["messages"])
        assert len(grouped["debate"]["conflicts"]) == len(flat["conflicts"])

        # borrow 字段一致性
        assert grouped["borrow"]["auto_borrow_count"] == flat["auto_borrow_count"]


class TestSectionsDefaultState:
    """空状态（默认值）下的 sections 视图测试。"""

    def test_default_state_sections_valid(self):
        """默认 MeetingState 的 sections 视图不报错。"""
        state = MeetingState(meeting_id="mtg-empty", topic="空状态")
        secs = state.sections
        assert secs["core"].meeting_id == "mtg-empty"
        assert secs["core"].stage == Stage.CLARIFY
        assert secs["debate"].messages == []
        assert secs["borrow"].borrowed_agents == []
        assert secs["iteration"].iteration_count == 0
        assert secs["observability"].artifact is None

    def test_default_snapshot_sections_serializable(self):
        """默认状态的 snapshot_sections() 可序列化。"""
        import json

        state = MeetingState(meeting_id="mtg-empty", topic="空状态")
        result = state.snapshot_sections()
        json.dumps(result, ensure_ascii=False)
