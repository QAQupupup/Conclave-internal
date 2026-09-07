"""议题合入 main 流程端到端测试（ADR-017 D11 + ADR-018 D13 挂钩）。

真实 git bare 远端 + 真实 DB 状态机 + 真实 API；唯一接缝补丁是
``merge_service.ensure_shared_clone``（项目 repo_url 为 https，测试环境
不可达，改接本地 bare 远端——合入/推送/状态机逻辑全部走真实代码）。

覆盖（含非正向，testing-rules §9）：
- 预览 → 执行 快乐路径：变更落远端、议题 resolved、凭证在案
- 预览干跑不落状态（远端 SHA 不变）
- 合入冲突：议题置 conflict 态、409 附冲突清单（预览/执行两条路径）
- 缺闭环凭证 → 409；未绑会议 → 409；议题不存在 → 404
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.dao import artifact_dao
from app.services import merge_service


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _git(cwd: Path, *args: str) -> str:
    out = subprocess.run(  # noqa: S603 — 静态参数列表无 shell，仅测试夹具
        ["git", *args],  # noqa: S607 — git 为容器内 PATH 工具
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout.strip()


def _bare_head(bare: Path) -> str:
    return subprocess.run(  # noqa: S603 — 静态参数列表无 shell，仅测试夹具
        ["git", "--git-dir", str(bare), "rev-parse", "main"],  # noqa: S607 — git 为容器内 PATH 工具
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _make_origin(tmp_path: Path) -> Path:
    """bare origin + 种子提交（main 分支，README.md 基线内容）。"""
    bare = tmp_path / "origin.git"
    subprocess.run(  # noqa: S603 — 静态参数列表无 shell，仅测试夹具
        ["git", "init", "--bare", "--quiet", "--initial-branch=main", str(bare)],  # noqa: S607 — git 为容器内 PATH 工具
        check=True,
    )
    seed = tmp_path / "seed"
    _git(tmp_path, "clone", "--quiet", str(bare), "seed")
    (seed / "README.md").write_text("base line\n", encoding="utf-8")
    _git(seed, "add", "-A")
    _git(seed, "-c", "user.name=seed", "-c", "user.email=seed@test.local", "commit", "-m", "seed", "--quiet")
    _git(seed, "push", "--quiet", "origin", "main")
    return bare


def _seed_artifact(meeting_id: str) -> dict:
    """DAO 发布闭环凭证产物（同 test_projects_issues_api.py 模式）。"""

    async def _do() -> dict:
        return await artifact_dao.publish_artifact(
            meeting_id=meeting_id,
            artifact_type="adr",
            version=1,
            title="合入闭环凭证",
            summary="合入流程测试凭证",
            content={"title": "合入闭环凭证"},
        )

    return asyncio.run(_do())


@pytest.fixture
def scenario(client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """项目（绑仓库）+ 议题 + 绑定会议 + 会议仓库克隆 + 共享克隆接缝补丁。"""
    bare = _make_origin(tmp_path)

    slug = _unique("mrg")
    resp = client.post(
        "/api/projects",
        json={
            "slug": slug,
            "name": "合入测试项目",
            # 目录名 projrepo 与会议工作区手动克隆目录 demo 不同名，
            # 避免后台摄入任务与测试布置竞态
            "repo_url": "https://git.example.invalid/team/projrepo.git",
            "default_branch": "main",
        },
    )
    assert resp.status_code == 201, resp.text
    project = resp.json()

    resp = client.post(f"/api/projects/{project['id']}/issues", json={"title": "合入测试议题"})
    assert resp.status_code == 201, resp.text
    issue = resp.json()

    # 创会绑定议题：open → in_progress + 回填项目归属
    resp = client.post(
        "/meetings",
        json={"topic": "合入测试会议", "deliverable_type": "adr", "issue_id": issue["id"]},
    )
    assert resp.status_code == 200, resp.text
    meeting_id = resp.json()["meeting_id"]

    # 会议工作区仓库克隆（模拟 _maybe_ingest_project_repo 的摄入产物）
    ws_root = Path(settings.workspace_root).resolve()
    meeting_dir = ws_root / meeting_id
    meeting_dir.mkdir(parents=True, exist_ok=True)
    _git(meeting_dir, "clone", "--quiet", str(bare), "demo")
    source_repo = meeting_dir / "demo"

    # 接缝：共享克隆改接本地 bare（https repo_url 测试环境不可达）
    async def _fake_ensure_shared_clone(project_dict: dict) -> Path:
        dest = merge_service.shared_clone_dir(str(project_dict["id"]))
        if not (dest / ".git").exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            _git(dest.parent, "clone", "--quiet", str(bare), "repo")
        return dest

    monkeypatch.setattr(merge_service, "ensure_shared_clone", _fake_ensure_shared_clone)

    yield SimpleNamespace(
        project=project, issue=issue, meeting_id=meeting_id, bare=bare, source_repo=source_repo, ws_root=ws_root
    )

    # 清理：共享克隆 + 会议工作区（防跨测试污染）
    shutil.rmtree(ws_root / "projects" / project["id"], ignore_errors=True)
    shutil.rmtree(meeting_dir, ignore_errors=True)


def _attach_artifact(client: TestClient, scenario) -> str:
    """发布真实产物并预挂为闭环凭证（PATCH 不流转状态分支）。"""
    artifact = _seed_artifact(scenario.meeting_id)
    resp = client.patch(f"/api/issues/{scenario.issue['id']}", json={"resolution_artifact_id": artifact["id"]})
    assert resp.status_code == 200, resp.text
    return artifact["id"]


def _stage_source_change(scenario, fname: str = "feature.txt", content: str = "new feature\n") -> None:
    """会议仓库新增变更但**不提交**（验证 D8 合入前自动提交）。"""
    (scenario.source_repo / fname).write_text(content, encoding="utf-8")


def _stage_origin_conflict(scenario, tmp_path: Path) -> None:
    """origin 侧与源侧对 README.md 做冲突修改。"""
    other = tmp_path / "other"
    _git(tmp_path, "clone", "--quiet", str(scenario.bare), "other")
    (other / "README.md").write_text("origin side change\n", encoding="utf-8")
    _git(other, "add", "-A")
    _git(other, "-c", "user.name=o", "-c", "user.email=o@t.local", "commit", "-m", "origin change", "--quiet")
    _git(other, "push", "--quiet", "origin", "main")
    # 源侧冲突变更（留未提交，由合入流程自动提交）
    (scenario.source_repo / "README.md").write_text("source side change\n", encoding="utf-8")


class TestMergePreview:
    """confirm=False：干跑预览不落状态。"""

    def test_preview_mergeable_with_diff(self, client, scenario):
        """预览返回变更清单，远端 SHA 不变，议题状态不变。"""
        _attach_artifact(client, scenario)
        _stage_source_change(scenario)
        head_before = _bare_head(scenario.bare)

        resp = client.post(f"/api/issues/{scenario.issue['id']}/merge", json={"confirm": False})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["mode"] == "preview"
        assert data["mergeable"] is True
        assert data["source_committed"] is True  # 未提交变更被 D8 自动提交
        assert any("feature.txt" in line for line in data["changed_files"])
        # 预览不落状态：远端未推进、议题仍 in_progress
        assert _bare_head(scenario.bare) == head_before
        assert client.get(f"/api/issues/{scenario.issue['id']}").json()["status"] == "in_progress"

    def test_preview_conflict_reports_files(self, client, scenario, tmp_path):
        """预览检测冲突：mergeable=False + 冲突清单，议题状态不变（非正向）。"""
        _attach_artifact(client, scenario)
        _stage_origin_conflict(scenario, tmp_path)

        resp = client.post(f"/api/issues/{scenario.issue['id']}/merge", json={"confirm": False})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["mergeable"] is False
        assert "README.md" in data["conflicts"]
        assert client.get(f"/api/issues/{scenario.issue['id']}").json()["status"] == "in_progress"


class TestMergeExecute:
    """confirm=True：正式合入 + push + 议题闭环。"""

    def test_execute_success_resolves_issue(self, client, scenario):
        """快乐路径：合入 → push origin/main → 议题 resolved + 凭证在案。"""
        artifact_id = _attach_artifact(client, scenario)
        _stage_source_change(scenario)
        head_before = _bare_head(scenario.bare)

        # 先预览再执行（真实用户路径，验证干跑不污染后续正式合入）
        assert client.post(f"/api/issues/{scenario.issue['id']}/merge", json={"confirm": False}).status_code == 200

        resp = client.post(f"/api/issues/{scenario.issue['id']}/merge", json={"confirm": True})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["merged"] is True
        assert data["pushed_to"] == "origin/main"
        assert data["issue_status"] == "resolved"
        assert any("feature.txt" in line for line in data["changed_files"])

        # 远端确实推进且含合入提交
        assert _bare_head(scenario.bare) != head_before
        log = subprocess.run(  # noqa: S603 — 静态参数列表无 shell，仅测试夹具
            ["git", "--git-dir", str(scenario.bare), "log", "--format=%s", "main"],  # noqa: S607 — git 为容器内 PATH 工具
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        assert "feat(issue-" in log

        # 议题终态与闭环凭证
        issue = client.get(f"/api/issues/{scenario.issue['id']}").json()
        assert issue["status"] == "resolved"
        assert issue["resolution_artifact_id"] == artifact_id

    def test_execute_conflict_marks_issue(self, client, scenario, tmp_path):
        """合入冲突 → 409 附清单，议题置 conflict 态交回用户（非正向，D11）。"""
        _attach_artifact(client, scenario)
        _stage_origin_conflict(scenario, tmp_path)

        resp = client.post(f"/api/issues/{scenario.issue['id']}/merge", json={"confirm": True})
        assert resp.status_code == 409
        # 全局异常处理器包装为 {"error": {code, message, details}}，冲突清单在 details
        details = resp.json()["error"]["details"]
        assert "README.md" in details["conflicts"]
        assert client.get(f"/api/issues/{scenario.issue['id']}").json()["status"] == "conflict"

    def test_execute_missing_artifact_409(self, client, scenario):
        """缺闭环凭证拒绝合入（非正向，闭环红线）。"""
        _stage_source_change(scenario)
        resp = client.post(f"/api/issues/{scenario.issue['id']}/merge", json={"confirm": True})
        assert resp.status_code == 409
        # 全局异常处理器包装为 {"error": {code, message, details}}
        assert "闭环凭证" in resp.json()["error"]["message"]


class TestMergeContextErrors:
    """合入上下文校验（非正向）。"""

    def test_merge_open_issue_without_meeting_409(self, client, scenario):
        """open 态且未绑会议的议题 → 409。"""
        resp = client.post(f"/api/projects/{scenario.project['id']}/issues", json={"title": "未绑会议"})
        fresh = resp.json()
        resp = client.post(f"/api/issues/{fresh['id']}/merge", json={"confirm": False})
        assert resp.status_code == 409

    def test_merge_unknown_issue_404(self, client, scenario):
        """不存在的议题 → 404。"""
        resp = client.post(f"/api/issues/{uuid.uuid4()}/merge", json={"confirm": False})
        assert resp.status_code == 404
