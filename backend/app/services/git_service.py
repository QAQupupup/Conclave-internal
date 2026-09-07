"""会议工作区 git 护栏（ADR-017 Phase 3，T3.5，决策 I12/I13）。

职责：
- ``commit_workspace``：会议工作区内自动提交（bot 身份、Conventional
  Commits、临时文件排除）。无 ``.git`` 时先 init。
- ``diff_summary``：未提交变更 + 未推送提交数摘要（供 push dry-run 展示）。
- ``push_repo``：推送到远端（路由层要求显式确认参数，ADR-017 D8）。
- 路径级原语（ADR-017 D11 合入流程）：``commit_repo`` / ``push_branch``，
  对 workspace 内任意仓库目录操作（越界防护同会议级）。

安全约束：
- 子进程参数列表无 shell（对齐 ``routers/code.py:_run_git`` 模式）
- ``GIT_TERMINAL_PROMPT=0``：凭据缺失时快速失败而非挂起等输入
- meeting_id 字符集校验 + workspace 包含校验（必须落在
  ``settings.workspace_root`` 内），防路径穿越
- 错误输出截断，不泄露完整 stderr

注意：工作区内如有仓库摄入留下的嵌套克隆（自带 ``.git``），git 会按
嵌入仓库（gitlink）处理——Phase 3 接受该行为，Phase 4 共享克隆
（ADR-017 D11）落地后由 worktree 模式取代。
"""

from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path
from typing import Any

# bot 身份：仅写入工作区本地 git 配置（--local），不污染全局
GIT_BOT_NAME = "conclave-bot"
GIT_BOT_EMAIL = "conclave-bot@conclave.local"

# 超时（秒）：本地提交操作轻量取 60s；push 走网络取 120s。
# 对齐 code.py 受控子进程超时策略（到点 kill 防挂死）。
GIT_COMMIT_TIMEOUT = 60
GIT_PUSH_TIMEOUT = 120

# 不纳入提交的临时文件模式（幂等写入工作区 .gitignore）
_GITIGNORE_PATTERNS = (".pytest_cache/", "__pycache__/", "*.pyc", ".conclave/")

# meeting_id 合法字符集（与沙箱目录规范一致）：仅字母数字下划线连字符
_MEETING_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


class GitServiceError(Exception):
    """git 护栏操作失败（工作区不存在/越界/git 命令失败）。"""


class GitPushError(GitServiceError):
    """push 专属失败（无远端/推送被拒），路由层转 409。"""


def _workspace_dir(meeting_id: str) -> Path:
    """解析会议工作区目录并防穿越：必须落在 workspace_root 内。"""
    from app.config import settings

    if not meeting_id or not _MEETING_ID_RE.match(meeting_id):
        raise GitServiceError(f"非法会议 ID: {str(meeting_id)[:50]}")
    ws_root = Path(settings.workspace_root).resolve()
    ws = (ws_root / meeting_id).resolve()
    try:
        ws.relative_to(ws_root)
    except ValueError:
        raise GitServiceError("工作区路径越界") from None
    if not ws.is_dir():
        raise GitServiceError("会议工作区不存在")
    return ws


async def _run_git(cwd: Path, args: list[str], timeout: int) -> tuple[int, str, str]:
    """受控 git 子进程：参数列表无 shell，禁交互凭据提示，超时 kill。"""
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    proc = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=str(cwd),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise TimeoutError(f"git {args[0] if args else '?'} 超时（{timeout}s）") from None
    return (
        proc.returncode or 0,
        stdout.decode("utf-8", errors="replace"),
        stderr.decode("utf-8", errors="replace"),
    )


def _ensure_gitignore(ws: Path) -> None:
    """幂等补全工作区 .gitignore：只追加缺失的临时文件模式。"""
    gi = ws / ".gitignore"
    existing = gi.read_text(encoding="utf-8", errors="replace") if gi.exists() else ""
    missing = [p for p in _GITIGNORE_PATTERNS if p not in existing]
    if not missing:
        return
    with gi.open("a", encoding="utf-8") as f:
        if existing and not existing.endswith("\n"):
            f.write("\n")
        f.write("\n".join(missing) + "\n")


async def ensure_bot_identity(repo: Path | str) -> None:
    """仓库本地配置 bot 身份（--local，不污染全局，I12）。

    提交/合并类操作的共同前置：容器通常无全局 git 配置，任何产生提交的
    合并（含 ``--no-commit`` 干跑——git 准备 MERGE_MSG 时提前校验身份）
    都会因 "Committer identity unknown" 直接 rc=128 失败。
    """
    rc, _, err = await _run_git(Path(repo), ["config", "--local", "user.name", GIT_BOT_NAME], GIT_COMMIT_TIMEOUT)
    if rc != 0:
        raise GitServiceError(f"git user.name 配置失败: {err[:200]}")
    rc, _, err = await _run_git(Path(repo), ["config", "--local", "user.email", GIT_BOT_EMAIL], GIT_COMMIT_TIMEOUT)
    if rc != 0:
        raise GitServiceError(f"git user.email 配置失败: {err[:200]}")


async def commit_workspace(meeting_id: str, topic: str = "") -> dict[str, Any]:
    """会议工作区自动提交（bot 身份 + Conventional Commits + 临时文件排除）。

    无 ``.git`` 时先 init；无变更时返回 ``{"committed": False}`` 不建空提交。

    Returns:
        ``{committed, commit_sha?, message?, stat?}``；
        commit_sha 为 12 位短哈希，stat 为 ``git show --stat`` 尾部摘要。

    Raises:
        GitServiceError: 工作区不存在/越界、git init/commit 失败。
    """
    ws = _workspace_dir(meeting_id)
    if not (ws / ".git").exists():
        rc, _, err = await _run_git(ws, ["init", "--quiet"], GIT_COMMIT_TIMEOUT)
        if rc != 0:
            raise GitServiceError(f"git init 失败: {err[:200]}")
    # bot 身份仅本地配置（I12）
    await ensure_bot_identity(ws)
    _ensure_gitignore(ws)

    rc, _, err = await _run_git(ws, ["add", "-A"], GIT_COMMIT_TIMEOUT)
    if rc != 0:
        raise GitServiceError(f"git add 失败: {err[:200]}")
    rc, status_out, _ = await _run_git(ws, ["status", "--porcelain"], GIT_COMMIT_TIMEOUT)
    if rc == 0 and not status_out.strip():
        return {"committed": False, "reason": "no_changes"}

    # Conventional Commits：test(<scope>): <主题截断 80>
    # scope 取 meeting 前 8 位并去掉尾部连字符，避免悬挂 "-"（如 "mtg-git-" → "mtg-git"）
    scope = meeting_id[:8].rstrip("-")
    safe_topic = (topic or "").strip().replace("\n", " ")[:80]
    message = f"test({scope}): {safe_topic}" if safe_topic else f"test({scope}): 会议测试产出归档"
    rc, _, err = await _run_git(ws, ["commit", "-m", message, "--quiet"], GIT_COMMIT_TIMEOUT)
    if rc != 0:
        raise GitServiceError(f"git commit 失败: {err[:200]}")
    _, sha_out, _ = await _run_git(ws, ["rev-parse", "HEAD"], GIT_COMMIT_TIMEOUT)
    _, stat_out, _ = await _run_git(ws, ["show", "--stat", "--format=", "HEAD"], GIT_COMMIT_TIMEOUT)
    return {
        "committed": True,
        "commit_sha": sha_out.strip()[:12],
        "message": message,
        "stat": stat_out.strip()[-500:],
    }


async def diff_summary(meeting_id: str) -> dict[str, Any]:
    """工作区变更摘要（push dry-run 数据源，I13）。

    Returns:
        ``{is_git_repo, changed_files(≤100 条), unpushed_commits, remote}``；
        非 git 仓库时 ``is_git_repo=False`` 其余为零值（路由层据此提示）。
    """
    ws = _workspace_dir(meeting_id)
    empty = {"is_git_repo": False, "changed_files": [], "unpushed_commits": 0, "remote": None}
    if not (ws / ".git").exists():
        return empty
    _, status_out, _ = await _run_git(ws, ["status", "--porcelain"], GIT_COMMIT_TIMEOUT)
    changed = [line.strip() for line in status_out.splitlines() if line.strip()][:100]
    remotes = await _list_remotes(ws)
    remote = remotes[0] if remotes else None
    # 未推送提交数：有 upstream 用 @{u}..HEAD；否则退化为全部提交数
    unpushed = 0
    if remote:
        rc, out, _ = await _run_git(ws, ["rev-list", "--count", "@{u}..HEAD"], GIT_COMMIT_TIMEOUT)
        if rc == 0 and out.strip().isdigit():
            unpushed = int(out.strip())
        else:
            rc, out, _ = await _run_git(ws, ["rev-list", "--count", "HEAD"], GIT_COMMIT_TIMEOUT)
            if rc == 0 and out.strip().isdigit():
                unpushed = int(out.strip())
    else:
        rc, out, _ = await _run_git(ws, ["rev-list", "--count", "HEAD"], GIT_COMMIT_TIMEOUT)
        if rc == 0 and out.strip().isdigit():
            unpushed = int(out.strip())
    return {"is_git_repo": True, "changed_files": changed, "unpushed_commits": unpushed, "remote": remote}


async def _list_remotes(ws: Path) -> list[str]:
    """列出工作区仓库的 remote 名（按声明顺序）。"""
    _, out, _ = await _run_git(ws, ["remote"], GIT_COMMIT_TIMEOUT)
    return [r.strip() for r in out.splitlines() if r.strip()]


async def push_repo(meeting_id: str) -> dict[str, Any]:
    """推送工作区仓库到首个 remote（显式确认由路由层强制，D8/I13）。

    Raises:
        GitPushError: 非 git 仓库 / 无 remote / push 失败。
    """
    ws = _workspace_dir(meeting_id)
    if not (ws / ".git").exists():
        raise GitPushError("工作区不是 git 仓库，无法推送")
    remotes = await _list_remotes(ws)
    if not remotes:
        raise GitPushError("不存在可推送的远端（remote），请先配置 origin")
    remote = remotes[0]
    _, branch_out, _ = await _run_git(ws, ["rev-parse", "--abbrev-ref", "HEAD"], GIT_COMMIT_TIMEOUT)
    branch = branch_out.strip()
    if not branch or branch == "HEAD":
        raise GitPushError("工作区处于游离头指针状态，无法推送")
    rc, out, err = await _run_git(ws, ["push", remote, branch], GIT_PUSH_TIMEOUT)
    if rc != 0:
        raise GitPushError(f"push 失败: {(err or out)[:300]}")
    return {"pushed_to": f"{remote}/{branch}", "output": (out + "\n" + err)[-500:]}


# ---------- 路径级原语（ADR-017 D11 议题合入流程，Phase 4） ----------


def resolve_repo_dir(repo_path: Path | str) -> Path:
    """路径级仓库目录校验与防穿越：必须存在、是 git 仓库、落在 workspace_root 内。

    与 ``_workspace_dir`` 同级的安全边界，但不绑定 meeting_id——
    供合入流程操作会议仓库克隆与项目共享克隆。
    """
    from app.config import settings

    ws_root = Path(settings.workspace_root).resolve()
    p = Path(repo_path).resolve()
    try:
        p.relative_to(ws_root)
    except ValueError:
        raise GitServiceError("仓库路径越界（不在工作区根目录内）") from None
    if not p.is_dir():
        raise GitServiceError("仓库目录不存在")
    if not (p / ".git").exists():
        raise GitServiceError("目标目录不是 git 仓库")
    return p


async def commit_repo(repo_path: Path | str, message: str) -> dict[str, Any]:
    """路径级提交：bot 身份 + 调用方给定消息（Conventional Commits 语义由调用方保证）。

    与 ``commit_workspace`` 的差异：不自动 init（合入源/目标必须已是仓库）、
    不绑定会议字符集、消息完整由调用方提供。无变更时返回 ``{"committed": False}``。

    Returns:
        ``{committed, commit_sha?, message?}``；commit_sha 为 12 位短哈希。

    Raises:
        GitServiceError: 路径越界/非仓库/空消息/git 命令失败。
    """
    repo = resolve_repo_dir(repo_path)
    if not message or not message.strip():
        raise GitServiceError("提交消息不能为空")
    # bot 身份仅本地配置（I12 同策略）
    await ensure_bot_identity(repo)
    rc, _, err = await _run_git(repo, ["add", "-A"], GIT_COMMIT_TIMEOUT)
    if rc != 0:
        raise GitServiceError(f"git add 失败: {err[:200]}")
    rc, status_out, _ = await _run_git(repo, ["status", "--porcelain"], GIT_COMMIT_TIMEOUT)
    if rc == 0 and not status_out.strip():
        return {"committed": False, "reason": "no_changes"}
    rc, _, err = await _run_git(repo, ["commit", "-m", message.strip(), "--quiet"], GIT_COMMIT_TIMEOUT)
    if rc != 0:
        raise GitServiceError(f"git commit 失败: {err[:200]}")
    _, sha_out, _ = await _run_git(repo, ["rev-parse", "HEAD"], GIT_COMMIT_TIMEOUT)
    return {"committed": True, "commit_sha": sha_out.strip()[:12], "message": message.strip()}


async def push_branch(repo_path: Path | str, remote: str = "origin", branch: str | None = None) -> dict[str, Any]:
    """路径级推送：把指定（或当前）分支推到远端。

    D8 红线：显式确认必须由调用方链路强制（合入流程的 confirm 参数）。

    Raises:
        GitPushError: 游离头指针/推送失败。
    """
    repo = resolve_repo_dir(repo_path)
    if branch is None:
        _, branch_out, _ = await _run_git(repo, ["rev-parse", "--abbrev-ref", "HEAD"], GIT_COMMIT_TIMEOUT)
        branch = branch_out.strip()
    if not branch or branch == "HEAD":
        raise GitPushError("处于游离头指针状态，无法推送")
    rc, out, err = await _run_git(repo, ["push", remote, branch], GIT_PUSH_TIMEOUT)
    if rc != 0:
        raise GitPushError(f"push 失败: {(err or out)[:300]}")
    return {"pushed_to": f"{remote}/{branch}", "output": (out + "\n" + err)[-500:]}
