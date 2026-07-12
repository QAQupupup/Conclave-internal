"""测试 Scheduler 的 DAG 分层与递归执行。

不调用真实 LLM，只验证调度逻辑。
"""
from __future__ import annotations

import pytest

from conclave_core.scheduler import ExecutionPlan, Scheduler, SubTask


async def _dummy_executor(task: SubTask, context: dict) -> dict:
    """模拟执行器：返回任务 id 和依赖结果"""
    return {
        "id": task.id,
        "deps": list(context.get("dependencies", {}).keys()),
        "sub_tasks": task.payload.get("sub_tasks", []),
    }


@pytest.mark.asyncio
async def test_topological_layers():
    plan = ExecutionPlan(
        tasks=[
            SubTask(id="a", stage="clarify", role="moderator", description="A"),
            SubTask(id="b", stage="intra", role="architect", description="B", dependencies=["a"]),
            SubTask(id="c", stage="intra", role="engineer", description="C", dependencies=["a"]),
            SubTask(id="d", stage="cross", role="moderator", description="D", dependencies=["b", "c"]),
        ]
    )
    layers = plan.topological_layers()
    assert len(layers) == 3
    assert [t.id for t in layers[0]] == ["a"]
    assert {t.id for t in layers[1]} == {"b", "c"}
    assert [t.id for t in layers[2]] == ["d"]


@pytest.mark.asyncio
async def test_run_plan_sequential_and_parallel():
    scheduler = Scheduler(_dummy_executor)
    plan = ExecutionPlan(
        tasks=[
            SubTask(id="a", stage="clarify", role="moderator", description="A"),
            SubTask(id="b", stage="intra", role="architect", description="B", dependencies=["a"]),
            SubTask(id="c", stage="intra", role="engineer", description="C", dependencies=["a"]),
        ]
    )
    results = await scheduler.run_plan(plan, shared_state={})
    assert results["a"]["deps"] == []
    assert set(results["b"]["deps"]) == {"a"}
    assert set(results["c"]["deps"]) == {"a"}


@pytest.mark.asyncio
async def test_recursive_sub_tasks():
    """验证子任务递归调度，受 max_recursion_depth 限制"""
    async def executor_with_subtasks(task: SubTask, context: dict) -> dict:
        return {
            "id": task.id,
            "sub_tasks": [{"id": "sub1", "stage": "produce", "role": "engineer", "description": "sub"}]
            if ":" not in task.id else [],
        }

    scheduler = Scheduler(executor_with_subtasks, max_recursion_depth=1)
    plan = ExecutionPlan(
        tasks=[SubTask(id="root", stage="produce", role="engineer", description="root")]
    )
    results = await scheduler.run_plan(plan, shared_state={})
    assert "sub_results" in results["root"]
    # 第二层子任务不应再展开
    sub = results["root"]["sub_results"]
    assert "root:sub1" in sub
    assert "sub_results" not in sub["root:sub1"]


@pytest.mark.asyncio
async def test_circular_dependency_raises():
    plan = ExecutionPlan(
        tasks=[
            SubTask(id="a", stage="clarify", role="moderator", description="A", dependencies=["b"]),
            SubTask(id="b", stage="clarify", role="moderator", description="B", dependencies=["a"]),
        ]
    )
    with pytest.raises(ValueError, match="循环依赖"):
        plan.topological_layers()
