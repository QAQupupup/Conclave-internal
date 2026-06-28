# Agent 计算抽象层：将"思考"与具体调用方式解耦
# 支持 LocalAgentCompute（进程内）和 GRPCAgentCompute（远程 Worker）

from __future__ import annotations
import asyncio
import inspect
import json
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

# 通过模块属性访问 get_llm，确保测试 monkeypatch（替换 llm_mod.get_llm）能生效；
# 若用 from app.agents.llm import get_llm 会在导入时绑定原始函数对象，monkeypatch 失效。
from app.agents import llm as _llm_mod
from app.agents.llm import LLMClient
from app.agents.prompts import (
    MODERATOR_CLARIFY, ARCHITECT_INTRA, ENGINEER_INTRA,
    CROSS_TEAM, EVIDENCE_CHECK, ARBITRATE, PRODUCE, render,
)
from app.models import Role

# IntraTeam 阶段的角色 → 模板注册表（Registry 模式）
# 消除 build_intra_prompt / build_intra_react_prompt 中的 if/elif 硬编码分派
# 新增角色只需在此注册，无需改业务逻辑（开闭原则）
_INTRA_TEAM_TEMPLATES: dict[Role, str] = {
    Role.ENGINEER: ENGINEER_INTRA,
    Role.PRODUCT_ARCHITECT: ARCHITECT_INTRA,
}


def _get_intra_template(role: Role) -> str:
    """取 IntraTeam 阶段的角色模板，未注册时回退到架构师模板"""
    return _INTRA_TEAM_TEMPLATES.get(role, ARCHITECT_INTRA)


@dataclass
class ThinkRequest:
    """Agent 思考请求（传输无关的纯数据模型）"""
    request_id: str = ""
    meeting_id: str = ""
    runner_session_id: str = ""
    agent_role: str = ""
    stage: str = ""
    prompt: str = ""
    schema_hint: str = ""
    temperature: float = 0.0
    seed: int = 42


@dataclass
class ThinkResponse:
    """Agent 思考响应"""
    success: bool = False
    result: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    latency_ms: int = 0
    validation_status: str = "valid"
    raw_response: str = ""


@runtime_checkable
class AgentCompute(Protocol):
    """Agent 计算协议：输入 ThinkRequest，返回 ThinkResponse

    实现可以是：
    - LocalAgentCompute：进程内直接调用 LLM
    - GRPCAgentCompute：通过 gRPC 调用远程 Worker
    """
    async def think(self, req: ThinkRequest) -> ThinkResponse: ...

    async def think_batch(self, requests: list[ThinkRequest]) -> list[ThinkResponse]:
        """批量并行思考（多角色同时）"""
        ...


class LocalAgentCompute:
    """本地计算实现：进程内直接调用 LLM

    保持与当前 Agent 类完全相同的行为。
    """

    def __init__(self) -> None:
        # 通过模块属性获取 LLM 客户端，支持测试 monkeypatch 替换 get_llm
        self._llm: LLMClient = _llm_mod.get_llm()

    async def think(self, req: ThinkRequest) -> ThinkResponse:
        import time
        t0 = time.monotonic()
        try:
            result = await self._llm.complete(req.prompt, schema_hint=req.schema_hint)
            return ThinkResponse(
                success=True,
                result=result,
                latency_ms=int((time.monotonic() - t0) * 1000),
                validation_status="valid",
            )
        except Exception as e:
            return ThinkResponse(
                success=False,
                error=f"{type(e).__name__}: {e}",
                latency_ms=int((time.monotonic() - t0) * 1000),
                validation_status="invalid",
            )

    async def think_batch(self, requests: list[ThinkRequest]) -> list[ThinkResponse]:
        """并行执行多个思考请求（asyncio.gather）"""
        tasks = [self.think(req) for req in requests]
        return await asyncio.gather(*tasks)

    async def aclose(self) -> None:
        """关闭底层 LLM 客户端的连接池（RealLLM 的 httpx.AsyncClient）"""
        close_fn = getattr(self._llm, "aclose", None)
        if close_fn and inspect.iscoroutinefunction(close_fn):
            await close_fn()


class GRPCAgentCompute:
    """gRPC 远程计算实现：调用独立 Worker 进程

    Worker 可以部署在多台机器上，实现横向扩展。
    当前为 stub 实现（gRPC 未安装时降级到 LocalAgentCompute）。
    """

    def __init__(self, endpoint: str = "localhost:50051") -> None:
        self._endpoint = endpoint
        self._channel = None
        self._stub = None
        self._fallback = LocalAgentCompute()  # 降级

    async def think(self, req: ThinkRequest) -> ThinkResponse:
        try:
            # TODO: 实现 gRPC 远程调用
            # from grpc import aio as grpc_aio
            # import agent_compute_pb2, agent_compute_pb2_grpc
            # if self._channel is None:
            #     self._channel = grpc_aio.insecure_channel(self._endpoint)
            #     self._stub = agent_compute_pb2_grpc.AgentComputeServiceStub(self._channel)
            # grpc_req = agent_compute_pb2.ThinkRequest(
            #     request_id=req.request_id, ...
            # )
            # resp = await self._stub.Think(grpc_req)
            # return ThinkResponse(success=resp.success, result=json.loads(resp.result_json), ...)

            # 当前降级到本地
            return await self._fallback.think(req)
        except Exception as e:
            # gRPC 调用失败，降级到本地
            return await self._fallback.think(req)

    async def think_batch(self, requests: list[ThinkRequest]) -> list[ThinkResponse]:
        try:
            # TODO: 使用 gRPC 双向流批量发送
            # 当前降级到本地并行
            return await self._fallback.think_batch(requests)
        except Exception:
            return await self._fallback.think_batch(requests)


# ---------- Prompt 构造器（从 Agent 方法提取） ----------
# 保持记忆画像注入：在 build_xxx_prompt 中注入 profile_anchor。
# 注入顺序与原 Agent 一致：
#   render(template) -> inject_profile（画像锚点）-> 拼接 anchor（宪章+已锁定结论）
# 最终 prompt 结构：[anchor]\n\n[profile_anchor]\n\n[rendered_template]


def _inject_profile(prompt: str, agent_role: str) -> str:
    """注入角色画像锚点到 prompt 前（无画像时原样返回）

    复用 app.memory.profile.inject_profile，保持与原 Agent._inject_profile 行为一致。
    记忆子系统失败时不影响主流程。
    """
    try:
        from app.memory.profile import inject_profile
        return inject_profile(prompt, agent_role)
    except Exception:
        return prompt


def build_clarify_prompt(topic: str, doc_summaries: list[str], anchor: str = "") -> ThinkRequest:
    """构造 clarify 阶段的思考请求"""
    prompt = render(MODERATOR_CLARIFY, topic=topic, doc_summaries="; ".join(doc_summaries) if doc_summaries else "无")
    prompt = _inject_profile(prompt, Role.MODERATOR.value)
    if anchor:
        prompt = f"{anchor}\n\n{prompt}"
    return ThinkRequest(
        agent_role=Role.MODERATOR.value,
        stage="clarify",
        prompt=prompt,
        schema_hint="clarify",
    )


def build_intra_prompt(role: Role, clarified_topic: str, stance: str, anchor: str = "") -> ThinkRequest:
    """构造 intra_team 阶段的思考请求"""
    template = _get_intra_template(role)
    prompt = render(template, clarified_topic=clarified_topic, stance=stance)
    prompt = _inject_profile(prompt, role.value)
    if anchor:
        prompt = f"{anchor}\n\n{prompt}"
    return ThinkRequest(
        agent_role=role.value,
        stage="intra_team",
        prompt=prompt,
        schema_hint="intra_team",
    )


def build_intra_react_prompt(
    role: Role,
    clarified_topic: str,
    stance: str,
    prior_conclusions: list[dict],
    anchor: str = "",
) -> ThinkRequest:
    """构造 intra_team 阶段的反应性思考请求（混合模式专用）

    与 build_intra_prompt 的区别：prompt 中注入了前序角色的结论，
    让当前角色可以看到其他人的观点并做出反应，提升辩论质量。

    prior_conclusions: 前序角色的结论列表 [{"role": "...", "stance": "...", "claims": [...]}]
    """
    template = _get_intra_template(role)
    # 构造前序结论摘要
    prior_summary = ""
    if prior_conclusions:
        parts = []
        for pc in prior_conclusions:
            role_name = pc.get("role", "未知角色")
            claims_text = json.dumps(pc.get("claims", []), ensure_ascii=False)
            parts.append(f"【{role_name}的论点】{claims_text}")
        prior_summary = (
            "\n\n【前序发言参考】\n"
            "以下是其他角色已发表的论点，请在你的分析中参考并考虑是否认同或反驳：\n"
            + "\n".join(parts)
            + "\n\n请基于上述参考，结合你的专业视角发表论点。"
        )
    prompt = render(template, clarified_topic=clarified_topic, stance=stance)
    # 在模板渲染后注入前序结论
    if prior_summary:
        prompt = prompt + prior_summary
    prompt = _inject_profile(prompt, role.value)
    if anchor:
        prompt = f"{anchor}\n\n{prompt}"
    return ThinkRequest(
        agent_role=role.value,
        stage="intra_team",
        prompt=prompt,
        schema_hint="intra_team",
    )


def build_cross_team_prompt(team_conclusions: list[dict], anchor: str = "") -> ThinkRequest:
    prompt = render(CROSS_TEAM, team_conclusions=str(team_conclusions))
    prompt = _inject_profile(prompt, Role.MODERATOR.value)
    if anchor:
        prompt = f"{anchor}\n\n{prompt}"
    return ThinkRequest(
        agent_role=Role.MODERATOR.value,
        stage="cross_team",
        prompt=prompt,
        schema_hint="cross_team",
    )


def build_evidence_prompt(conflict: dict, evidence_chunks: list[dict], anchor: str = "") -> ThinkRequest:
    prompt = render(EVIDENCE_CHECK, conflict=str(conflict), evidence_chunks=str(evidence_chunks))
    prompt = _inject_profile(prompt, Role.MODERATOR.value)
    if anchor:
        prompt = f"{anchor}\n\n{prompt}"
    return ThinkRequest(
        agent_role=Role.MODERATOR.value,
        stage="evidence_check",
        prompt=prompt,
        schema_hint="evidence_check",
    )


def build_arbitrate_prompt(evidence_set: list[dict], anchor: str = "") -> ThinkRequest:
    prompt = render(ARBITRATE, evidence_set=str(evidence_set))
    prompt = _inject_profile(prompt, Role.MODERATOR.value)
    if anchor:
        prompt = f"{anchor}\n\n{prompt}"
    return ThinkRequest(
        agent_role=Role.MODERATOR.value,
        stage="arbitrate",
        prompt=prompt,
        schema_hint="arbitrate",
    )


def build_produce_prompt(decision_record: dict, anchor: str = "", template: str | None = None) -> ThinkRequest:
    if template is None:
        template = PRODUCE
    prompt = render(template, decision_record=str(decision_record))
    prompt = _inject_profile(prompt, Role.MODERATOR.value)
    if anchor:
        prompt = f"{anchor}\n\n{prompt}"
    return ThinkRequest(
        agent_role=Role.MODERATOR.value,
        stage="produce",
        prompt=prompt,
        schema_hint="produce",
    )


# ---------- 全局计算实例 ----------

_compute: AgentCompute | None = None


def get_compute() -> AgentCompute:
    """获取全局 Agent 计算实例（按配置选择 Local 或 gRPC）"""
    global _compute
    if _compute is None:
        from app.config import settings
        if settings.use_grpc_compute:
            _compute = GRPCAgentCompute(settings.grpc_compute_endpoint)
        else:
            _compute = LocalAgentCompute()
    return _compute


def reset_compute() -> None:
    """重置计算实例（测试用，同步）

    注意：StubLLM 模式下无连接池需关闭。
    RealLLM 模式下 httpx.AsyncClient 未关闭可能导致事件循环挂起，
    真实 LLM 脚本应调用 shutdown_compute() 代替。
    """
    global _compute
    _compute = None


async def shutdown_compute() -> None:
    """异步关闭计算实例并释放连接池（真实 LLM 脚本必须调用）

    先关闭底层 httpx.AsyncClient，再清空全局引用，
    防止 asyncio.run() 关闭事件循环时因未关闭的连接池挂起。
    """
    global _compute
    if _compute is not None:
        close_fn = getattr(_compute, "aclose", None)
        if close_fn and inspect.iscoroutinefunction(close_fn):
            await close_fn()
    _compute = None
