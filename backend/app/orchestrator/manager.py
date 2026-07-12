# § Meeting Manager：系统级调度与治理中枢
# 不是 Agent，而是 Agent 网络上层的“操作系统内核”。
from __future__ import annotations

from typing import Any

from app.agents.agent_runtime import AgentContext, AgentResult, AgentRuntime, build_agent_from_baseline
from app.agents.task_baseline import TaskBaseline, get_baseline
from app.orchestrator.context_manager import ContextManager, ContextSlice
from app.orchestrator.scheduler import ExecutionPlan, Scheduler, SubTask


class MeetingManager:
    """会议生命周期管理器

    职责：
    1. 调度：把会议目标拆成阶段和子任务，分配给 Agent
    2. 管理：管理会议、Agent、物料的生命周期
    3. 分发：把物料切片喂给 Agent，把产物路由给下游或归档
    4. 治理：监控递归深度、token 消耗、执行时间，触发熔断/降级
    5. 协调：作为 Storage、EventBus、Sandbox、Scheduler、Agent 之间的统一交互层
    """

    def __init__(
        self,
        context_manager: ContextManager | None = None,
        scheduler: Scheduler | None = None,
        max_recursion_depth: int = 2,
        compatibility_mode: bool = False,
    ):
        self.context_manager = context_manager or ContextManager()
        self.scheduler = scheduler
        self.max_recursion_depth = max_recursion_depth
        # Phase 1 兼容模式：直接调用旧节点函数，保证 Runner 行为不变
        self.compatibility_mode = compatibility_mode

    async def run_stage(
        self,
        state: Any,
        stage: str,
        baseline: TaskBaseline | None = None,
    ) -> Any:
        """运行单个阶段

        Phase 1 兼容模式：直接调用旧节点函数，返回 MeetingState。
        非兼容模式：通过 Scheduler 展开 SubTask DAG，返回任务结果字典。
        """
        if self.compatibility_mode:
            return await self._run_stage_compat(state, stage)

        baseline = baseline or get_baseline(state.topic if hasattr(state, "topic") else "")
        if self.scheduler is None:
            self.scheduler = Scheduler(self._execute_subtask, max_recursion_depth=self.max_recursion_depth)

        plan = Scheduler.stage_plan(stage, baseline.team_roles)
        shared_state = {"state": state, "baseline": baseline}
        return await self.scheduler.run_plan(plan, shared_state)

    async def _run_stage_compat(self, state: Any, stage: str) -> Any:
        """兼容模式：直接调用旧节点函数"""
        from app.models import Stage
        from app.orchestrator.nodes import NODES

        try:
            stage_enum = Stage(stage)
        except ValueError as exc:
            raise ValueError(f"无效阶段: {stage}") from exc

        node = NODES.get(stage_enum)
        if node is None:
            raise ValueError(f"阶段 {stage} 无对应节点")

        return await node(state)

    async def _execute_subtask(self, task: SubTask, context: dict[str, Any]) -> dict[str, Any]:
        shared = context.get("shared_state", {})
        state = shared.get("state")
        baseline = shared.get("baseline")

        # 1. 准备上下文
        ctx_slice = self.context_manager.prepare(state, task.stage, task.role)

        # 2. 构建 Agent 并执行
        role_def = {"role": task.role, "instructions": task.description}
        agent = build_agent_from_baseline(role_def, baseline, task.stage)
        agent_ctx = AgentContext(
            meeting_id=state.meeting_id if hasattr(state, "meeting_id") else "",
            topic=state.topic if hasattr(state, "topic") else "",
            stage=task.stage,
            baseline=baseline,
            working_memory={"context": ctx_slice.to_prompt_text()},
        )
        result: AgentResult = await agent.execute(agent_ctx, {"description": task.description, "payload": task.payload})

        # 3. 治理：记录 token、耗时
        return {
            "success": result.success,
            "role": result.role,
            "stage": result.stage,
            "payload": result.payload,
            "confidence": result.confidence,
            "trace_id": result.trace_id,
            "latency_ms": result.latency_ms,
            "error": result.error,
            "sub_tasks": result.sub_tasks,
        }

    def select_baseline(self, topic: str, domain_hint: str = "") -> TaskBaseline:
        """根据议题选择基线"""
        return get_baseline(topic, domain_hint)

    # ---------- 统一交互层（后续逐步替换 Runner 中直接调用） ----------
    def persist_state(self, state: Any) -> None:
        """持久化状态（待接入 Repository 层）"""
        # TODO: 统一通过 Repository 写入 PostgreSQL
        pass

    def publish_event(self, meeting_id: str, event_type: str, payload: dict[str, Any]) -> None:
        """发布事件（待接入 EventBus）"""
        # TODO: 统一通过 EventBus 发布
        pass

    def dispatch_material(self, query: str, meeting_id: str) -> dict[str, Any]:
        """分发物料（待接入 MaterialHub）"""
        # TODO: 统一通过 MaterialHub 检索
        return {}
