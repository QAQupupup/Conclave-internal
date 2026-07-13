# 核心链路测试：clarify → intra_team 状态流转 + claims 生成
# 使用 StubLLM（不烧 token），验证状态机和数据流正确性
import asyncio


from app.models import MeetingStatus
from app.orchestrator import runner as runner_mod
from app.orchestrator.runner import Runner
from conclave_core.state import STAGE_ORDER, next_stage, is_terminal, should_pause


# ---------- 状态机辅助函数 ----------

def test_stage_order():
    """STAGE_ORDER 应为六阶段固定顺序"""
    assert STAGE_ORDER == ["clarify", "intra_team", "cross_team", "evidence_check", "arbitrate", "produce"]


def test_next_stage():
    """next_stage 返回下一阶段"""
    assert next_stage("clarify") == "intra_team"
    assert next_stage("intra_team") == "cross_team"
    assert next_stage("produce") is None  # 终态


def test_is_terminal():
    """is_terminal 判断终态"""
    # 需要构造 MeetingState，这里简单测 status
    from app.models import MeetingState as MS
    state = MS(meeting_id="test", topic="test")
    state.status = MeetingStatus.DONE
    assert is_terminal(state) is True

    state.status = MeetingStatus.ABORTED
    assert is_terminal(state) is True

    state.status = MeetingStatus.RUNNING
    assert is_terminal(state) is False


def test_should_pause():
    """should_pause 判断暂停态"""
    from app.models import MeetingState as MS
    state = MS(meeting_id="test", topic="test")
    state.status = MeetingStatus.PAUSED
    assert should_pause(state) is True

    state.status = MeetingStatus.RUNNING
    assert should_pause(state) is False


# ---------- 控制信号 ----------

def test_pause_resume_signal(client):
    """pause/resume 信号正确改变状态"""
    resp = client.post("/meetings", json={"topic": "暂停恢复测试"})
    meeting_id = resp.json()["meeting_id"]

    state = runner_mod.get_state(meeting_id)
    # 创建后默认 PAUSED，先设为 RUNNING
    state.status = MeetingStatus.RUNNING

    from conclave_core.state import apply_signal
    state = apply_signal(state, "pause")
    assert state.status == MeetingStatus.PAUSED

    state = apply_signal(state, "resume")
    assert state.status == MeetingStatus.RUNNING


def test_abort_signal(client):
    """abort 信号终止会议"""
    resp = client.post("/meetings", json={"topic": "终止测试"})
    meeting_id = resp.json()["meeting_id"]

    state = runner_mod.get_state(meeting_id)
    state.status = MeetingStatus.RUNNING

    from conclave_core.state import apply_signal
    apply_signal(state, "abort")
    assert state.status == MeetingStatus.ABORTED
    assert is_terminal(state)


def test_inject_signal(client):
    """inject 信号追加消息"""
    resp = client.post("/meetings", json={"topic": "注入测试"})
    meeting_id = resp.json()["meeting_id"]

    state = runner_mod.get_state(meeting_id)
    initial_count = len(state.injected_messages)

    from conclave_core.state import apply_signal
    apply_signal(state, "inject", {"role": "product_architect", "content": "额外补充：需要支持移动端"})
    assert len(state.injected_messages) == initial_count + 1
    assert state.injected_messages[-1]["content"] == "额外补充：需要支持移动端"


# ---------- 端到端：clarify → intra_team ----------

def test_clarify_to_intra_team_flow(client):
    """验证 clarify → intra_team 两阶段的状态流转 + 数据生成

    使用 StubLLM，验证：
    1. clarify 生成 clarified_topic / key_questions / team_config
    2. intra_team 生成 messages 和 claims
    3. conclusion_chain 长度增长
    4. 状态正确流转到 cross_team
    """
    resp = client.post("/meetings", json={"topic": "设计一个任务管理 API"})
    meeting_id = resp.json()["meeting_id"]

    state = runner_mod.get_state(meeting_id)
    state.status = MeetingStatus.RUNNING

    # 只跑前两个阶段：手动控制
    from app.orchestrator.nodes import clarify_node
    state = asyncio.run(clarify_node(state))

    # 验证 clarify 输出
    assert state.clarified_topic is not None, "clarify 应生成澄清后议题"
    assert len(state.key_questions) > 0, "clarify 应生成关键问题"
    assert len(state.team_config) > 0, "clarify 应生成团队配置"
    assert state.charter is not None, "clarify 应生成会议宪章"
    assert state.confidence_flags.get("clarify") in ("high", "low", "fallback")

    # 结论链第 1 步
    assert len(state.conclusion_chain.conclusions) >= 1, "结论链应有 clarify 步骤"

    # 跑 intra_team
    from app.orchestrator.nodes import intra_team_node
    state = asyncio.run(intra_team_node(state))

    # 验证 intra_team 输出
    assert len(state.messages) > 0, "intra_team 应生成发言"
    assert len(state.claims) > 0, "intra_team 应生成 claims"
    assert state.confidence_flags.get("intra_team") in ("high", "low", "fallback")

    # 验证 claims 有正确字段
    for claim in state.claims:
        # claim 字段可能是 text 或 claim
        text = claim.get("text") or claim.get("claim")
        assert text, f"claim 应有 text 或 claim 字段: {claim}"
        assert "agent_role" in claim, f"claim 应有 agent_role 字段: {claim}"

    # 结论链增长
    assert len(state.conclusion_chain.conclusions) >= 2, "结论链应有 intra_team 步骤"


def test_full_six_stage_flow(client):
    """完整六阶段端到端（StubLLM 模式）

    验证：
    1. 最终状态为 stage=produce, status=done
    2. artifact 不为空
    3. 每阶段都有 confidence_flags
    4. conclusion_chain 长度为 6
    5. drift_log 非空
    """
    resp = client.post("/meetings", json={"topic": "完整六阶段测试"})
    meeting_id = resp.json()["meeting_id"]

    state = runner_mod.get_state(meeting_id)
    state.status = MeetingStatus.RUNNING
    state = asyncio.run(Runner().run(state))
    runner_mod.set_state(state)

    # 最终状态
    assert state.stage.value == "produce"
    assert state.status.value == "done"

    # 产出物
    assert state.artifact is not None
    assert "prd" in state.artifact or "code_analysis" in state.artifact

    # 置信度标记
    for stage in STAGE_ORDER:
        assert stage in state.confidence_flags, f"阶段 {stage} 缺少置信度标记"

    # 结论链
    assert len(state.conclusion_chain.conclusions) == 6, "结论链应为 6 步"

    # 漂移日志
    assert len(state.drift_log) > 0, "应有漂移检查记录"


def test_deliverable_type_selection(client):
    """不同 deliverable_type 产出不同类型 artifact"""
    for deliverable_type in ["prd_openapi", "code_analysis", "tested_system", "deployable_service"]:
        resp = client.post("/meetings", json={
            "topic": f"测试 {deliverable_type}",
            "deliverable_type": deliverable_type,
        })
        meeting_id = resp.json()["meeting_id"]

        state = runner_mod.get_state(meeting_id)
        state.status = MeetingStatus.RUNNING
        state = asyncio.run(Runner().run(state))

        assert state.status.value == "done", f"{deliverable_type} 应完成"
        assert state.artifact is not None, f"{deliverable_type} 应有产出"

        # 验证产出类型
        if deliverable_type == "prd_openapi":
            assert "prd" in state.artifact, "prd_openapi 应有 prd"
            assert "openapi" in state.artifact, "prd_openapi 应有 openapi"
        elif deliverable_type == "code_analysis":
            assert "code_analysis" in state.artifact, "code_analysis 应有 code_analysis"
        elif deliverable_type == "tested_system":
            assert "tested_system" in state.artifact, "tested_system 应有 tested_system"
        elif deliverable_type == "deployable_service":
            assert "deployable_service" in state.artifact, "deployable_service 应有 deployable_service"
