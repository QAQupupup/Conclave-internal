# § Meeting Manager：系统级调度与治理中枢
# 不是 Agent，而是 Agent 网络上层的“操作系统内核”。
from __future__ import annotations

from typing import Any

from app.agents.agent_runtime import AgentContext, AgentResult, build_agent_from_baseline
from app.agents.task_baseline import TaskBaseline, get_baseline
from app.orchestrator.context_manager import ContextManager
from conclave_core.scheduler import Scheduler, SubTask
from app.orchestrator.stage_planners import get_stage_planner
from app.orchestrator.stage_reducers import reduce_stage_results


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
    ):
        self.context_manager = context_manager or ContextManager()
        self.scheduler = scheduler
        self.max_recursion_depth = max_recursion_depth

    async def run_stage(
        self,
        state: Any,
        stage: str,
        baseline: TaskBaseline | None = None,
    ) -> Any:
        """运行单个阶段

        统一路径：Planner -> Scheduler -> Reducer，返回更新后的 MeetingState。
        遗留节点（如 produce）仍通过 Reducer 调用，后续逐步迁移到 stage_runners。
        """
        baseline = baseline or self.select_baseline(
            state.topic if hasattr(state, "topic") else "",
            state.domain_hint if hasattr(state, "domain_hint") else "",
        )
        if self.scheduler is None:
            self.scheduler = Scheduler(self._execute_subtask, max_recursion_depth=self.max_recursion_depth)

        planner = get_stage_planner(stage)
        plan = planner(state, baseline)
        shared_state = {"state": state, "baseline": baseline}
        results = await self.scheduler.run_plan(plan, shared_state)
        return await reduce_stage_results(state, stage, results)

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
            "task_id": task.id,
            "meta": {
                "role": task.role,
                "stage": task.stage,
                "description": task.description,
                **task.payload,
            },
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
