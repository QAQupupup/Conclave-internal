# § Scheduler：任务调度器
# 把阶段/子任务表达为显式 DAG，支持递归深度控制。
from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SubTask:
    """子任务节点"""

    id: str
    stage: str
    role: str
    description: str
    dependencies: list[str] = field(default_factory=list)
    max_depth: int = 0
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecutionPlan:
    """执行计划 = DAG"""

    tasks: list[SubTask] = field(default_factory=list)

    def topological_layers(self) -> list[list[SubTask]]:
        """按拓扑排序分层，每层内部可并行"""
        pending = {t.id: t for t in self.tasks}
        completed: set[str] = set()
        layers: list[list[SubTask]] = []
        while pending:
            layer = [t for t in pending.values() if all(dep in completed for dep in t.dependencies)]
            if not layer:
                raise ValueError("存在循环依赖或不可达任务")
            layers.append(layer)
            for t in layer:
                completed.add(t.id)
                del pending[t.id]
        return layers


class Scheduler:
    """调度器

    职责：
    1. 把高层阶段（clarify/intra_team/...）展开为 SubTask DAG
    2. 按拓扑分层并行执行
    3. 支持递归：AgentResult.sub_tasks 可被再次 schedule
    4. 收集结果并返回给 Manager
    """

    def __init__(
        self,
        executor: Callable[[SubTask, dict[str, Any]], Coroutine[Any, Any, dict[str, Any]]],
        max_recursion_depth: int = 2,
    ):
        self.executor = executor
        self.max_recursion_depth = max_recursion_depth

    async def run_plan(self, plan: ExecutionPlan, shared_state: dict[str, Any]) -> dict[str, Any]:
        results: dict[str, Any] = {}
        for layer in plan.topological_layers():
            coros = [self._run_task(t, shared_state, results, depth=0) for t in layer]
            layer_results = await asyncio.gather(*coros, return_exceptions=True)
            for t, res in zip(layer, layer_results, strict=False):
                if isinstance(res, Exception):
                    results[t.id] = {"success": False, "error": str(res)}
                else:
                    results[t.id] = res
        return results

    async def _run_task(
        self,
        task: SubTask,
        shared_state: dict[str, Any],
        parent_results: dict[str, Any],
        depth: int,
    ) -> dict[str, Any]:
        # 注入依赖结果
        dep_payload = {dep: parent_results.get(dep) for dep in task.dependencies}
        context = {"shared_state": shared_state, "dependencies": dep_payload}
        result = await self.executor(task, context)

        # 递归处理子任务
        sub_tasks = result.get("sub_tasks", [])
        if sub_tasks and depth < self.max_recursion_depth:
            sub_plan = self._build_sub_plan(task.id, sub_tasks)
            sub_results = await self.run_plan(sub_plan, shared_state)
            result["sub_results"] = sub_results
        return result

    def _build_sub_plan(self, parent_id: str, sub_tasks: list[dict[str, Any]]) -> ExecutionPlan:
        tasks = []
        for st in sub_tasks:
            tasks.append(
                SubTask(
                    id=f"{parent_id}:{st.get('id', str(uuid.uuid4())[:6])}",
                    stage=st.get("stage", "produce"),
                    role=st.get("role", "engineer"),
                    description=st.get("description", ""),
                    dependencies=[f"{parent_id}:{dep}" for dep in st.get("dependencies", [])],
                    payload=st.get("payload", {}),
                )
            )
        return ExecutionPlan(tasks=tasks)

    @staticmethod
    def stage_plan(stage: str, team_roles: list[dict[str, Any]], task_description: str = "") -> ExecutionPlan:
        """从阶段和团队角色生成简单并行计划"""
        tasks = [
            SubTask(
                id=f"{stage}:{r.get('role', 'agent')}",
                stage=stage,
                role=r.get("role", "agent"),
                description=task_description or f"执行 {stage} 阶段任务",
            )
            for r in team_roles
        ]
        return ExecutionPlan(tasks=tasks)
