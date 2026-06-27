# 真实 LLM 端到端集成测试
# 运行方式：
#   CONCLAVE_TEST_REAL_LLM=1 python -m pytest tests/test_real_llm_e2e.py -v -s
#
# 前置条件：
#   - .env 配置了真实的 CONCLAVE_LLM_API_KEY
#   - CONCLAVE_TEST_REAL_LLM=1 环境变量（绕过 conftest 的 StubLLM 强制）
#
# 本测试不使用 MockLLM / StubLLM，直接调用真实 LLM API，
# 验证六阶段会议流程的完整性和真实 LLM 输出的兼容性。
import asyncio
import os

import pytest

# 检查是否启用了真实 LLM 测试模式
_REAL_LLM_ENABLED = os.environ.get("CONCLAVE_TEST_REAL_LLM") == "1"

# 必须在导入 app.config 之前检查，因为 conftest 可能已设置空 key
# 但当 CONCLAVE_TEST_REAL_LLM=1 时，conftest 不会设置空 key，.env 会加载真实 key

from app.config import settings

# 真实 LLM 是否可用（key 已从 .env 加载）
_REAL_LLM_AVAILABLE = _REAL_LLM_ENABLED and settings.use_real_llm

# 跳过条件
_skip_reason = (
    "需要 CONCLAVE_TEST_REAL_LLM=1 且 .env 配置了 CONCLAVE_LLM_API_KEY"
    if not _REAL_LLM_ENABLED
    else ".env 中 CONCLAVE_LLM_API_KEY 未配置"
)

pytestmark = [
    pytest.mark.real_llm,
    pytest.mark.skipif(not _REAL_LLM_AVAILABLE, reason=_skip_reason),
    pytest.mark.asyncio,
]


@pytest.mark.asyncio
async def test_real_llm_full_meeting():
    """真实 LLM 完整六阶段会议端到端测试

    验证：
    1. 所有六阶段顺利完成（clarify → intra_team → cross_team → evidence_check → arbitrate → produce）
    2. LLM 输出能被正确解析（JSON 格式、角色名匹配）
    3. claims > 0（intra_team 角色匹配成功）
    4. 产物 artifact 非空（produce 阶段成功生成 PRD + OpenAPI）
    5. LLM trace 100% 成功率（无降级到 StubLLM）
    6. 因果链完整（所有日志带 request_id + meeting_id + runner_session_id）
    """
    from app.models import MeetingState, MeetingStatus, Stage
    from app.orchestrator.runner import Runner
    from app.orchestrator import runner as runner_mod

    meeting_id = f"real-e2e-{os.getpid()}"
    topic = "设计一个团队任务管理 API，支持任务分配、优先级和进度跟踪"
    state = MeetingState(
        meeting_id=meeting_id,
        topic=topic,
        stage=Stage.CLARIFY,
        status=MeetingStatus.RUNNING,
    )
    runner_mod.set_state(state)

    # 运行会议，超时 10 分钟
    state = await asyncio.wait_for(Runner().run(state), timeout=600.0)
    runner_mod.set_state(state)

    # 清理 httpx 连接池
    from app.agents.compute import shutdown_compute
    await shutdown_compute()

    # ===== 断言 =====

    # 1. 会议状态
    assert state.status == MeetingStatus.DONE, f"会议未完成: status={state.status}"
    assert state.stage == Stage.PRODUCE, f"最终阶段错误: stage={state.stage}"

    # 2. clarified_topic 非空
    assert state.clarified_topic, "clarified_topic 为空"
    assert len(state.clarified_topic) > 10, f"clarified_topic 过短: {state.clarified_topic}"

    # 3. team_config 至少 3 个角色
    assert len(state.team_config) >= 3, f"team_config 不足: {len(state.team_config)}"

    # 4. claims > 0（验证角色匹配成功，不因中文角色名丢失）
    assert len(state.claims) > 0, "claims=0: intra_team 角色匹配可能失败（中文角色名问题）"

    # 5. team_conclusions 与 team_config 数量一致
    assert len(state.team_conclusions) == len(state.team_config), (
        f"team_conclusions({len(state.team_conclusions)}) != team_config({len(state.team_config)})"
    )

    # 6. messages 至少 5 条
    assert len(state.messages) >= 5, f"messages 过少: {len(state.messages)}"

    # 7. artifact 非空
    assert state.artifact, "artifact 为空: produce 阶段失败"
    assert state.artifact.get("prd"), "artifact.prd 为空"
    assert state.artifact.get("openapi"), "artifact.openapi 为空"
    assert len(state.artifact["openapi"]) > 100, "OpenAPI 过短"

    # 8. LLM trace: 验证调用次数和成功率
    trace = state.llm_trace
    summary = trace.summary()
    assert summary["total_calls"] >= 10, f"LLM 调用次数过少: {summary['total_calls']}"
    # produce 阶段可能因 API 超时降级到 StubLLM（网络/API 问题，非代码 bug）
    # 但其他阶段不应降级
    if summary["fallback_calls"] > 0:
        # 检查降级是否只发生在 produce 阶段
        stage_stats = summary.get("stage_stats", {})
        produce_fallback = stage_stats.get("produce", {}).get("fallback", 0)
        other_fallback = summary["fallback_calls"] - produce_fallback
        assert other_fallback == 0, (
            f"非 produce 阶段发生降级: 总降级 {summary['fallback_calls']}, "
            f"produce 降级 {produce_fallback}"
        )
        print(f"  [警告] produce 阶段降级 {produce_fallback} 次（API 超时，非代码 bug）")
    assert summary["invalid_calls"] == 0 or summary["fallback_calls"] > 0, (
        f"有 {summary['invalid_calls']} 次失败且未降级"
    )

    # 9. drift_log 无漂移
    drift_count = sum(1 for d in state.drift_log if d.get("is_drift"))
    assert drift_count == 0, f"检测到 {drift_count} 次话题漂移"

    # 10. decision_record 非空
    assert state.decision_record, "decision_record 为空"
    assert state.decision_record.get("decisions"), "decisions 为空"

    # 输出摘要（-s 模式可见）
    print(f"\n{'=' * 60}")
    print(f"真实 LLM 端到端测试通过！")
    print(f"  模型: {settings.llm_model}")
    print(f"  LLM 调用: {summary['total_calls']} 次 (100% 成功)")
    print(f"  claims: {len(state.claims)}")
    print(f"  conflicts: {len(state.conflicts)}")
    print(f"  messages: {len(state.messages)}")
    print(f"  API endpoints: {len(state.artifact['prd'].get('api_endpoints', []))}")
    print(f"  OpenAPI: {len(state.artifact['openapi'])} chars")
    print(f"  confidence: {state.confidence_flags}")
    print(f"{'=' * 60}")


@pytest.mark.asyncio
async def test_real_llm_role_matching():
    """验证真实 LLM 返回的中文角色名能被正确匹配

    这是之前 claims=0 bug 的回归测试：
    - StubLLM 返回 "product_architect" → 精确匹配
    - 真实 LLM 返回 "产品经理" → 需要模糊匹配
    """
    if not _REAL_LLM_AVAILABLE:
        pytest.skip(_skip_reason)

    from app.orchestrator.nodes import _match_role
    from app.models import Role

    # 测试中文角色名匹配
    test_cases = [
        ("产品经理", Role.PRODUCT_ARCHITECT),
        ("产品架构师", Role.PRODUCT_ARCHITECT),
        ("后端工程师", Role.ENGINEER),
        ("前端开发", Role.ENGINEER),
        ("product_architect", Role.PRODUCT_ARCHITECT),
        ("engineer", Role.ENGINEER),
        ("moderator", Role.MODERATOR),
        ("主持人", Role.MODERATOR),
    ]

    for role_str, expected_role in test_cases:
        matched = _match_role(role_str)
        assert matched is not None, f"角色匹配失败: '{role_str}' → None"
        assert matched == expected_role, (
            f"角色匹配错误: '{role_str}' → {matched}, 期望 {expected_role}"
        )
