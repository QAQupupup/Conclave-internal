"""验证 eval 框架流程：数据加载 + 参数构建 + 评分逻辑 + 结果汇总

不依赖真实 LLM，使用 mock 会议详情数据模拟 StubLLM 产出。
运行方式：cd backend && python -m eval.verify_eval_framework
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# 确保可以导入 eval 模块
EVAL_ROOT = Path(__file__).resolve().parent
DATASET_DIR = EVAL_ROOT / "dataset"
sys.path.insert(0, str(EVAL_ROOT.parent))

from eval.models import CaseResult  # noqa: E402
from eval.run import load_cases  # noqa: E402
from eval.runners.case_runner import CaseRunner  # noqa: E402
from eval.runners.suite_runner import SuiteRunner  # noqa: E402


def test_case_loading():
    """验证 Tier1 测试用例加载"""
    print("=" * 60)
    print("[1] 测试用例加载")
    print("=" * 60)
    cases = load_cases(1)
    assert len(cases) > 0, "Tier1 测试用例为空"
    print(f"  加载 {len(cases)} 个 Tier1 用例")

    required_fields = {"case_id", "topic", "config", "expected", "terminal_state"}
    for case in cases:
        missing = required_fields - set(case.keys())
        assert not missing, f"用例 {case.get('case_id', '?')} 缺少字段: {missing}"
        # 验证 expected 包含至少 3 个阶段
        assert len(case["expected"]) >= 3, f"用例 {case['case_id']} expected 阶段不足 3 个"
        # 验证 terminal_state
        ts = case["terminal_state"]
        assert ts["status"] == "done", f"用例 {case['case_id']} 终态 status 非 done"
        assert ts["stage"] == "produce", f"用例 {case['case_id']} 终态 stage 非 produce"

    print("  所有用例结构验证通过（case_id / topic / config / expected / terminal_state）")
    return cases


def test_param_building(cases):
    """验证会议参数构建"""
    print("\n" + "=" * 60)
    print("[2] 会议参数构建")
    print("=" * 60)
    runner = CaseRunner("http://localhost:8000", "fake-token")
    for case in cases:
        params = runner._build_meeting_params(case)
        assert params["topic"] == case["topic"], f"topic 不匹配: {case['case_id']}"
        assert "deliverable_type" in params
        assert "flow_plan" in params
        assert "debate_depth" in params
        print(
            f"  {case['case_id']}: topic={params['topic'][:30]}... "
            f"deliverable={params['deliverable_type']} flow={params['flow_plan']}"
        )
    print("  所有用例参数构建验证通过")
    return runner


def _make_mock_detail(case: dict) -> dict:
    """构造 mock 会议详情，模拟 StubLLM 完成后的产出"""
    expected = case.get("expected", {})
    clarify_exp = expected.get("clarify", {})
    intra_exp = expected.get("intra_team", {})
    cross_exp = expected.get("cross_team", {})
    arbitrate_exp = expected.get("arbitrate", {})
    produce_exp = expected.get("produce", {})

    # 构造 claims — 覆盖所有 expected_claim_types
    expected_claim_types = intra_exp.get("expected_claim_types", ["fact"])
    num_claims = max(len(expected_claim_types), intra_exp.get("min_claims", 2))
    claims = []
    for i in range(num_claims):
        claims.append(
            {
                "claim_id": f"claim-{i:04d}",
                "role": "engineer",
                "text": f"Claim {i}: 这是一个技术主张",
                "type": expected_claim_types[i % len(expected_claim_types)],
            }
        )

    # 构造 conflicts — 覆盖所有 expected_conflict_types
    expected_conflict_types = cross_exp.get("expected_conflict_types", ["preference"])
    num_conflicts = max(len(expected_conflict_types), cross_exp.get("min_conflicts", 1))
    max_conflicts = cross_exp.get("max_conflicts", 99)
    num_conflicts = min(num_conflicts, max_conflicts)
    conflicts = []
    for i in range(num_conflicts):
        conflicts.append(
            {
                "conflict_id": f"conf-{i:04d}",
                "type": expected_conflict_types[i % len(expected_conflict_types)],
                "summary": f"Conflict {i}: 角色间观点冲突",
            }
        )

    # 构造 decisions — 数量 >= conflicts 数量
    num_decisions = max(len(conflicts), arbitrate_exp.get("min_decisions", 1))
    decisions = []
    for i in range(num_decisions):
        decisions.append(
            {
                "conflict_id": f"conf-{i:04d}",
                "decision": "采纳方案 A",
                "rationale": "x" * max(20, arbitrate_exp.get("min_rationale_length", 20)),
            }
        )

    # 构造 artifact — 根据 deliverable_type 构造不同产出
    cfg = case.get("config") or {}
    deliverable_type = cfg.get("deliverable_type", "prd_openapi")

    # 构造 team_config
    expected_roles = clarify_exp.get("expected_roles", ["product_architect", "engineer", "security_expert"])
    team_config = [{"role": r, "stance": "neutral"} for r in expected_roles]

    artifact: dict = {"meeting_id": "mtg-mock-0000", "deliverable_type": deliverable_type}

    if deliverable_type in ("design_doc", "comprehensive", "research_report", "business_report"):
        # 文档类产出
        must_have_doc = produce_exp.get("must_have_doc_fields", ["title", "summary"])
        doc_content: dict = {}
        for field in must_have_doc:
            if field in ("findings", "recommendations", "requirements", "api_endpoints"):
                doc_content[field] = [f"{field} 项 {i + 1}: 详细内容描述" for i in range(3)]
            else:
                doc_content[field] = f"{field} 的详细内容描述，长度超过五十个字符以确保内容深度评估通过"
        # 补充额外字段确保内容深度
        for extra in ["overview", "analysis", "architecture", "tech_stack"]:
            if extra not in doc_content:
                doc_content[extra] = f"额外字段 {extra} 的详细描述内容，用于补充文档完整性"
        artifact[deliverable_type] = doc_content
    else:
        # prd_openapi 及其他类型
        must_have = produce_exp.get("must_have_prd_fields", ["title", "goal", "scope"])
        prd = {field: f"值_{field}" for field in must_have}
        prd["api_endpoints"] = [
            {"method": "GET", "path": "/api/users"},
            {"method": "POST", "path": "/api/users"},
        ] * max(1, produce_exp.get("min_api_endpoints", 2) // 2 + 1)
        openapi_str = "openapi: 3.0.0\n" + "x" * max(100, produce_exp.get("min_openapi_length", 100))
        artifact["prd"] = prd
        artifact["openapi"] = openapi_str

    return {
        "meeting_id": "mtg-mock-0000",
        "topic": case.get("topic", ""),
        "stage": "produce",
        "status": "done",
        "deliverable_type": deliverable_type,
        "config": cfg,
        "clarified_topic": "这是一个已澄清的议题描述，长度大于十个字符",
        "key_questions": [f"问题 {i + 1}" for i in range(max(2, clarify_exp.get("min_key_questions", 2)))],
        "team_config": team_config,
        "claims": claims,
        "conflicts": conflicts,
        "evidence_set": [{"assessments": [{"claim_id": "claim-0000", "verdict": "supported"}]}],
        "decision_record": {"decisions": decisions},
        "artifact": artifact,
        "messages": [{"role": "moderator", "text": f"消息 {i}"} for i in range(10)],
        "llm_trace": {"total_tokens": 5000, "fallback_calls": 0, "invalid_calls": 0},
        "confidence_flags": {"clarify": "high", "intra_team": "medium", "cross_team": "high"},
    }


async def test_grading(cases, runner: CaseRunner):
    """验证评分逻辑（使用 mock 会议详情）"""
    print("\n" + "=" * 60)
    print("[3] 评分逻辑验证（mock 数据）")
    print("=" * 60)
    all_passed = True
    for case in cases:
        mock_detail = _make_mock_detail(case)
        stage_scores = await runner._grade_all_stages(case, mock_detail)

        # 检查终端状态
        errors: list[str] = []
        runner._check_terminal_state(case, mock_detail, errors)

        case_passed = not errors and bool(stage_scores) and all(v >= 0.6 for v in stage_scores.values())
        status = "PASS" if case_passed else "FAIL"
        if not case_passed:
            all_passed = False
        scores_str = ", ".join(f"{k}={v:.2f}" for k, v in sorted(stage_scores.items()))
        print(f"  [{status}] {case['case_id']}: {scores_str}")
        if errors:
            print(f"         errors: {errors}")

        # 验证每个 expected 阶段都有评分
        for stage in case.get("expected", {}):
            assert stage in stage_scores, f"用例 {case['case_id']} 阶段 {stage} 未评分"

    assert all_passed, "部分用例评分未通过"
    print("\n  所有用例评分验证通过（6 阶段全覆盖，分数 >= 0.6）")


def test_suite_result_building(cases):
    """验证 SuiteResult 汇总逻辑"""
    print("\n" + "=" * 60)
    print("[4] SuiteResult 汇总逻辑")
    print("=" * 60)

    # 构造 mock CaseResult 列表
    mock_results: list[CaseResult] = []
    for case in cases:
        for run_idx in range(2):  # pass_k=2
            mock_results.append(
                CaseResult(
                    case_id=case["case_id"],
                    tier=1,
                    passed=True,
                    stage_scores={
                        "clarify": 1.0,
                        "intra_team": 1.0,
                        "cross_team": 1.0,
                        "evidence_check": 1.0,
                        "arbitrate": 1.0,
                        "produce": 1.0,
                    },
                    total_tokens=5000,
                    latency_ms=30000.0,
                    errors=[],
                    run_index=run_idx,
                )
            )

    # 使用 SuiteRunner 的 _build_suite_result
    config = {
        "service": {"base_url": "http://localhost:8000", "admin_username": "admin", "admin_password": "admin123"},
        "execution": {"pass_k": 2, "max_concurrent": 1},
    }
    suite = SuiteRunner(config)
    result = suite._build_suite_result(mock_results, cases, k=2)

    print(f"  total_cases:  {result.total_cases}")
    print(f"  pass1:        {result.pass1:.3f}")
    print(f"  pass1_ci:     [{result.pass1_ci[0]:.3f}, {result.pass1_ci[1]:.3f}]")
    print(f"  pass3:        {result.pass3:.3f}")
    print(f"  avg_score:    {result.avg_score:.3f}")
    print(f"  total_tokens: {result.total_tokens}")
    print(f"  p50_latency:  {result.p50_latency_ms:.0f}ms")
    print(f"  p95_latency:  {result.p95_latency_ms:.0f}ms")
    print(f"  unstable:     {result.unstable_cases}")
    print("  stage_breakdown:")
    for stage, rate in sorted(result.stage_breakdown.items()):
        print(f"    {stage:<16} {rate:.3f}")

    assert result.total_cases == len(cases), f"total_cases 不匹配: {result.total_cases} != {len(cases)}"
    assert result.pass1 == 1.0, f"pass1 应为 1.0: {result.pass1}"
    assert result.total_tokens == 5000 * len(cases) * 2
    print("\n  SuiteResult 汇总验证通过")


async def main():
    print("\nConclave Eval Framework 验证（StubLLM mock 模式）\n")

    # 1. 加载测试用例
    cases = test_case_loading()

    # 2. 验证参数构建
    runner = test_param_building(cases)

    # 3. 验证评分逻辑
    await test_grading(cases, runner)

    # 4. 验证汇总逻辑
    test_suite_result_building(cases)

    print("\n" + "=" * 60)
    print("全部验证通过！eval 框架流程完整可用。")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
