"""议题状态机与生命周期编排（ADR-017 Phase 2）。

状态机（合法流转）::

    open ──→ scheduled ──→ in_progress ──→ resolved
      │          │            │  │
      │          └→ open（解绑）│  └──→ conflict（合入冲突，D11）
      │                        │            │
      │                        │            ├→ open / in_progress（处置后重试）
      │                        │            └→ resolved（重试合入成功）
      └────────────────────────┴────────────────→ wontfix

- ``resolved`` 必须挂 ``resolution_artifact_id``（闭环凭证红线，缺失拒绝）。
- ``resolved`` / ``wontfix`` 为终态，不可再流转。
- ``conflict``（ADR-017 D11）：合入 main 冲突时由合入流程置入，不自动解决、
  交回用户处置；可回池（open）、重新绑会（in_progress）或合入重试成功后闭环（resolved）。
- 会议生命周期挂钩：
  - 创会绑定议题 → ``bind_meeting``（open/scheduled/conflict → in_progress）；
  - 会议成功终态且产物已发布 → ``resolve_issue``（挂闭环凭证）；
  - 会议中止 → ``release_issue``（in_progress → open，议题回池待重办）。

流转通过 DAO 条件更新（WHERE status IN expected）保证原子性。
"""

from __future__ import annotations

from typing import Any

from app.dao import issue_dao
from app.observability.log_bus import log_bus

# 全部合法状态（conflict：ADR-017 D11 合入冲突态）
ISSUE_STATUSES = ("open", "scheduled", "in_progress", "conflict", "resolved", "wontfix")

# 合法流转表：current → 允许的 target 集合
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "open": frozenset({"scheduled", "in_progress", "wontfix"}),
    "scheduled": frozenset({"in_progress", "open", "wontfix"}),
    "in_progress": frozenset({"resolved", "open", "wontfix", "conflict"}),
    # 合入冲突交回用户处置（D11）：回池 / 重新绑会 / 重试合入成功闭环 / 放弃
    "conflict": frozenset({"open", "in_progress", "resolved", "wontfix"}),
    "resolved": frozenset(),
    "wontfix": frozenset(),
}

_LOGGER = "services.issue_service"


class IssueTransitionError(ValueError):
    """非法状态流转（状态机校验失败）。"""


def validate_transition(current: str, target: str) -> None:
    """校验状态流转合法性，非法时抛 IssueTransitionError。"""
    if current not in ALLOWED_TRANSITIONS:
        raise IssueTransitionError(f"未知议题状态: {current}")
    if target not in ISSUE_STATUSES:
        raise IssueTransitionError(f"未知目标状态: {target}")
    if target not in ALLOWED_TRANSITIONS[current]:
        raise IssueTransitionError(f"非法流转: {current} → {target}")


async def transition_issue(
    issue_id: str,
    target_status: str,
    resolution_artifact_id: str | None = None,
) -> dict[str, Any]:
    """通用状态流转（供 API PATCH 使用）。

    - 校验状态机合法性（基于当前实际状态）；
    - 流转到 resolved 时必须提供或已挂 resolution_artifact_id（红线）；
    - 条件更新未命中（并发竞争或状态已变）时抛 IssueTransitionError。

    Raises:
        IssueTransitionError: 非法流转 / 议题不存在 / 并发竞争失败。
    """
    issue = await issue_dao.get_issue(issue_id)
    if issue is None:
        raise IssueTransitionError("议题不存在")
    current = str(issue["status"])
    validate_transition(current, target_status)

    extra: dict[str, Any] = {}
    if target_status == "resolved":
        artifact_id = resolution_artifact_id or issue.get("resolution_artifact_id")
        if not artifact_id:
            raise IssueTransitionError("resolved 必须挂 resolution_artifact_id（闭环凭证）")
        extra["resolution_artifact_id"] = artifact_id

    updated = await issue_dao.transition_status(
        issue_id, expected_statuses=(current,), new_status=target_status, extra_fields=extra or None
    )
    if updated is None:
        raise IssueTransitionError(f"流转失败（状态已并发变更）: {current} → {target_status}")
    log_bus.info(
        f"议题状态流转: {current} → {target_status}",
        logger=_LOGGER,
        extra={"issue_id": issue_id, "from": current, "to": target_status},
    )
    return updated


async def bind_meeting(issue_id: str, meeting_id: str) -> dict[str, Any] | None:
    """会议创建时绑定议题：open/scheduled/conflict → in_progress + 记录执行会议。

    创会路径调用。议题已处于其他状态（含已绑定其他会议）时返回 None，
    由调用方决定是否阻断创会。conflict 态允许重新绑会（D11：合入冲突后
    用户可开新会议重做）。
    """
    updated = await issue_dao.transition_status(
        issue_id,
        expected_statuses=("open", "scheduled", "conflict"),
        new_status="in_progress",
        extra_fields={"assigned_meeting_id": meeting_id},
    )
    if updated is None:
        log_bus.warning(
            "议题绑定会议失败（状态不允许或不存在）",
            logger=_LOGGER,
            extra={"issue_id": issue_id, "meeting_id": meeting_id},
        )
        return None
    log_bus.info(
        "议题已绑定执行会议",
        logger=_LOGGER,
        extra={"issue_id": issue_id, "meeting_id": meeting_id},
    )
    return updated


async def resolve_issue(issue_id: str, resolution_artifact_id: str) -> dict[str, Any] | None:
    """会议成功终态后闭环议题：非终态 → resolved + 挂闭环凭证。

    publish 挂钩调用。允许从 open/scheduled/in_progress 闭环
    （容忍人工改过状态的场景）；已终态时静默返回 None。
    """
    if not resolution_artifact_id:
        log_bus.warning(
            "议题闭环拒绝：缺少闭环凭证（resolved 必挂产物）",
            logger=_LOGGER,
            extra={"issue_id": issue_id},
        )
        return None
    updated = await issue_dao.transition_status(
        issue_id,
        expected_statuses=("open", "scheduled", "in_progress"),
        new_status="resolved",
        extra_fields={"resolution_artifact_id": resolution_artifact_id},
    )
    if updated is None:
        log_bus.info(
            "议题闭环跳过（已终态或不存在）",
            logger=_LOGGER,
            extra={"issue_id": issue_id},
        )
        return None
    log_bus.info(
        "议题已闭环",
        logger=_LOGGER,
        extra={
            "issue_id": issue_id,
            "resolution_artifact_id": resolution_artifact_id,
        },
    )
    return updated


async def release_issue(issue_id: str) -> dict[str, Any] | None:
    """会议中止时释放议题：in_progress → open，议题回池待重办。

    保留 assigned_meeting_id 供追溯（哪次会议曾执行过它）。
    """
    updated = await issue_dao.transition_status(
        issue_id,
        expected_statuses=("in_progress",),
        new_status="open",
    )
    if updated is not None:
        log_bus.info(
            "议题已释放回池（会议中止）",
            logger=_LOGGER,
            extra={"issue_id": issue_id},
        )
    return updated
