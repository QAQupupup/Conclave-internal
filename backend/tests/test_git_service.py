"""会议工作区 git 护栏单元测试（ADR-017 Phase 3 / T3.5，决策 I12/I13）。

覆盖：
- commit_workspace：无 .git 自动 init + 提交 / bot 身份 / Conventional Commits
  消息 / 无变更返回 committed=False / 临时文件排除（.gitignore 幂等）/
  非法会议 ID 与越界拒绝（非正向）/ 主题截断（边界）
- diff_summary：非 git 仓库零值（边界）/ 变更清单与未推送提交数统计
- push_repo：非 git 仓库 / 无远端拒绝（非正向）/ 本地裸仓库推送成功

测试在容器内使用真实 git 二进制（Dockerfile 已安装）；
workspace_root 经 monkeypatch 指向 tmp_path，不污染真实工作区。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.config import Settings
from app.services.git_service import (
    GitPushError,
    GitServiceError,
    commit_workspace,
    diff_summary,
    push_repo,
)


def _patch_ws_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """把 settings.workspace_root 指向 tmp_path 下的独立目录。"""
    import app.config as config_mod

    ws_root = tmp_path / "wsroot"
    ws_root.mkdir()
    monkeypatch.setattr(
        config_mod,
        "settings",
        Settings(workspace_root=str(ws_root), memory_enabled=False),
    )
    return ws_root


def _mk_workspace(ws_root: Path, meeting_id: str, files: dict[str, str] | None = None) -> Path:
    """创建会议工作区并写入初始文件。"""
    ws = ws_root / meeting_id
    ws.mkdir(parents=True, exist_ok=True)
    for name, content in (files or {}).items():
        p = ws / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return ws


def _git(ws: Path, *args: str) -> str:
    """测试验证用 git 调用（非被测代码，直接同步执行）。"""
    out = subprocess.run(  # noqa: S603 — 静态参数列表无 shell，仅测试夹具
        ["git", "-C", str(ws), *args],  # noqa: S607 — git 为容器内 PATH 工具，无需绝对路径
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    return out.stdout.strip()


# ---------- commit_workspace ----------


async def test_commit_workspace_init_and_commit(monkeypatch, tmp_path):
    """无 .git 时自动 init 并以 bot 身份提交（Conventional Commits 消息）"""
    ws_root = _patch_ws_root(monkeypatch, tmp_path)
    ws = _mk_workspace(ws_root, "mtg-git-commit-1", {"tests/test_a.py": "def test_x():\n    assert True\n"})

    info = await commit_workspace("mtg-git-commit-1", topic="测试套件归档")

    assert info["committed"] is True
    assert len(info["commit_sha"]) == 12
    assert info["message"] == "test(mtg-git): 测试套件归档"
    # bot 身份（I12：仅本地配置，不污染全局）
    assert _git(ws, "log", "-1", "--format=%an") == "conclave-bot"
    assert _git(ws, "log", "-1", "--format=%ae") == "conclave-bot@conclave.local"
    # stat 摘要非空
    assert info["stat"]


async def test_commit_workspace_excludes_temp_files(monkeypatch, tmp_path):
    """临时文件（__pycache__/.pytest_cache）经 .gitignore 排除，不进入提交"""
    ws_root = _patch_ws_root(monkeypatch, tmp_path)
    ws = _mk_workspace(
        ws_root,
        "mtg-git-ignore",
        {
            "tests/test_a.py": "def test_x():\n    assert True\n",
            "__pycache__/cached.py": "binary",
            ".pytest_cache/v/cache": "{}",
        },
    )

    await commit_workspace("mtg-git-ignore")

    tracked = _git(ws, "ls-files")
    assert "tests/test_a.py" in tracked
    assert "__pycache__" not in tracked
    assert ".pytest_cache" not in tracked
    # .gitignore 自身入库且包含排除模式
    gi = (ws / ".gitignore").read_text(encoding="utf-8")
    for pattern in (".pytest_cache/", "__pycache__/", "*.pyc", ".conclave/"):
        assert pattern in gi


async def test_commit_workspace_no_changes_returns_false(monkeypatch, tmp_path):
    """二次提交无变更 → committed=False，不建空提交（边界）"""
    ws_root = _patch_ws_root(monkeypatch, tmp_path)
    _mk_workspace(ws_root, "mtg-git-noop", {"a.txt": "hello"})

    first = await commit_workspace("mtg-git-noop")
    second = await commit_workspace("mtg-git-noop")

    assert first["committed"] is True
    assert second["committed"] is False
    assert second["reason"] == "no_changes"
    # 仓库内仅一次提交
    ws = ws_root / "mtg-git-noop"
    assert _git(ws, "rev-list", "--count", "HEAD") == "1"


async def test_commit_workspace_default_message_without_topic(monkeypatch, tmp_path):
    """未提供主题时使用默认归档消息"""
    ws_root = _patch_ws_root(monkeypatch, tmp_path)
    _mk_workspace(ws_root, "mtg-git-msg", {"a.txt": "x"})

    info = await commit_workspace("mtg-git-msg")
    assert info["message"] == "test(mtg-git): 会议测试产出归档"


async def test_commit_workspace_topic_truncated_to_80(monkeypatch, tmp_path):
    """超长主题截断到 80 字符（边界）"""
    ws_root = _patch_ws_root(monkeypatch, tmp_path)
    _mk_workspace(ws_root, "mtg-git-long", {"a.txt": "x"})

    info = await commit_workspace("mtg-git-long", topic="长" * 200)
    prefix = "test(mtg-git): "
    assert info["message"].startswith(prefix)
    assert len(info["message"]) == len(prefix) + 80


async def test_commit_workspace_rejects_invalid_meeting_id(monkeypatch, tmp_path):
    """非法会议 ID（路径穿越/特殊字符/空）直接拒绝（非正向）"""
    _patch_ws_root(monkeypatch, tmp_path)
    for bad_id in ("../escape", "mtg;rm -rf", "a/b", ""):
        with pytest.raises(GitServiceError):
            await commit_workspace(bad_id)


async def test_commit_workspace_missing_workspace_raises(monkeypatch, tmp_path):
    """工作区不存在 → GitServiceError（非正向）"""
    _patch_ws_root(monkeypatch, tmp_path)
    with pytest.raises(GitServiceError, match="不存在"):
        await commit_workspace("mtg-ghost-workspace")


# ---------- diff_summary ----------


async def test_diff_summary_non_git_repo_returns_zero_values(monkeypatch, tmp_path):
    """非 git 仓库：is_git_repo=False 其余零值（边界）"""
    ws_root = _patch_ws_root(monkeypatch, tmp_path)
    _mk_workspace(ws_root, "mtg-git-norepo", {"a.txt": "x"})

    summary = await diff_summary("mtg-git-norepo")
    assert summary == {
        "is_git_repo": False,
        "changed_files": [],
        "unpushed_commits": 0,
        "remote": None,
    }


async def test_diff_summary_tracks_changes_and_unpushed(monkeypatch, tmp_path):
    """已提交 + 新增未跟踪文件：变更清单与未推送提交数正确"""
    ws_root = _patch_ws_root(monkeypatch, tmp_path)
    _mk_workspace(ws_root, "mtg-git-diff", {"a.txt": "x"})
    await commit_workspace("mtg-git-diff")
    (ws_root / "mtg-git-diff" / "new_file.py").write_text("y = 1", encoding="utf-8")

    summary = await diff_summary("mtg-git-diff")
    assert summary["is_git_repo"] is True
    assert any("new_file.py" in line for line in summary["changed_files"])
    assert summary["unpushed_commits"] == 1  # 无远端 → 全部提交数
    assert summary["remote"] is None


# ---------- push_repo ----------


async def test_push_repo_rejects_non_git_workspace(monkeypatch, tmp_path):
    """非 git 仓库无法推送 → GitPushError（非正向）"""
    ws_root = _patch_ws_root(monkeypatch, tmp_path)
    _mk_workspace(ws_root, "mtg-git-nopush", {"a.txt": "x"})
    with pytest.raises(GitPushError, match="不是 git 仓库"):
        await push_repo("mtg-git-nopush")


async def test_push_repo_rejects_without_remote(monkeypatch, tmp_path):
    """git 仓库但无 remote → GitPushError（非正向）"""
    ws_root = _patch_ws_root(monkeypatch, tmp_path)
    _mk_workspace(ws_root, "mtg-git-noremote", {"a.txt": "x"})
    await commit_workspace("mtg-git-noremote")
    with pytest.raises(GitPushError, match="远端"):
        await push_repo("mtg-git-noremote")


async def test_push_repo_success_to_local_bare_remote(monkeypatch, tmp_path):
    """配置本地裸仓库远端后推送成功，远端收到提交"""
    ws_root = _patch_ws_root(monkeypatch, tmp_path)
    ws = _mk_workspace(ws_root, "mtg-git-push", {"a.txt": "x"})
    await commit_workspace("mtg-git-push")

    # 测试夹具：裸仓库作为远端
    bare = tmp_path / "remote.git"
    subprocess.run(  # noqa: S603 — 静态参数列表无 shell，仅测试夹具
        ["git", "init", "--bare", str(bare)],  # noqa: S607 — git 为容器内 PATH 工具
        capture_output=True,
        check=True,
        timeout=60,
    )
    _git(ws, "remote", "add", "origin", str(bare))

    result = await push_repo("mtg-git-push")
    assert result["pushed_to"].startswith("origin/")
    # 远端仓库收到的提交与工作区 HEAD 一致
    bare_head = subprocess.run(  # noqa: S603 — 静态参数列表无 shell，仅测试夹具
        ["git", "--git-dir", str(bare), "rev-parse", "HEAD"],  # noqa: S607 — git 为容器内 PATH 工具
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    assert bare_head.stdout.strip() == _git(ws, "rev-parse", "HEAD")
