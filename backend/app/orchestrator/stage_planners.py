# § Stage Planners：把每个阶段展开为 SubTask DAG
# Phase 2 过渡实现：
# - clarify / cross_team / arbitrate / produce 先保持单任务，与旧节点一次调用等价。
# - intra_team 按角色拆分为并行 SubTask（复用基线团队角色）。
# - evidence_check 按 conflict 拆分为并行 SubTask。
# Phase 3 再进一步细化（如 produce 的子产物递归、intra_team 的 ReAct 迭代等）。
from __future__ import annotations

from typing import Callable

from app.agents.task_baseline import TaskBaseline
from app.models import MeetingState
from app.orchestrator.scheduler import ExecutionPlan, SubTask


def plan_clarify(state: MeetingState, baseline: TaskBaseline) -> ExecutionPlan:
    """clarify 阶段：主持人拆解议题、生成 charter"""
    return ExecutionPlan(
        tasks=[
            SubTask(
                id="clarify-moderator",
                stage="clarify",
                role="moderator",
                description="议题澄清、关键问题识别与会议宪章生成",
                payload={"topic": state.topic},
            )
        ]
    )


def plan_intra_team(state: MeetingState, baseline: TaskBaseline) -> ExecutionPlan:
    """intra_team 阶段：每个团队角色独立发表观点

    优先使用 state.team_config（clarify 阶段由 LLM 生成），
    若为空则回退到 baseline.team_roles（测试/默认场景）。
    """
    team_roles = state.team_config if state.team_config else baseline.team_roles
    tasks: list[SubTask] = []
    for idx, role_def in enumerate(team_roles):
        role = role_def.get("role", "agent")
        stance = role_def.get("stance", "")
        tasks.append(
            SubTask(
                id=f"intra-{role}-{idx}",
                stage="intra_team",
                role=role,
                description=f"从 {role} 视角发表队内观点与 claims",
                payload={"role": role, "stance": stance},
            )
        )
    # 兜底：至少保证一个任务，避免 Scheduler 空跑
    if not tasks:
        tasks.append(
            SubTask(
                id="intra-moderator",
                stage="intra_team",
                role="moderator",
                description="主持人兜底队内观点收集",
            )
        )
    return ExecutionPlan(tasks=tasks)


def plan_cross_team(state: MeetingState, baseline: TaskBaseline) -> ExecutionPlan:
    """cross_team 阶段：主持人识别冲突、汇总共识"""
    return ExecutionPlan(
        tasks=[
            SubTask(
                id="cross-moderator",
                stage="cross_team",
                role="moderator",
                description="基于各角色 claims 识别冲突点或汇总共识",
                payload={"claims": [c for c in state.claims]},
            )
        ]
    )


def plan_evidence_check(state: MeetingState, baseline: TaskBaseline) -> ExecutionPlan:
    """evidence_check 阶段：按 conflict 并行校验证据

    Phase 2 过渡：每个 conflict 一个 SubTask，无 conflict 时退化为单任务。
    """
    conflicts = state.conflicts if state.conflicts else []
    if not conflicts:
        return ExecutionPlan(
            tasks=[
                SubTask(
                    id="evidence-moderator",
                    stage="evidence_check",
                    role="moderator",
                    description="无争议时执行证据兜底检查",
                    payload={"conflicts": []},
                )
            ]
        )

    tasks: list[SubTask] = []
    for idx, conflict in enumerate(conflicts):
        cid = conflict.get("id", f"c{idx}")
        tasks.append(
            SubTask(
                id=f"evidence-{cid}",
                stage="evidence_check",
                role="moderator",
                description=f"校验冲突 {cid} 的相关证据",
                payload={"conflict": conflict},
            )
        )
    return ExecutionPlan(tasks=tasks)


def plan_arbitrate(state: MeetingState, baseline: TaskBaseline) -> ExecutionPlan:
    """arbitrate 阶段：主持人裁决争议、锁定结论"""
    return ExecutionPlan(
        tasks=[
            SubTask(
                id="arbitrate-moderator",
                stage="arbitrate",
                role="moderator",
                description="基于 claims、conflicts 与 evidence_set 做出裁决",
                payload={
                    "claims": [c for c in state.claims],
                    "evidence_set": [e for e in state.evidence_set],
                },
            )
        ]
    )


def plan_produce(state: MeetingState, baseline: TaskBaseline) -> ExecutionPlan:
    """produce 阶段：生成最终产物"""
    return ExecutionPlan(
        tasks=[
            SubTask(
                id="produce-moderator",
                stage="produce",
                role="moderator",
                description=f"生成 {state.deliverable_type or 'prd_openapi'} 产出物",
                payload={
                    "deliverable_type": state.deliverable_type,
                    "decision_record": state.decision_record,
                },
            )
        ]
    )


_STAGE_PLANNERS: dict[str, Callable[[MeetingState, TaskBaseline], ExecutionPlan]] = {
    "clarify": plan_clarify,
    "intra_team": plan_intra_team,
    "cross_team": plan_cross_team,
    "evidence_check": plan_evidence_check,
    "arbitrate": plan_arbitrate,
    "produce": plan_produce,
}


def get_stage_planner(stage: str) -> Callable[[MeetingState, TaskBaseline], ExecutionPlan]:
    planner = _STAGE_PLANNERS.get(stage)
    if planner is None:
        raise ValueError(f"阶段 {stage} 无对应规划器")
    return planner
