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
    ARBITRATE,
    ARCHITECT_INTRA,
    CROSS_TEAM,
    ENGINEER_INTRA,
    EVIDENCE_CHECK,
    MODERATOR_CLARIFY,
    PRODUCE,
    render,
)
from app.agents.role_templates import ROLE_LIBRARY
from app.logging_config import get_logger
from app.models import Role

# IntraTeam 阶段的角色 → 模板注册表（Registry 模式）
# 消除 build_intra_prompt / build_intra_react_prompt 中的 if/elif 硬编码分派
# 新增角色只需在此注册，无需改业务逻辑（开闭原则）
_INTRA_TEAM_TEMPLATES: dict[Role, str] = {
    Role.ENGINEER: ENGINEER_INTRA,
    Role.PRODUCT_ARCHITECT: ARCHITECT_INTRA,
}

# Role 枚举值 → ROLE_LIBRARY key 映射
_ROLE_KEY_MAP: dict[str, str] = {
    "moderator": "moderator",
    "product_architect": "product_architect",
    "engineer": "engineer",
    "security_expert": "security_expert",
    "data_engineer": "data_engineer",
    "ux_designer": "ux_designer",
}


def _get_role_persona(role_value: str) -> str:
    """从 ROLE_LIBRARY 取角色画像文本（单一数据源）

    角色画像（视角+决策偏置）只在 role_templates.py 维护一份，
    prompts.py 模板通过 {role_persona} 占位符动态注入。
    """
    key = _ROLE_KEY_MAP.get(role_value, role_value)
    template = ROLE_LIBRARY.get(key)
    if template is not None:
        return template.prompt_template
    return f"你是{role_value}专家。"


def _get_intra_template(role: Role) -> str:
    """取 IntraTeam 阶段的角色模板，未注册时回退到架构师模板"""
    return _INTRA_TEAM_TEMPLATES.get(role, ARCHITECT_INTRA)


@dataclass
class ToolCall:
    """Agent 请求执行的工具调用"""

    tool_name: str = ""  # "web_search" | "browser.goto" | "browser.click" | ...
    arguments: dict[str, Any] = field(default_factory=dict)  # 工具参数
    reason: str = ""  # Agent 为什么调用此工具（可读性 + 调试）


@dataclass
class ToolResult:
    """工具调用的执行结果"""

    tool_name: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)
    success: bool = True
    result: Any = None  # 工具返回值
    error: str = ""
    latency_ms: int = 0
    iteration: int = 0  # 第几轮 ReAct 迭代


@dataclass
class ThinkRequest:
    """Agent 思考请求（传输无关的纯数据模型）

    ReAct 扩展（Phase B）：
    - available_tools: Agent 可调用的工具列表
    - tool_history: 前序迭代的工具调用结果（经裁剪）
    - iteration: 当前 ReAct 迭代序号（0 = 首轮）
    非 ReAct 模式下这三个字段为空/0，行为与原来一致。
    """

    request_id: str = ""
    meeting_id: str = ""
    runner_session_id: str = ""
    agent_role: str = ""
    stage: str = ""
    prompt: str = ""
    schema_hint: str = ""
    temperature: float = 0.0
    seed: int = 42
    model: str = ""  # per-role/stage 模型覆盖（空=继承会议级配置）
    # ReAct 扩展
    available_tools: list[dict[str, Any]] = field(default_factory=list)  # [{name, description, parameters}]
    tool_history: list[ToolResult] = field(default_factory=list)
    iteration: int = 0


@dataclass
class ThinkResponse:
    """Agent 思考响应

    ReAct 扩展（Phase B）：
    - tool_calls: Agent 请求执行的工具调用列表
    - need_continue: Agent 是否需要继续 ReAct 循环
    - input_tokens / output_tokens: token 用量（成本追踪）
    非 ReAct 模式下 tool_calls 为空，need_continue 为 False。
    """

    success: bool = False
    result: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    latency_ms: int = 0
    validation_status: str = "valid"
    raw_response: str = ""
    # ReAct 扩展
    tool_calls: list[ToolCall] = field(default_factory=list)
    need_continue: bool = False
    input_tokens: int = 0
    output_tokens: int = 0


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

        from app.context import reset_agent_role, set_agent_role

        # 设置 agent_role 上下文（trace/cost/logging 自动注入）
        role_token = set_agent_role(req.agent_role) if req.agent_role else None
        t0 = time.monotonic()
        try:
            result = await self._llm.complete(
                req.prompt,
                schema_hint=req.schema_hint,
                model_override=req.model or "",
                agent_role=req.agent_role or "",
            )

            # ReAct 模式：从 result 中提取 tool_calls 和 need_continue
            tool_calls: list[ToolCall] = []
            need_continue = False
            if req.available_tools and isinstance(result, dict):
                need_continue = bool(result.pop("need_continue", False))
                raw_calls = result.pop("tool_calls", [])
                if isinstance(raw_calls, list):
                    for call in raw_calls:
                        if isinstance(call, dict):
                            tool_calls.append(
                                ToolCall(
                                    tool_name=call.get("tool_name", ""),
                                    arguments=call.get("arguments", {}),
                                    reason=call.get("reason", ""),
                                )
                            )

            return ThinkResponse(
                success=True,
                result=result,
                latency_ms=int((time.monotonic() - t0) * 1000),
                validation_status="valid",
                tool_calls=tool_calls,
                need_continue=need_continue,
            )
        except Exception as e:
            error_msg = f"{type(e).__name__}: {e}"
            get_logger("agents.compute").warning(
                f"compute.think 异常: stage={req.stage}, model={req.model or 'default'}, error={error_msg}",
                extra={
                    "stage": req.stage,
                    "meeting_id": req.meeting_id,
                    "agent_role": req.agent_role,
                    "model": req.model,
                    "error": error_msg,
                },
            )
            return ThinkResponse(
                success=False,
                error=error_msg,
                latency_ms=int((time.monotonic() - t0) * 1000),
                validation_status="invalid",
            )
        finally:
            # 恢复 agent_role 上下文
            if role_token is not None:
                reset_agent_role(role_token)

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
        except Exception:
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


def _inject_tools_to_prompt(prompt: str, available_tools: list[dict[str, Any]]) -> str:
    """将可用工具描述注入到 prompt 中，让 LLM 知道可以调用哪些工具

    工具描述格式（Function Calling 兼容）：
        【可用工具】
        1. tool_name: description
           参数: param1 (type), param2 (type)
        2. ...

    输出要求：
        - 如果当前信息不足以完成任务，设置 need_continue=true 并返回 tool_calls
        - tool_calls 格式: [{"tool_name": "...", "arguments": {...}, "reason": "..."}]
        - 如果任务完成，设置 need_continue=false
    """
    if not available_tools:
        return prompt

    tool_lines = ["\n\n【可用工具 - 你可以调用以下工具获取信息】"]
    for i, tool in enumerate(available_tools, 1):
        params = ", ".join(f"{k}: {v}" for k, v in tool.get("parameters", {}).items())
        tool_lines.append(f"{i}. {tool['name']}: {tool['description']}\n   参数: {params if params else '无'}")

    tool_lines.append(
        "\n【工具调用规则】\n"
        "如果你需要调用工具获取信息，请在 JSON 输出中设置：\n"
        '  "need_continue": true,\n'
        '  "tool_calls": [{"tool_name": "工具名", "arguments": {参数}, "reason": "调用原因"}]\n'
        "如果你已有足够信息，设置 need_continue=false 并给出最终结论。\n"
        "工具调用结果会在下一轮对话中提供给你。"
    )
    return prompt + "\n".join(tool_lines)


def _inject_skills(prompt: str, stage: str, deliverable_type: str = "", role: str = "", complexity: str = "") -> str:
    """在prompt末尾注入匹配的Skill内容（动态加载设计规范/代码规范/沟通风格等）"""
    try:
        from app.agents.skills import format_skills_for_prompt

        skills_text = format_skills_for_prompt(
            stage=stage,
            deliverable_type=deliverable_type,
            role=role,
            complexity=complexity,
        )
        if skills_text:
            return f"{prompt}\n\n{skills_text}"
    except Exception:
        pass  # Skill加载失败不影响主流程
    return prompt


def build_clarify_prompt(
    topic: str,
    doc_summaries: list[str],
    anchor: str = "",
    available_tools: list[dict[str, Any]] | None = None,
    reference_context: str = "",
) -> ThinkRequest:
    """构造 clarify 阶段的思考请求"""
    prompt = render(MODERATOR_CLARIFY, topic=topic, doc_summaries="; ".join(doc_summaries) if doc_summaries else "无")
    prompt = _inject_profile(prompt, Role.MODERATOR.value)
    prompt = _inject_skills(prompt, stage="clarify", role=Role.MODERATOR.value)
    if available_tools:
        prompt = _inject_tools_to_prompt(prompt, available_tools)
    if reference_context:
        prompt = reference_context + "\n\n" + prompt
    if anchor:
        prompt = f"{anchor}\n\n{prompt}"
    return ThinkRequest(
        agent_role=Role.MODERATOR.value,
        stage="clarify",
        prompt=prompt,
        schema_hint="clarify",
        available_tools=available_tools or [],
    )


def build_intra_prompt(role: Role, clarified_topic: str, stance: str, anchor: str = "") -> ThinkRequest:
    """构造 intra_team 阶段的思考请求"""
    template = _get_intra_template(role)
    persona = _get_role_persona(role.value)
    prompt = render(template, role_persona=persona, clarified_topic=clarified_topic, stance=stance)
    prompt = _inject_profile(prompt, role.value)
    prompt = _inject_skills(prompt, stage="intra_team", role=role.value)
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
    prompt = render(
        template, role_persona=_get_role_persona(role.value), clarified_topic=clarified_topic, stance=stance
    )
    # 在模板渲染后注入前序结论
    if prior_summary:
        prompt = prompt + prior_summary
    prompt = _inject_profile(prompt, role.value)
    prompt = _inject_skills(prompt, stage="intra_team", role=role.value)
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
    prompt = _inject_skills(prompt, stage="cross_team", role=Role.MODERATOR.value)
    if anchor:
        prompt = f"{anchor}\n\n{prompt}"
    return ThinkRequest(
        agent_role=Role.MODERATOR.value,
        stage="cross_team",
        prompt=prompt,
        schema_hint="cross_team",
    )


def build_evidence_prompt(
    conflict: dict, evidence_chunks: list[dict], anchor: str = "", available_tools: list[dict[str, Any]] | None = None
) -> ThinkRequest:
    prompt = render(EVIDENCE_CHECK, conflict=str(conflict), evidence_chunks=str(evidence_chunks))
    prompt = _inject_profile(prompt, Role.MODERATOR.value)
    prompt = _inject_skills(prompt, stage="evidence_check", role=Role.MODERATOR.value)
    if available_tools:
        prompt = _inject_tools_to_prompt(prompt, available_tools)
    if anchor:
        prompt = f"{anchor}\n\n{prompt}"
    return ThinkRequest(
        agent_role=Role.MODERATOR.value,
        stage="evidence_check",
        prompt=prompt,
        schema_hint="evidence_check",
        available_tools=available_tools or [],
    )


def build_arbitrate_prompt(evidence_set: list[dict], anchor: str = "") -> ThinkRequest:
    prompt = render(ARBITRATE, evidence_set=str(evidence_set))
    prompt = _inject_profile(prompt, Role.MODERATOR.value)
    prompt = _inject_skills(prompt, stage="arbitrate", role=Role.MODERATOR.value)
    if anchor:
        prompt = f"{anchor}\n\n{prompt}"
    return ThinkRequest(
        agent_role=Role.MODERATOR.value,
        stage="arbitrate",
        prompt=prompt,
        schema_hint="arbitrate",
    )


def build_produce_prompt(
    decision_record: dict,
    anchor: str = "",
    template: str | None = None,
    deliverable_type: str = "prd_openapi",
    evidence_summary: dict | None = None,
) -> ThinkRequest:
    if template is None:
        template = PRODUCE
    # 注入代码质量经验库（bug patterns）
    from app.agents.bug_patterns import format_bug_patterns_for_prompt

    bug_patterns = format_bug_patterns_for_prompt()
    # 格式化证据上下文（供 data_science / code_analysis 模板使用）
    evidence_context = ""
    if evidence_summary and deliverable_type in ("data_science", "code_analysis", "tested_system"):
        evidence_context = _format_evidence_for_code_gen(evidence_summary)
    prompt = render(
        template,
        decision_record=str(decision_record),
        bug_patterns=bug_patterns,
        evidence_context=evidence_context,
    )
    prompt = _inject_profile(prompt, Role.MODERATOR.value)
    # 注入匹配的Skills（UI设计规范、代码规范等，根据deliverable_type动态加载）
    prompt = _inject_skills(prompt, stage="produce", deliverable_type=deliverable_type, role=Role.MODERATOR.value)
    if anchor:
        prompt = f"{anchor}\n\n{prompt}"
    return ThinkRequest(
        agent_role=Role.MODERATOR.value,
        stage="produce",
        prompt=prompt,
        schema_hint=f"produce_{deliverable_type}",
    )


def _format_evidence_for_code_gen(evidence_summary: dict) -> str:
    """将证据综合结果格式化为 prompt 段落，注入代码生成上下文"""
    lines = ["【可用数据来源与证据上下文】"]
    lines.append("以下是讨论和证据对照阶段发现的数据来源和分析方向，请在生成代码时充分利用：\n")

    sources = evidence_summary.get("available_data_sources", [])
    if sources:
        lines.append(f"数据来源（共 {len(sources)} 个）:")
        for i, src in enumerate(sources[:8], 1):
            lines.append(f"  {i}. {src}")
        lines.append("")

    samples = evidence_summary.get("evidence_samples", [])
    if samples:
        lines.append(
            f"关键证据摘要（共 {evidence_summary.get('evidence_count', len(samples))} 条，展示前 {len(samples)} 条）:"
        )
        for s in samples[:10]:
            support_tag = f"[{s.get('supports', 'neutral')}]" if s.get("supports") else ""
            lines.append(f"  - {support_tag} {s.get('quote', '')[:150]}  (来源: {s.get('source', '?')})")
        lines.append("")

    decisions_count = evidence_summary.get("decisions_count", 0)
    adopted_count = evidence_summary.get("adopted_claims_count", 0)
    if decisions_count or adopted_count:
        lines.append(f"仲裁结果: {decisions_count} 项决策, {adopted_count} 条采纳论点")
        lines.append("")

    lines.append("请在生成代码时：")
    lines.append("1. 优先使用上述数据来源构造分析管道，避免凭空捏造数据")
    lines.append("2. 计算与已采纳结论一致的指标，使代码输出能验证裁决方向")
    lines.append("3. 生成能直观展示关键发现的可视化图表")

    return "\n".join(lines)


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


async def execute_think(req: ThinkRequest) -> ThinkResponse:
    """统一 Agent 执行入口：所有 LLM 调用应经此函数

    职责：
    1. 获取全局 compute 实例（Local 或 gRPC）
    2. 委托执行 think()
    3. 统一错误处理和日志

    替代直接调用 compute.think()，为后续添加 trace、metrics 提供统一切入点。
    """
    compute = get_compute()
    return await compute.think(req)


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
