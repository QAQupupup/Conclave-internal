"""议题合入 main 流程（ADR-017 D11，Phase 4 第 5 条）。

两阶段确认（同 D8 push 护栏哲学）：

1. **预览**（``preview_merge``，confirm=False）：校验合入上下文 → 会议仓库
   克隆未提交变更自动提交（D8：commit 可自动）→ 共享克隆内干跑合并 →
   返回 diff 摘要 / 冲突清单，**不落任何状态**；
2. **执行**（``execute_merge``，confirm=True）：正式合并 → push 到远端
   ``default_branch`` → 议题置 ``resolved``（挂闭环凭证）→ 触发 ADR-018 D13
   索引增量重摄（fire-and-forget，失败不回滚合入）。

合入目标 = 项目共享克隆（``workspace/projects/{project_id}/repo``，跟踪
``default_branch``；ADR-017 Phase 4 第 2 条仓库缓存的最小落地，按需创建）。
合入源 = 议题执行会议 workspace 内的仓库克隆（``_maybe_ingest_project_repo``
植入）。合入冲突不自动解决：议题置 ``conflict`` 态交回用户（D11）。

安全约束沿用 git_service：受控子进程无 shell、路径越界防护、
``GIT_TERMINAL_PROMPT=0`` 凭据缺失快速失败。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.dao import issue_dao, project_dao
from app.observability.log_bus import log_bus
from app.services.git_service import GIT_PUSH_TIMEOUT, _run_git, commit_repo, ensure_bot_identity, push_branch

# 克隆/抓取/合并可能涉及大仓库与网络，对齐 code.py 的 300s clone 超时
GIT_MERGE_TIMEOUT = 300

# 允许发起合入的议题状态：in_progress（会议已完成待合入）/ conflict（冲突处置后重试）
MERGEABLE_STATUSES = ("in_progress", "conflict")

# project_id / meeting_id 合法字符集（与 git_service 会议 ID 校验一致）
_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")

_LOGGER = "services.merge_service"


class MergeServiceError(Exception):
    """合入流程业务失败（上下文缺失/状态不符/git 操作失败）。"""


class MergeNotFoundError(MergeServiceError):
    """议题/项目不存在或跨租户（路由层转 404）。"""


class MergeConflictError(MergeServiceError):
    """合入冲突（议题已置 conflict 态；路由层转 409 并附冲突文件清单）。"""

    def __init__(self, message: str, conflicts: list[str]) -> None:
        super().__init__(message)
        self.conflicts = conflicts


def shared_clone_dir(project_id: str) -> Path:
    """项目共享克隆目录（workspace/projects/{project_id}/repo）+ 越界防护。"""
    from app.config import settings

    if not project_id or not _ID_RE.match(project_id):
        raise MergeServiceError(f"非法项目 ID: {str(project_id)[:50]}")
    ws_root = Path(settings.workspace_root).resolve()
    d = (ws_root / "projects" / project_id / "repo").resolve()
    try:
        d.relative_to(ws_root)
    except ValueError:
        raise MergeServiceError("共享克隆路径越界") from None
    return d


async def ensure_shared_clone(project: dict[str, Any]) -> Path:
    """获取项目共享克隆：不存在则克隆，存在则 fetch + ff-only 追平远端。

    ff-only 失败（本地分叉）时报错交回人工——共享克隆是基线缓存，
    不应携带未推送的本地提交，静默强推会丢数据。

    测试接缝：集成测试 monkeypatch 本函数改接本地 bare 仓库（repo_url
    的 http/https 克隆在测试环境不可达）。
    """
    repo_url = project.get("repo_url")
    if not repo_url:
        raise MergeServiceError("项目未绑定仓库，无需合入")
    branch = str(project.get("default_branch") or "main")
    dest = shared_clone_dir(str(project["id"]))
    if not (dest / ".git").exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        rc, _, err = await _run_git(
            dest.parent, ["clone", "--quiet", "--branch", branch, str(repo_url), "repo"], GIT_MERGE_TIMEOUT
        )
        if rc != 0:
            raise MergeServiceError(f"共享克隆失败: {err[:200]}")
        return dest
    rc, _, err = await _run_git(dest, ["fetch", "--quiet", "origin", branch], GIT_MERGE_TIMEOUT)
    if rc != 0:
        raise MergeServiceError(f"共享克隆拉取远端失败: {err[:200]}")
    rc, _, err = await _run_git(dest, ["merge", "--ff-only", "--quiet", f"origin/{branch}"], GIT_MERGE_TIMEOUT)
    if rc != 0:
        raise MergeServiceError(f"共享克隆与 origin/{branch} 分叉，需人工处理: {err[:150]}")
    return dest


async def _find_meeting_repo(meeting_id: str, repo_url: str | None) -> Path:
    """定位会议 workspace 内的项目仓库克隆（含 ``.git`` 的子目录）。

    多个候选时优先 origin URL 与项目 repo_url 匹配者（去 ``.git`` 后缀比较）；
    无候选抛错。
    """
    from app.config import settings

    if not meeting_id or not _ID_RE.match(meeting_id):
        raise MergeServiceError(f"非法会议 ID: {str(meeting_id)[:50]}")
    ws_root = Path(settings.workspace_root).resolve()
    meeting_dir = (ws_root / meeting_id).resolve()
    try:
        meeting_dir.relative_to(ws_root)
    except ValueError:
        raise MergeServiceError("会议工作区路径越界") from None
    if not meeting_dir.is_dir():
        raise MergeNotFoundError("议题执行会议的工作区不存在")
    candidates = [d for d in meeting_dir.iterdir() if d.is_dir() and (d / ".git").exists()]
    if not candidates:
        raise MergeServiceError("会议工作区内无仓库克隆，无法合入（需先经议题会议摄入仓库）")
    if repo_url and len(candidates) > 1:
        want = str(repo_url).rstrip("/").removesuffix(".git")
        for d in candidates:
            rc, out, _ = await _run_git(d, ["remote", "get-url", "origin"], GIT_PUSH_TIMEOUT)
            if rc == 0 and out.strip().rstrip("/").removesuffix(".git") == want:
                return d
    return candidates[0]


async def validate_merge_context(issue_id: str) -> dict[str, Any]:
    """合入上下文校验：议题可合入 + 有执行会议 + 项目绑定仓库 + 会议仓库在场。

    Returns:
        ``{issue, project, meeting_id, source_repo}``

    Raises:
        MergeNotFoundError: 议题/项目不存在或跨租户、会议工作区缺失。
        MergeServiceError: 状态不可合入/未绑会议/项目未绑仓库/无仓库克隆。
    """
    issue = await issue_dao.get_issue(issue_id)
    if issue is None:
        raise MergeNotFoundError("议题不存在")
    status = str(issue["status"])
    if status not in MERGEABLE_STATUSES:
        raise MergeServiceError(f"议题当前状态 {status} 不可合入（仅 {'/'.join(MERGEABLE_STATUSES)}）")
    meeting_id = issue.get("assigned_meeting_id")
    if not meeting_id:
        raise MergeServiceError("议题未绑定执行会议，无法定位合入源")
    project = await project_dao.get_project(str(issue["project_id"]))
    if project is None:
        raise MergeNotFoundError("议题归属项目不存在或跨租户")
    if not project.get("repo_url"):
        raise MergeServiceError("项目未绑定仓库，无需合入")
    source_repo = await _find_meeting_repo(str(meeting_id), project.get("repo_url"))
    return {"issue": issue, "project": project, "meeting_id": str(meeting_id), "source_repo": source_repo}


def _source_commit_message(issue: dict[str, Any]) -> str:
    """会议仓库自动提交消息（Conventional Commits，D8 commit 可自动）。"""
    scope = str(issue["id"])[:8].rstrip("-")
    title = str(issue.get("title") or "").strip().replace("\n", " ")[:80] or "议题产出归档"
    return f"feat(issue-{scope}): {title}"


async def _collect_conflicts(shared: Path) -> list[str]:
    """采集合并冲突文件清单（``--diff-filter=U``，≤100 条）。"""
    _, conf_out, _ = await _run_git(shared, ["diff", "--name-only", "--diff-filter=U"], GIT_MERGE_TIMEOUT)
    return [line.strip() for line in conf_out.splitlines() if line.strip()][:100]


async def _dry_run_merge(shared: Path, source_repo: Path) -> dict[str, Any]:
    """共享克隆内干跑合并：fetch 源 HEAD → 试合并 → 采集结果 → 恢复现场。

    预览语义：无论成功与否，退出时共享克隆状态与进入时一致（merge --abort）。
    失败语义：仅内容冲突才报 ``mergeable=False``；无冲突文件的非零退出
    （如身份缺失/仓库损坏）是 git 操作失败，抛错并附 stderr，避免误报冲突。
    """
    rc, _, err = await _run_git(shared, ["fetch", "--quiet", str(source_repo), "HEAD"], GIT_MERGE_TIMEOUT)
    if rc != 0:
        raise MergeServiceError(f"抓取合入源失败: {err[:200]}")
    rc, _, merge_err = await _run_git(shared, ["merge", "--no-commit", "--no-ff", "FETCH_HEAD"], GIT_MERGE_TIMEOUT)
    if rc != 0:
        conflicts = await _collect_conflicts(shared)
        await _run_git(shared, ["merge", "--abort"], GIT_MERGE_TIMEOUT)
        if not conflicts:
            raise MergeServiceError(f"干跑合并失败（非内容冲突）: {(merge_err or '未知错误')[:200]}")
        return {"mergeable": False, "changed_files": [], "conflicts": conflicts}
    _, stat_out, _ = await _run_git(shared, ["diff", "--cached", "--name-status"], GIT_MERGE_TIMEOUT)
    changed = [line for line in stat_out.splitlines() if line.strip()][:200]
    await _run_git(shared, ["merge", "--abort"], GIT_MERGE_TIMEOUT)
    return {"mergeable": True, "changed_files": changed, "conflicts": []}


async def preview_merge(issue_id: str) -> dict[str, Any]:
    """合入预览（confirm=False 分支）：干跑合并，返回摘要，不落状态。"""
    ctx = await validate_merge_context(issue_id)
    shared = await ensure_shared_clone(ctx["project"])
    # 容器无全局 git 配置，合并（含 --no-commit 干跑）需本地 bot 身份
    await ensure_bot_identity(shared)
    # D8：commit 可自动——会议仓库未提交变更先落提交，否则不会进入合入
    commit_info = await commit_repo(ctx["source_repo"], _source_commit_message(ctx["issue"]))
    result = await _dry_run_merge(shared, ctx["source_repo"])
    return {
        "mode": "preview",
        "issue_id": issue_id,
        "project_id": str(ctx["project"]["id"]),
        "meeting_id": ctx["meeting_id"],
        "branch": str(ctx["project"].get("default_branch") or "main"),
        "source_committed": bool(commit_info.get("committed")),
        **result,
    }


async def _mark_conflict(issue_id: str) -> None:
    """合入冲突时置议题 conflict 态（条件更新；状态已变则仅记日志）。"""
    updated = await issue_dao.transition_status(issue_id, expected_statuses=MERGEABLE_STATUSES, new_status="conflict")
    if updated is None:
        log_bus.warning("议题置 conflict 态失败（状态已并发变更）", logger=_LOGGER, extra={"issue_id": issue_id})
    else:
        log_bus.info("合入冲突，议题已置 conflict 态交回用户", logger=_LOGGER, extra={"issue_id": issue_id})


def _trigger_index_resync(project: dict[str, Any], shared: Path, meeting_id: str) -> None:
    """ADR-018 D13 挂钩：合入 main 成功后对共享克隆增量重摄（fire-and-forget）。

    索引源 = 共享克隆（合入后恒等于项目基线）；``ingest_repo_semantic`` 按
    内容哈希四分类增量（变更删旧插新、已删文件清理），等价于按 git diff
    变更文件重摄，且自带 D12 串行锁。重摄失败不回滚合入（合入是既成事实，
    索引是派生缓存——ADR-018 索引同步时窗）。

    租户/项目/会议 ID 在请求上下文内捕获后再入后台任务（后台任务不访问
    contextvar，同 meetings.py _maybe_ingest_project_repo 纪律）。
    """
    from app.tenants.context import get_tenant_id
    from app.utils.tasks import create_supervised_task

    tenant_id = get_tenant_id() or 0  # 系统命名空间，同 routers/code.py _resolve_tenant_id
    project_id = str(project["id"])

    async def _resync() -> None:
        from app.rag.semantic_ingest import ingest_repo_semantic

        try:
            result = await ingest_repo_semantic(
                shared, meeting_id=meeting_id, tenant_id=tenant_id, project_id=project_id
            )
            log_bus.info(
                f"合入后索引增量重摄完成: docs={result.get('docs_ingested', 0)}",
                logger=_LOGGER,
                extra={"project_id": project_id, "meeting_id": meeting_id},
            )
        except Exception as e:
            log_bus.warning(
                f"合入后索引重摄失败（不影响合入结果，可重试）: {str(e)[:200]}",
                logger=_LOGGER,
                extra={"project_id": project_id, "meeting_id": meeting_id},
            )

    create_supervised_task(_resync(), name=f"merge-index-resync-{project_id[:8]}")


async def execute_merge(issue_id: str) -> dict[str, Any]:
    """合入执行（confirm=True 分支）：合并 → push → 议题闭环 → D13 重摄。

    Raises:
        MergeNotFoundError: 议题/项目不存在或跨租户。
        MergeConflictError: 合并冲突（议题已置 conflict 态）。
        MergeServiceError: 上下文缺失/闭环凭证缺失/流转竞争失败。
        GitServiceError/GitPushError: git 原语失败（路由层转 409；push 失败时
            合入提交保留在共享克隆本地，可重试）。
    """
    ctx = await validate_merge_context(issue_id)
    issue = ctx["issue"]
    artifact_id = issue.get("resolution_artifact_id")
    if not artifact_id:
        raise MergeServiceError("缺少闭环凭证（resolution_artifact_id），拒绝合入")
    branch = str(ctx["project"].get("default_branch") or "main")

    shared = await ensure_shared_clone(ctx["project"])
    # 容器无全局 git 配置，合并提交需本地 bot 身份
    await ensure_bot_identity(shared)
    await commit_repo(ctx["source_repo"], _source_commit_message(issue))

    rc, _, err = await _run_git(shared, ["fetch", "--quiet", str(ctx["source_repo"]), "HEAD"], GIT_MERGE_TIMEOUT)
    if rc != 0:
        raise MergeServiceError(f"抓取合入源失败: {err[:200]}")
    short = str(issue_id)[:8].rstrip("-")
    title = str(issue.get("title") or "").strip().replace("\n", " ")[:80] or "议题合入"
    merge_msg = f"feat(issue-{short}): {title}（合入 {branch}）"
    rc, _, err = await _run_git(shared, ["merge", "--no-ff", "-m", merge_msg, "FETCH_HEAD"], GIT_MERGE_TIMEOUT)
    if rc != 0:
        conflicts = await _collect_conflicts(shared)
        await _run_git(shared, ["merge", "--abort"], GIT_MERGE_TIMEOUT)
        if not conflicts:
            # 非内容冲突的 git 失败（身份/仓库问题）：不置 conflict 态，议题状态不变
            raise MergeServiceError(f"合入失败（非内容冲突）: {(err or '未知错误')[:200]}")
        await _mark_conflict(issue_id)
        raise MergeConflictError(f"合入冲突（{len(conflicts)} 个文件），议题已置 conflict 态", conflicts)

    _, sha_out, _ = await _run_git(shared, ["rev-parse", "HEAD"], GIT_MERGE_TIMEOUT)
    _, stat_out, _ = await _run_git(shared, ["diff", "--name-status", "HEAD^1", "HEAD"], GIT_MERGE_TIMEOUT)
    changed = [line for line in stat_out.splitlines() if line.strip()][:200]

    # D8/D11：push 进共享空间——显式确认即路由层 confirm=True 参数
    push_result = await push_branch(shared, "origin", branch)

    # 合入成功 → 议题闭环（D11）。经服务层状态机校验（含并发条件更新）
    from app.services.issue_service import IssueTransitionError, transition_issue

    try:
        updated_issue = await transition_issue(issue_id, "resolved", str(artifact_id))
    except IssueTransitionError as exc:
        raise MergeServiceError(f"合入成功但议题闭环失败: {exc}") from exc

    _trigger_index_resync(ctx["project"], shared, ctx["meeting_id"])
    log_bus.info(
        f"议题合入 {branch} 成功: sha={sha_out.strip()[:12]}",
        logger=_LOGGER,
        extra={"issue_id": issue_id, "project_id": str(ctx["project"]["id"]), "pushed_to": push_result["pushed_to"]},
    )
    return {
        "mode": "execute",
        "merged": True,
        "issue_id": issue_id,
        "project_id": str(ctx["project"]["id"]),
        "meeting_id": ctx["meeting_id"],
        "branch": branch,
        "merge_commit_sha": sha_out.strip()[:12],
        "pushed_to": push_result["pushed_to"],
        "changed_files": changed,
        "issue_status": updated_issue["status"],
    }
