"""议题状态机与生命周期服务测试（ADR-017 Phase 2）。

覆盖：
- validate_transition 纯逻辑：全部合法流转 + 非法流转拒绝（非正向）
- transition_issue：合法流转 / 非法流转 409 语义 / resolved 闭环凭证红线（非正向）
- bind_meeting：open/scheduled 绑定成功；已绑定/终态拒绝返回 None（非正向）
- resolve_issue：挂凭证闭环；缺凭证拒绝；已终态静默跳过（非正向）
- release_issue：in_progress 释放回池；其他状态返回 None（非正向）

状态机契约（issue_service.ALLOWED_TRANSITIONS）：
    open → scheduled/in_progress/wontfix
    scheduled → in_progress/open/wontfix
    in_progress → resolved/open/wontfix
    resolved/wontfix 为终态
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.dao import artifact_dao, issue_dao, meeting_dao, project_dao
from app.services.issue_service import (
    ALLOWED_TRANSITIONS,
    ISSUE_STATUSES,
    IssueTransitionError,
    bind_meeting,
    release_issue,
    resolve_issue,
    transition_issue,
    validate_transition,
)


def _slug(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _mid(prefix: str) -> str:
    return f"mtg-{prefix}-{uuid.uuid4().hex[:8]}"


async def _seed_project(prefix: str) -> dict:
    return await project_dao.create_project(slug=_slug(prefix), name=f"{prefix} 项目")


async def _seed_issue(prefix: str, title: str = "状态机议题") -> dict:
    project = await _seed_project(prefix)
    return await issue_dao.create_issue(project_id=project["id"], title=title, source="user")


async def _seed_meeting(meeting_id: str) -> None:
    await meeting_dao.save_meeting(
        meeting_id=meeting_id,
        topic=f"议题服务测试会议 {meeting_id}",
        status="done",
        stage="produce",
        created_at=datetime.now(timezone.utc),
        payload={},
    )


# ---------- validate_transition 纯逻辑 ----------


def test_validate_transition_all_legal_pairs():
    """合法流转表内全部配对校验通过（往返：与 ALLOWED_TRANSITIONS 定义一致）"""
    for current, targets in ALLOWED_TRANSITIONS.items():
        for target in targets:
            validate_transition(current, target)  # 不抛异常即通过


def test_validate_transition_illegal_rejected():
    """非法流转全部拒绝：终态不可出、跳级不允许、自流转不允许（非正向）"""
    illegal_pairs = [
        ("open", "open"),  # 自流转
        ("open", "resolved"),  # 跳级：未经 in_progress
        ("scheduled", "resolved"),  # 跳级
        ("resolved", "open"),  # 终态不可出
        ("resolved", "wontfix"),  # 终态不可出
        ("wontfix", "open"),  # 终态不可出
    ]
    for current, target in illegal_pairs:
        with pytest.raises(IssueTransitionError):
            validate_transition(current, target)


def test_validate_transition_unknown_status():
    """未知状态/未知目标 → IssueTransitionError（非正向）"""
    with pytest.raises(IssueTransitionError, match="未知议题状态"):
        validate_transition("ghost", "open")
    with pytest.raises(IssueTransitionError, match="未知目标状态"):
        validate_transition("open", "ghost")
    # 状态全集与流转表键一致（防新增状态漏配流转规则）
    assert set(ALLOWED_TRANSITIONS.keys()) == set(ISSUE_STATUSES)


# ---------- transition_issue ----------


async def test_transition_issue_legal():
    """合法流转：open → scheduled，落库生效"""
    issue = await _seed_issue("trans-ok")
    updated = await transition_issue(issue["id"], "scheduled")
    assert updated["status"] == "scheduled"
    got = await issue_dao.get_issue(issue["id"])
    assert got is not None and got["status"] == "scheduled"


async def test_transition_issue_illegal_raises():
    """非法流转：open 直接 resolved → IssueTransitionError，状态不变（非正向）"""
    issue = await _seed_issue("trans-bad")
    with pytest.raises(IssueTransitionError, match="非法流转"):
        await transition_issue(issue["id"], "resolved")
    got = await issue_dao.get_issue(issue["id"])
    assert got is not None and got["status"] == "open"


async def test_transition_issue_missing_raises():
    """议题不存在 → IssueTransitionError（非正向）"""
    with pytest.raises(IssueTransitionError, match="议题不存在"):
        await transition_issue("issue-no-such", "scheduled")


async def test_transition_resolved_requires_artifact():
    """红线：流转到 resolved 未挂闭环凭证 → 拒绝（非正向）"""
    issue = await _seed_issue("trans-noart")
    await transition_issue(issue["id"], "in_progress")
    with pytest.raises(IssueTransitionError, match="resolution_artifact_id"):
        await transition_issue(issue["id"], "resolved")
    got = await issue_dao.get_issue(issue["id"])
    assert got is not None and got["status"] == "in_progress"  # 未被流转


async def test_transition_resolved_with_artifact():
    """resolved 携带闭环凭证 → 流转成功且凭证落库（往返）"""
    issue = await _seed_issue("trans-art")
    mid = _mid("issue-art")
    await _seed_meeting(mid)
    artifact = await artifact_dao.publish_artifact(meeting_id=mid, artifact_type="adr", version=1)

    await transition_issue(issue["id"], "in_progress")
    updated = await transition_issue(issue["id"], "resolved", resolution_artifact_id=artifact["id"])
    assert updated["status"] == "resolved"
    assert updated["resolution_artifact_id"] == artifact["id"]


# ---------- bind_meeting（创会挂钩） ----------


async def test_bind_meeting_open_to_in_progress():
    """open 议题绑定会议：→ in_progress + assigned_meeting_id 落库"""
    issue = await _seed_issue("bind-ok")
    mid = _mid("bind-ok")
    await _seed_meeting(mid)

    bound = await bind_meeting(issue["id"], mid)
    assert bound is not None
    assert bound["status"] == "in_progress"
    assert bound["assigned_meeting_id"] == mid


async def test_bind_meeting_scheduled_also_allowed():
    """scheduled 议题同样可绑定（状态机允许 scheduled → in_progress）"""
    issue = await _seed_issue("bind-sched")
    await transition_issue(issue["id"], "scheduled")
    mid = _mid("bind-sched")
    await _seed_meeting(mid)

    bound = await bind_meeting(issue["id"], mid)
    assert bound is not None
    assert bound["status"] == "in_progress"


async def test_bind_meeting_wrong_status_returns_none():
    """已 in_progress（已被其他会议绑定）→ 返回 None，不覆盖（非正向，防并发双绑）"""
    issue = await _seed_issue("bind-bad")
    mid_a = _mid("bind-a")
    mid_b = _mid("bind-b")
    await _seed_meeting(mid_a)
    await _seed_meeting(mid_b)

    assert await bind_meeting(issue["id"], mid_a) is not None
    assert await bind_meeting(issue["id"], mid_b) is None  # 第二次绑定被拒
    got = await issue_dao.get_issue(issue["id"])
    assert got is not None and got["assigned_meeting_id"] == mid_a  # 仍指向第一次的会议

    # 不存在的议题 → None
    assert await bind_meeting("issue-no-such", mid_a) is None


# ---------- resolve_issue（产物发布挂钩） ----------


async def test_resolve_issue_with_artifact():
    """in_progress 议题以产物凭证闭环 → resolved"""
    issue = await _seed_issue("resolve-ok")
    mid = _mid("resolve-ok")
    await _seed_meeting(mid)
    artifact = await artifact_dao.publish_artifact(meeting_id=mid, artifact_type="adr", version=1)
    await bind_meeting(issue["id"], mid)

    resolved = await resolve_issue(issue["id"], artifact["id"])
    assert resolved is not None
    assert resolved["status"] == "resolved"
    assert resolved["resolution_artifact_id"] == artifact["id"]


async def test_resolve_issue_missing_artifact_rejected():
    """空凭证闭环 → 拒绝返回 None，状态不变（非正向，闭环凭证红线）"""
    issue = await _seed_issue("resolve-noart")
    assert await resolve_issue(issue["id"], "") is None
    got = await issue_dao.get_issue(issue["id"])
    assert got is not None and got["status"] == "open"


async def test_resolve_issue_terminal_silent_skip():
    """已终态议题闭环 → 静默返回 None（幂等挂钩语义，非正向）"""
    issue = await _seed_issue("resolve-term")
    await transition_issue(issue["id"], "wontfix")
    assert await resolve_issue(issue["id"], "art-fake-id") is None
    got = await issue_dao.get_issue(issue["id"])
    assert got is not None and got["status"] == "wontfix"


# ---------- release_issue（中止/删除挂钩） ----------


async def test_release_issue_in_progress_to_open():
    """in_progress 释放回池 → open；assigned_meeting_id 保留供追溯"""
    issue = await _seed_issue("release-ok")
    mid = _mid("release-ok")
    await _seed_meeting(mid)
    await bind_meeting(issue["id"], mid)

    released = await release_issue(issue["id"])
    assert released is not None
    assert released["status"] == "open"
    assert released["assigned_meeting_id"] == mid  # 保留追溯


async def test_release_issue_wrong_status_returns_none():
    """open（未绑定）状态释放 → None，状态不变（非正向）"""
    issue = await _seed_issue("release-bad")
    assert await release_issue(issue["id"]) is None
    got = await issue_dao.get_issue(issue["id"])
    assert got is not None and got["status"] == "open"
    assert await release_issue("issue-no-such") is None
