# DAG 任务图：表达任务依赖关系，自动并行无依赖任务
# 设计模式：DAG（有向无环图）+ 调度器（拓扑排序 + 同层并行）
#
# 用法：
#   graph = TaskGraph()
#   graph.add_task(Task("fetch_data", "获取数据", execute=fetch_fn))
#   graph.add_task(Task("analyze", "数据分析", dependencies=["fetch_data"], execute=analyze_fn))
#   graph.add_task(Task("report", "生成报告", dependencies=["analyze"], execute=report_fn))
#   graph.add_task(Task("validate", "验证", dependencies=["report"], execute=validate_fn))
#   results = await TaskScheduler().run(graph)
#   # fetch_data 先执行 → analyze 依赖 fetch_data 结果 → report 依赖 analyze → validate 依赖 report
#
# 同层并行示例：
#   graph.add_task(Task("fetch_api", "API数据", execute=fn1))
#   graph.add_task(Task("fetch_db", "DB数据", execute=fn2))  # 与 fetch_api 无依赖，自动并行
#   graph.add_task(Task("merge", "合并", dependencies=["fetch_api", "fetch_db"], execute=fn3))
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from app.logging_config import get_logger

logger = get_logger("orchestrator.task_graph")


@dataclass
class Task:
    """单个任务节点

    - id: 唯一标识
    - name: 人类可读名称
    - dependencies: 依赖的任务 id 列表（必须全部完成才能执行本任务）
    - execute: 异步执行函数，接收前置任务结果 dict，返回本任务结果
    - result: 执行结果（执行后填充）
    - status: pending / running / done / failed
    """
    id: str
    name: str
    dependencies: list[str] = field(default_factory=list)
    execute: Callable[[dict[str, Any]], Awaitable[Any]] | None = None
    result: Any = None
    status: str = "pending"

    def __post_init__(self):
        if not self.id:
            raise ValueError("Task.id 不能为空")


class TaskGraph:
    """任务依赖图（DAG）

    支持添加任务和依赖关系，支持拓扑排序分层。
    """

    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}

    def add_task(self, task: Task) -> None:
        """添加任务到图"""
        if task.id in self._tasks:
            raise ValueError(f"任务 {task.id} 已存在")
        self._tasks[task.id] = task

    def get_task(self, task_id: str) -> Task | None:
        return self._tasks.get(task_id)

    @property
    def tasks(self) -> dict[str, Task]:
        return self._tasks

    def validate(self) -> None:
        """校验 DAG 无环且依赖存在"""
        for task in self._tasks.values():
            for dep in task.dependencies:
                if dep not in self._tasks:
                    raise ValueError(f"任务 {task.id} 依赖不存在的任务 {dep}")
        # 环检测：DFS
        visiting: set[str] = set()
        visited: set[str] = set()

        def check(tid: str) -> None:
            if tid in visited:
                return
            if tid in visiting:
                raise ValueError(f"检测到环依赖，涉及任务 {tid}")
            visiting.add(tid)
            for dep in self._tasks[tid].dependencies:
                check(dep)
            visiting.discard(tid)
            visited.add(tid)

        for tid in self._tasks:
            check(tid)

    def topological_layers(self) -> list[list[str]]:
        """拓扑排序分层：同一层的任务无依赖关系，可并行执行

        返回 [[layer0_tasks], [layer1_tasks], ...]
        layer0 无依赖，layer1 依赖 layer0，依此类推。
        """
        self.validate()
        layers: list[list[str]] = []
        completed: set[str] = set()
        remaining = set(self._tasks.keys())

        while remaining:
            # 找出所有依赖已完成的任务
            ready = [tid for tid in remaining if all(d in completed for d in self._tasks[tid].dependencies)]
            if not ready:
                raise ValueError("拓扑排序失败：可能存在环")
            layers.append(ready)
            completed.update(ready)
            remaining -= set(ready)
        return layers


class TaskScheduler:
    """任务调度器：按拓扑分层并行执行 DAG

    同一层的任务 asyncio.gather 并行执行，
    层间串行等待（上层全部完成后才进入下层）。
    """

    async def run(self, graph: TaskGraph) -> dict[str, Any]:
        """执行整个任务图，返回 {task_id: result}"""
        graph.validate()
        layers = graph.topological_layers()
        results: dict[str, Any] = {}

        for layer_idx, layer in enumerate(layers):
            logger.info("执行第 %d 层（%d 个任务）: %s", layer_idx, len(layer), layer)
            # 同层并行
            async def _run_one(tid: str) -> tuple[str, Any]:
                task = graph.get_task(tid)
                if task is None or task.execute is None:
                    return tid, None
                task.status = "running"
                try:
                    # 把前置任务的结果传给执行函数
                    dep_results = {d: results.get(d) for d in task.dependencies}
                    result = await task.execute(dep_results)
                    task.result = result
                    task.status = "done"
                    return tid, result
                except Exception as e:
                    task.status = "failed"
                    logger.error("任务 %s 执行失败: %s", tid, e, exc_info=True)
                    return tid, {"error": str(e)}

            layer_results = await asyncio.gather(*[_run_one(tid) for tid in layer])
            for tid, result in layer_results:
                results[tid] = result

        return results
