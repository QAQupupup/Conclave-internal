"""git_service 路径级原语测试（ADR-017 D11 合入流程基座）。

真实 git 仓库往返（testing-rules §3 配对函数往返红线）：
- commit_repo：提交 → 短哈希 + bot 身份 + 幂等（无变更不再提交）
- push_branch：推送 → 远端分支可见；坏远端 → GitPushError

越界防护（非正向）：workspace_root 之外的路径一律拒绝。
settings 为 frozen dataclass，测试整体替换 app.config.settings 对象
（git_service 各函数在调用时惰性读取，补丁即时生效）。
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.git_service import GitPushError, GitServiceError, commit_repo, push_branch


@pytest.fixture
def ws(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """把 workspace_root 指向临时目录，返回该目录。"""
    monkeypatch.setattr("app.config.settings", SimpleNamespace(workspace_root=str(tmp_path)))
    return tmp_path


def _git(cwd: Path, *args: str) -> str:
    """同步执行 git 并返回 stdout（失败即测试失败）。"""
    out = subprocess.run(  # noqa: S603 — 静态参数列表无 shell，仅测试夹具
        ["git", *args],  # noqa: S607 — git 为容器内 PATH 工具
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout.strip()


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "--quiet", "--initial-branch=main")


class TestCommitRepo:
    """commit_repo 往返与边界。"""

    @pytest.mark.asyncio
    async def test_commit_round_trip_and_idempotent(self, ws: Path) -> None:
        """提交往返：变更 → committed=True + 12 位短哈希 + bot 身份；无变更 → committed=False。"""
        repo = ws / "repo"
        _init_repo(repo)
        (repo / "feature.txt").write_text("v1\n", encoding="utf-8")

        result = await commit_repo(repo, "feat(issue-test): 首次提交")
        assert result["committed"] is True
        assert len(result["commit_sha"]) == 12

        log = _git(repo, "log", "-1", "--format=%an|%s")
        assert log == "conclave-bot|feat(issue-test): 首次提交"

        # 往返幂等：无变更不再建空提交
        again = await commit_repo(repo, "feat(issue-test): 不应产生")
        assert again["committed"] is False
        assert again["reason"] == "no_changes"

    @pytest.mark.asyncio
    async def test_commit_empty_message_rejected(self, ws: Path) -> None:
        """空提交消息 → GitServiceError（非正向）。"""
        repo = ws / "repo"
        _init_repo(repo)
        (repo / "a.txt").write_text("x\n", encoding="utf-8")
        with pytest.raises(GitServiceError, match="提交消息"):
            await commit_repo(repo, "   ")

    @pytest.mark.asyncio
    async def test_commit_outside_workspace_rejected(self, ws: Path, tmp_path_factory: pytest.TempPathFactory) -> None:
        """workspace_root 之外的仓库 → 越界拒绝（非正向）。"""
        outside = tmp_path_factory.mktemp("outside") / "repo"
        _init_repo(outside)
        with pytest.raises(GitServiceError, match="越界"):
            await commit_repo(outside, "feat(x): 越界提交")

    @pytest.mark.asyncio
    async def test_commit_non_repo_rejected(self, ws: Path) -> None:
        """无 .git 的普通目录 → 拒绝（非正向）。"""
        plain = ws / "plain"
        plain.mkdir()
        with pytest.raises(GitServiceError, match="不是 git 仓库"):
            await commit_repo(plain, "feat(x): 非仓库")


class TestPushBranch:
    """push_branch 往返与边界。"""

    @pytest.mark.asyncio
    async def test_push_round_trip_to_bare_origin(self, ws: Path, tmp_path_factory: pytest.TempPathFactory) -> None:
        """推送往返：本地提交 → push → bare 远端分支可见同一提交。"""
        bare = tmp_path_factory.mktemp("remotes") / "origin.git"
        subprocess.run(  # noqa: S603 — 静态参数列表无 shell，仅测试夹具
            ["git", "init", "--bare", "--quiet", "--initial-branch=main", str(bare)],  # noqa: S607 — git 为容器内 PATH 工具
            check=True,
        )

        repo = ws / "repo"
        _git(ws, "clone", "--quiet", str(bare), "repo")
        (repo / "feature.txt").write_text("v1\n", encoding="utf-8")
        commit = await commit_repo(repo, "feat(issue-test): 待推送提交")
        assert commit["committed"] is True

        result = await push_branch(repo, "origin", "main")
        assert result["pushed_to"] == "origin/main"

        remote_head = subprocess.run(  # noqa: S603 — 静态参数列表无 shell，仅测试夹具
            ["git", "--git-dir", str(bare), "rev-parse", "main"],  # noqa: S607 — git 为容器内 PATH 工具
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        local_head = _git(repo, "rev-parse", "HEAD")
        assert remote_head == local_head

    @pytest.mark.asyncio
    async def test_push_bad_remote_raises(self, ws: Path, tmp_path_factory: pytest.TempPathFactory) -> None:
        """推送到不存在的远端 → GitPushError（非正向）。"""
        bare = tmp_path_factory.mktemp("remotes2") / "origin.git"
        subprocess.run(  # noqa: S603 — 静态参数列表无 shell，仅测试夹具
            ["git", "init", "--bare", "--quiet", "--initial-branch=main", str(bare)],  # noqa: S607 — git 为容器内 PATH 工具
            check=True,
        )
        repo = ws / "repo"
        _git(ws, "clone", "--quiet", str(bare), "repo")
        (repo / "f.txt").write_text("x\n", encoding="utf-8")
        await commit_repo(repo, "feat(x): 提交")
        with pytest.raises(GitPushError, match="push 失败"):
            await push_branch(repo, "no-such-remote", "main")
