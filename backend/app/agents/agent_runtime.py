# § 统一 Agent 运行时
# 所有 Agent（主持人、治理、业务、子 Agent）共享同一执行接口，差异通过配置表达。
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from app.agents.compute import ThinkRequest, get_compute
from app.agents.task_baseline import RequiredArtifact, TaskBaseline


@dataclass
class AgentConfig:
    """Agent 运行时配置"""

    role: str
    name: str
    instructions: str
    output_schema: str = ""
    tools: list[str] = field(default_factory=list)
    sub_agents: list[str] = field(default_factory=list)
    max_depth: int = 0
    temperature: float = 0.3


@dataclass
class AgentContext:
    """单次 Agent 执行上下文"""

    meeting_id: str
    topic: str
    stage: str
    baseline: TaskBaseline
    # 由 ContextManager 准备好的上下文切片
    working_memory: dict[str, Any] = field(default_factory=dict)
    # 父 Agent 传递下来的约束/结论
    parent_constraints: list[str] = field(default_factory=list)
    # 已锁定的结论链
    locked_conclusions: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class AgentResult:
    """Agent 执行结果"""

    success: bool
    role: str
    stage: str
    payload: dict[str, Any] = field(default_factory=dict)
    confidence: str = "high"
    produced_artifacts: list[RequiredArtifact] = field(default_factory=list)
    sub_tasks: list[dict[str, Any]] = field(default_factory=list)
    trace_id: str = ""
    latency_ms: int = 0
    error: str = ""


class AgentRuntime:
    """统一 Agent 运行时

    职责：
    1. 根据 AgentConfig 构造 prompt
    2. 调用 compute 层执行 LLM
    3. 按 output_schema 校验结果
    4. 若配置 sub_agents，递归拆分子任务（受 max_depth 限制）
    """

    def __init__(self, config: AgentConfig):
        self.config = config
        self.compute = get_compute()

    async def execute(
        self,
        ctx: AgentContext,
        task: dict[str, Any],
    ) -> AgentResult:
        trace_id = str(uuid.uuid4())[:8]
        prompt = self._build_prompt(ctx, task)
        schema_hint = self.config.output_schema or ctx.stage

        req = ThinkRequest(
            agent_role=self.config.role,
            stage=ctx.stage,
            prompt=prompt,
            schema_hint=schema_hint,
            temperature=self.config.temperature,
        )

        try:
            resp = await self.compute.think(req)
        except Exception as exc:
            return AgentResult(
                success=False,
                role=self.config.role,
                stage=ctx.stage,
                trace_id=trace_id,
                error=str(exc),
            )

        payload = resp.result if resp.success else {}
        if not isinstance(payload, dict):
            payload = {"raw": payload}

        return AgentResult(
            success=resp.success,
            role=self.config.role,
            stage=ctx.stage,
            payload=payload,
            confidence="high" if resp.validation_status == "valid" else "low",
            trace_id=trace_id,
            latency_ms=resp.latency_ms,
            error=resp.error or "",
        )

    def _build_prompt(self, ctx: AgentContext, task: dict[str, Any]) -> str:
        parts = [
            f"# 角色：{self.config.name} ({self.config.role})",
            f"## 任务\n{task.get('description', '请根据上下文完成本阶段工作')}",
            f"## 议题\n{ctx.topic}",
        ]
        if ctx.parent_constraints:
            parts.append("## 父级约束\n" + "\n".join(f"- {c}" for c in ctx.parent_constraints))
        if ctx.locked_conclusions:
            parts.append(
                "## 已锁定结论\n"
                + "\n".join(f"- [{c.get('stage')}] {c.get('summary', '')}" for c in ctx.locked_conclusions)
            )
        if ctx.working_memory:
            parts.append("## 相关上下文\n")
            for k, v in ctx.working_memory.items():
                parts.append(f"### {k}\n{self._summarize(v)}")
        parts.append(f"## 角色指令\n{self.config.instructions}")
        return "\n\n".join(parts)

    @staticmethod
    def _summarize(value: Any, max_len: int = 1200) -> str:
        text = str(value)
        if len(text) <= max_len:
            return text
        return text[:max_len] + f"\n...（已截断，原长度 {len(text)}）"


def build_agent_from_baseline(
    role: dict[str, Any],
    baseline: TaskBaseline,
    stage: str,
) -> AgentRuntime:
    """从 TaskBaseline 的团队角色定义构建 AgentRuntime"""
    role_key = role.get("role", "unknown")
    return AgentRuntime(
        AgentConfig(
            role=role_key,
            name=role.get("name", role_key),
            instructions=role.get("instructions", f"你是 {role_key}，立场：{role.get('stance', '')}"),
            output_schema=stage,
            temperature=float(role.get("temperature", 0.3)),
        )
    )
