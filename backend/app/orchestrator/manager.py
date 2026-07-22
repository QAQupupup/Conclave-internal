# § Meeting Manager：系统级调度与治理中枢
# 不是 Agent，而是 Agent 网络上层的“操作系统内核”。
from __future__ import annotations

from typing import Any

from app.agents.agent_runtime import AgentContext, AgentResult, build_agent_from_baseline
from app.agents.task_baseline import TaskBaseline, get_baseline
from app.orchestrator.context_manager import ContextManager
from app.orchestrator.stage_planners import get_stage_planner
from app.orchestrator.stage_reducers import reduce_stage_results
from conclave_core.scheduler import Scheduler, SubTask


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
        # M1.1: 懒加载 LLM 客户端，用于上下文摘要生成
        self._llm: Any = None

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
        # produce 阶段：reducer 直接调用 produce_node（含分阶段生成），
        # 不需要 SubTask agent 做额外的 LLM 调用（避免重复生成导致长时间挂起）
        if stage == "produce":
            return await reduce_stage_results(state, stage, {})

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

        # 1. 准备上下文（M1.1: 动态窗口 + 摘要压缩）
        ctx_slice = await self.context_manager.prepare_async(
            state, task.stage, task.role, llm_summarize=self._summarize_callback
        )

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

    # ---------- M1.1: 上下文摘要 LLM 回调 ----------

    def _get_llm(self) -> Any:
        """懒加载 LLM 客户端（缓存，避免每次摘要都创建新连接池）"""
        if self._llm is None:
            from app.agents import llm as _llm_mod

            self._llm = _llm_mod.get_llm()
        return self._llm

    async def _summarize_callback(self, prompt: str) -> str:
        """ContextManager 摘要压缩的 LLM 回调。

        使用 complete_text() 做纯文本补全（无 JSON schema）。
        失败时返回空字符串，ContextManager 自动降级为裁剪。
        """
        llm = self._get_llm()
        complete_text_fn = getattr(llm, "complete_text", None)
        if complete_text_fn is not None:
            result: str = await complete_text_fn(prompt)
            return result
        # 兼容：LLM 客户端无 complete_text 时降级
        return ""

    # ---------- 统一交互层（后续逐步替换 Runner 中直接调用） ----------
    async def persist_state(self, state: Any) -> None:
        """持久化状态到 PostgreSQL（通过 db_legacy）"""
        from app.db_legacy import save_meeting, save_meeting_aux, save_message

        aux = state.extract_aux() if hasattr(state, "extract_aux") else {}
        await save_meeting(
            meeting_id=state.meeting_id,
            topic=state.topic,
            status=state.status.value if hasattr(state.status, "value") else str(state.status),
            stage=state.stage.value if hasattr(state.stage, "value") else str(state.stage),
            created_at=state.created_at,
            payload=state.snapshot() if hasattr(state, "snapshot") else state.model_dump(),
        )
        await save_meeting_aux(state.meeting_id, aux)
        for msg in getattr(state, "messages", []):
            await save_message(msg)

    async def publish_event(self, meeting_id: str, event_type: str, payload: dict[str, Any]) -> None:
        """通过 EventBus 发布事件"""
        from app.events import bus, make_event

        await bus.publish(make_event(event_type, meeting_id, payload))

    async def dispatch_material(self, query: str, meeting_id: str) -> list[dict[str, Any]]:
        """通过 RAG retriever 检索物料（异步）"""
        try:
            from app.rag.retriever import retrieve

            return await retrieve(meeting_id, query)
        except Exception:
            return []
