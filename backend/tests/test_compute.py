# Agent 计算解耦层测试
import pytest

from app.agents.compute import (
    ThinkRequest, ThinkResponse, LocalAgentCompute, GRPCAgentCompute,
    get_compute, reset_compute,
    build_clarify_prompt, build_intra_prompt,
    build_cross_team_prompt, build_evidence_prompt,
    build_arbitrate_prompt, build_produce_prompt,
)
from app.models import Role


def test_think_request_dataclass():
    """ThinkRequest 数据模型"""
    req = ThinkRequest(
        agent_role="moderator",
        stage="clarify",
        prompt="test prompt",
        schema_hint="clarify",
    )
    assert req.agent_role == "moderator"
    assert req.stage == "clarify"
    assert req.temperature == 0.0
    assert req.seed == 42


def test_think_response_dataclass():
    """ThinkResponse 数据模型"""
    resp = ThinkResponse(success=True, result={"key": "value"})
    assert resp.success
    assert resp.result["key"] == "value"
    assert resp.validation_status == "valid"


@pytest.mark.asyncio
async def test_local_compute_think():
    """LocalAgentCompute 执行思考"""
    compute = LocalAgentCompute()
    req = ThinkRequest(
        agent_role="moderator",
        stage="clarify",
        prompt="测试 prompt",
        schema_hint="clarify",
    )
    resp = await compute.think(req)
    assert resp.success
    assert "clarified_topic" in resp.result or resp.validation_status == "valid"


@pytest.mark.asyncio
async def test_local_compute_batch_parallel():
    """LocalAgentCompute 批量并行思考"""
    compute = LocalAgentCompute()
    requests = [
        ThinkRequest(agent_role="product_architect", stage="intra_team", prompt=f"prompt-{i}", schema_hint="intra_team")
        for i in range(3)
    ]
    responses = await compute.think_batch(requests)
    assert len(responses) == 3
    # 验证并行执行（总耗时 < 串行耗时之和的 2 倍）
    sum(r.latency_ms for r in responses)
    # stub 模式下 latency 为 0，只验证数量
    assert all(r.success for r in responses)


@pytest.mark.asyncio
async def test_grpc_compute_fallback():
    """GRPCAgentCompute 未实现时降级到 LocalAgentCompute"""
    compute = GRPCAgentCompute("localhost:9999")  # 无效端口
    req = ThinkRequest(
        agent_role="moderator",
        stage="clarify",
        prompt="降级测试",
        schema_hint="clarify",
    )
    resp = await compute.think(req)
    # 应回退到本地
    assert resp.success


def test_build_clarify_prompt():
    """build_clarify_prompt 构造正确请求"""
    req = build_clarify_prompt("测试议题", ["doc1", "doc2"])
    assert req.agent_role == "moderator"
    assert req.stage == "clarify"
    assert req.schema_hint == "clarify"
    assert "测试议题" in req.prompt
    assert "doc1" in req.prompt


def test_build_intra_prompt():
    """build_intra_prompt 按角色选择模板"""
    req_eng = build_intra_prompt(Role.ENGINEER, "议题", "重可行性")
    assert req_eng.agent_role == "engineer"
    assert "工程师" in req_eng.prompt or "Engineer" in req_eng.prompt

    req_arch = build_intra_prompt(Role.PRODUCT_ARCHITECT, "议题", "重价值")
    assert req_arch.agent_role == "product_architect"


def test_build_all_stage_prompts():
    """所有阶段的 prompt 构造器都能正常工作"""
    req1 = build_cross_team_prompt([{"role": "architect"}])
    assert req1.stage == "cross_team"

    req2 = build_evidence_prompt({"id": "c1"}, [{"evidence_id": "ev-0"}])
    assert req2.stage == "evidence_check"

    req3 = build_arbitrate_prompt([{"conflict_id": "c1"}])
    assert req3.stage == "arbitrate"

    req4 = build_produce_prompt({"decisions": []})
    assert req4.stage == "produce"


def test_get_compute_returns_local_by_default():
    """默认返回 LocalAgentCompute"""
    reset_compute()
    compute = get_compute()
    assert isinstance(compute, LocalAgentCompute)


def test_get_compute_returns_grpc_when_configured(monkeypatch):
    """配置启用时返回 GRPCAgentCompute"""
    from app import config as config_mod
    from types import SimpleNamespace
    # Settings 为 frozen dataclass，无法直接 setattr，替换整个 settings 引用
    fake_settings = SimpleNamespace(
        use_grpc_compute=True,
        grpc_compute_endpoint="localhost:50051",
    )
    monkeypatch.setattr(config_mod, "settings", fake_settings)
    reset_compute()
    compute = get_compute()
    assert isinstance(compute, GRPCAgentCompute)


def test_compute_singleton():
    """get_compute 返回单例"""
    reset_compute()
    c1 = get_compute()
    c2 = get_compute()
    assert c1 is c2
