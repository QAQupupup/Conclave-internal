"""produce 节点 test_suite 执行闭环测试（ADR-017 Phase 3 / T3.1-T3.2、T3.5）。

覆盖：
- _parse_test_report：通过/失败汇总、FAILED 明细、ERRORS 收集错误、
  空输出零值（边界）、大输出截断（大产物红线）
- _write_test_files：正常写入含子目录、路径穿越拒绝（非正向）、
  非法条目静默跳过、绝对路径规范化不出工作区
- produce_node test_suite 分支：沙箱执行写回 execution/test_report +
  自动提交、路径全部非法跳过执行（降级可追溯）、执行异常降级、
  空 test_files 不执行
- produce_node 兜底分支：feasibility_report/adr 写入 artifact（T3.1/I8）

compute 以存根替换，sandbox.run_command 与 git 提交经 monkeypatch 拦截；
不依赖真实 LLM、Docker 沙箱与数据库。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.agents import compute as compute_mod
from app.agents.compute import ThinkRequest, ThinkResponse
from app.config import Settings
from app.models import MeetingState
from app.orchestrator.nodes.produce import (
    _parse_test_report,
    _write_test_files,
    produce_node,
)
from app.sandbox import SANDBOX_IMAGE_DATASCIENCE, ExecResult
from app.services import git_service as git_service_mod


class FixedResultStubCompute:
    """返回固定结果的 compute 存根。"""

    def __init__(self, result: dict[str, Any]) -> None:
        self._result = result

    async def think(self, req: ThinkRequest) -> ThinkResponse:
        return ThinkResponse(success=True, result=self._result)

    async def think_batch(self, requests: list[ThinkRequest]) -> list[ThinkResponse]:
        return [await self.think(r) for r in requests]


@pytest.fixture(autouse=True)
def reset_compute():
    """每个测试前后重置全局 compute 实例。"""
    compute_mod.reset_compute()
    yield
    compute_mod.reset_compute()


def _patch_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    import app.config as config_mod

    monkeypatch.setattr(
        config_mod,
        "settings",
        Settings(workspace_root=str(tmp_path), memory_enabled=False),
    )
    return tmp_path


def _patch_sandbox(monkeypatch: pytest.MonkeyPatch, stdout: str = "===== 2 passed in 0.01s =====", exit_code: int = 0):
    """替换 sandbox.run_command，记录调用参数。"""
    import app.sandbox as sandbox_mod

    calls: list[dict[str, Any]] = []

    async def fake_run_command(command, workspace_root, timeout=30, image=None, network_level="L1"):
        calls.append(
            {
                "command": command,
                "workspace_root": workspace_root,
                "timeout": timeout,
                "image": image,
                "network_level": network_level,
            }
        )
        return ExecResult(exit_code=exit_code, stdout=stdout, stderr="", sandboxed=True, image=image or "")

    monkeypatch.setattr(sandbox_mod, "run_command", fake_run_command)
    return calls


def _patch_git_commit(monkeypatch: pytest.MonkeyPatch):
    """替换 git_service.commit_workspace，记录调用（避免测试内真实 git 操作）。"""
    calls: list[dict[str, Any]] = []

    async def fake_commit(meeting_id: str, topic: str = "") -> dict[str, Any]:
        calls.append({"meeting_id": meeting_id, "topic": topic})
        return {"committed": True, "commit_sha": "abc123def456"}

    monkeypatch.setattr(git_service_mod, "commit_workspace", fake_commit)
    return calls


# ---------- _parse_test_report ----------


def test_parse_test_report_all_passed():
    """标准 pytest 汇总行解析出通过数"""
    report = _parse_test_report(
        {
            "exit_code": 0,
            "stdout": "collected 5 items\n.....\n===== 5 passed in 0.12s =====",
            "stderr": "",
            "sandboxed": True,
        }
    )
    assert report["passed"] == 5
    assert report["failed"] == 0
    assert report["failures"] == []
    assert report["exit_code"] == 0
    assert report["sandboxed"] is True
    assert report["executed_at"]


def test_parse_test_report_failed_with_details():
    """失败数与 FAILED 明细（≤10 条）均被解析"""
    stdout = (
        "=== FAILURES ===\n"
        "FAILED tests/test_x.py::test_bad - AssertionError\n"
        "FAILED tests/test_y.py::test_worse\n"
        "=== 2 failed, 3 passed in 0.30s ==="
    )
    report = _parse_test_report({"exit_code": 1, "stdout": stdout, "stderr": "", "sandboxed": True})
    assert report["passed"] == 3
    assert report["failed"] == 2
    assert report["failures"] == ["tests/test_x.py::test_bad", "tests/test_y.py::test_worse"]
    assert report["exit_code"] == 1


def test_parse_test_report_collection_errors_counted_as_failed():
    """无汇总行但有 ERRORS 段（收集阶段报错）→ 按 error 数计失败（非正向）"""
    stdout = "=========== ERRORS ===========\nERROR collecting tests/test_a.py\n======= 2 errors in 0.10s ======="
    report = _parse_test_report({"exit_code": 2, "stdout": stdout, "stderr": "", "sandboxed": False})
    assert report["passed"] == 0
    assert report["failed"] == 2


def test_parse_test_report_empty_output_zero_values():
    """空输出 → 全零值不抛错（边界）"""
    report = _parse_test_report({"exit_code": -1, "stdout": "", "stderr": "", "sandboxed": False})
    assert report["passed"] == 0
    assert report["failed"] == 0
    assert report["failures"] == []
    assert report["exit_code"] == -1


def test_parse_test_report_truncates_large_output():
    """大输出只保留尾部 3000 字符（大产物红线）"""
    report = _parse_test_report({"exit_code": 0, "stdout": "x" * 5000, "stderr": "y" * 5000, "sandboxed": True})
    assert len(report["output"]) <= 3000


# ---------- _write_test_files ----------


def test_write_test_files_writes_valid_paths(tmp_path):
    """合法路径写入成功，含子目录创建与反斜杠规范化"""
    kept, skipped = _write_test_files(
        tmp_path,
        [
            {"path": "tests/test_a.py", "code": "def test_ok():\n    assert True\n"},
            {"path": "src\\nested\\test_b.py", "code": "x = 1\n"},
        ],
    )
    assert skipped == []
    assert [f["path"] for f in kept] == ["tests/test_a.py", "src/nested/test_b.py"]
    assert (tmp_path / "tests" / "test_a.py").read_text(encoding="utf-8").startswith("def test_ok")
    assert (tmp_path / "src" / "nested" / "test_b.py").exists()


def test_write_test_files_rejects_traversal(tmp_path):
    """路径穿越（.. 段）被拒绝且不落盘（非正向，I10）"""
    kept, skipped = _write_test_files(
        tmp_path,
        [
            {"path": "../evil.py", "code": "bad"},
            {"path": "tests/../../escape.py", "code": "bad"},
        ],
    )
    assert kept == []
    assert len(skipped) == 2
    assert not (tmp_path.parent / "evil.py").exists()
    assert not (tmp_path.parent / "escape.py").exists()


def test_write_test_files_rejects_illegal_charset(tmp_path):
    """白名单外字符（空格/命令元字符）被拒绝（非正向，I10）"""
    kept, skipped = _write_test_files(
        tmp_path,
        [
            {"path": "a b.py", "code": "x"},
            {"path": "test;rm.py", "code": "x"},
            {"path": "$(whoami).py", "code": "x"},
        ],
    )
    assert kept == []
    assert len(skipped) == 3


def test_write_test_files_skips_malformed_entries(tmp_path):
    """非 dict / 空 path / 空 code 静默跳过（边界）"""
    kept, skipped = _write_test_files(
        tmp_path,
        ["not a dict", {"path": "", "code": "x"}, {"path": "a.py", "code": ""}, {}],
    )
    assert kept == []
    assert skipped == []


def test_write_test_files_normalizes_absolute_path_inside_workspace(tmp_path):
    """绝对路径前导斜杠被剥离，仍落在工作区内（I10 包含校验）"""
    kept, skipped = _write_test_files(tmp_path, [{"path": "/etc/passwd", "code": "data"}])
    assert skipped == []
    assert kept[0]["path"] == "etc/passwd"
    assert (tmp_path / "etc" / "passwd").exists()
    assert not Path("/etc/passwd_conclave_test").exists()


# ---------- produce_node test_suite 分支 ----------


_VALID_TEST_SUITE_RESULT = {
    "test_suite": {
        "title": "产物模块测试套件",
        "test_files": [{"path": "tests/test_gen.py", "code": "def test_a():\n    assert True\n"}],
        "run_instructions": "pytest tests/test_gen.py",
    }
}


async def test_produce_node_test_suite_full_closed_loop(monkeypatch, tmp_path):
    """完整闭环：写入 → 沙箱 pytest → execution/test_report 写回 → 自动提交"""
    monkeypatch.setattr(compute_mod, "_compute", FixedResultStubCompute(_VALID_TEST_SUITE_RESULT))
    _patch_settings(monkeypatch, tmp_path)
    run_calls = _patch_sandbox(monkeypatch)
    commit_calls = _patch_git_commit(monkeypatch)

    state = MeetingState(meeting_id="mtg-ts-loop", topic="生成测试套件", deliverable_type="test_suite")
    state = await produce_node(state)

    # 测试文件落工作区
    assert (tmp_path / "mtg-ts-loop" / "tests" / "test_gen.py").exists()
    # 沙箱执行：pytest 命令 + datascience 镜像
    assert len(run_calls) == 1
    assert "python -m pytest tests/test_gen.py" in run_calls[0]["command"]
    assert run_calls[0]["image"] == SANDBOX_IMAGE_DATASCIENCE
    # 执行结果与报告写回 artifact
    assert state.artifact["execution"]["exit_code"] == 0
    assert state.artifact["test_report"]["passed"] == 2
    assert state.artifact["test_report"]["failed"] == 0
    assert state.artifact["test_report"]["test_file_count"] == 1
    # 规范化后的文件列表回写产物
    assert state.artifact["test_suite"]["test_files"][0]["path"] == "tests/test_gen.py"
    # 工作区自动提交（T3.5）
    assert commit_calls and commit_calls[0]["meeting_id"] == "mtg-ts-loop"


async def test_produce_node_test_suite_all_paths_invalid_skips_execution(monkeypatch, tmp_path):
    """路径全部非法：不执行沙箱，产物仍发布且降级可追溯（非正向）"""
    result = {"test_suite": {"title": "t", "test_files": [{"path": "../evil.py", "code": "x = 1"}]}}
    monkeypatch.setattr(compute_mod, "_compute", FixedResultStubCompute(result))
    _patch_settings(monkeypatch, tmp_path)
    run_calls = _patch_sandbox(monkeypatch)
    _patch_git_commit(monkeypatch)

    state = MeetingState(meeting_id="mtg-ts-invalid", topic="非法路径", deliverable_type="test_suite")
    state = await produce_node(state)

    assert run_calls == []  # 未触发沙箱
    assert state.artifact["test_suite"]["test_files"] == []
    assert "安全校验" in state.artifact["test_report"]["error"]
    assert state.artifact["test_report"]["test_file_count"] == 0
    assert "execution" not in state.artifact


async def test_produce_node_test_suite_execution_exception_degrades(monkeypatch, tmp_path):
    """沙箱执行异常：错误写入 execution/test_report，不抛出（异常路径）"""
    monkeypatch.setattr(compute_mod, "_compute", FixedResultStubCompute(_VALID_TEST_SUITE_RESULT))
    _patch_settings(monkeypatch, tmp_path)

    import app.sandbox as sandbox_mod

    async def broken_run_command(command, workspace_root, timeout=30, image=None, network_level="L1"):
        raise RuntimeError("docker unavailable")

    monkeypatch.setattr(sandbox_mod, "run_command", broken_run_command)
    _patch_git_commit(monkeypatch)

    state = MeetingState(meeting_id="mtg-ts-broken", topic="沙箱不可用", deliverable_type="test_suite")
    state = await produce_node(state)

    assert state.artifact["execution"]["error"] == "docker unavailable"
    assert state.artifact["execution"]["exit_code"] == -1
    assert "docker unavailable" in state.artifact["test_report"]["error"]
    assert state.artifact["test_report"]["test_file_count"] == 1


async def test_produce_node_test_suite_empty_files_no_execution(monkeypatch, tmp_path):
    """LLM 未返回测试文件：不执行沙箱，仅写入（可能为空的）套件数据（边界）"""
    monkeypatch.setattr(
        compute_mod, "_compute", FixedResultStubCompute({"test_suite": {"title": "空套件", "test_files": []}})
    )
    _patch_settings(monkeypatch, tmp_path)
    run_calls = _patch_sandbox(monkeypatch)

    state = MeetingState(meeting_id="mtg-ts-empty", topic="空套件", deliverable_type="test_suite")
    state = await produce_node(state)

    assert run_calls == []
    assert state.artifact["test_suite"]["test_files"] == []
    assert "execution" not in state.artifact
    assert "test_report" not in state.artifact


# ---------- produce_node 兜底分支（T3.1/I8） ----------


@pytest.mark.parametrize("dt,key", [("feasibility_report", "feasibility_report"), ("adr", "adr")])
async def test_produce_node_new_doc_types_written_to_artifact(monkeypatch, tmp_path, dt, key):
    """feasibility_report/adr 经兜底分支写入 artifact（修复前键列表缺失导致丢失）"""
    payload = {"title": f"{key} 标题", "summary": "摘要内容"}
    monkeypatch.setattr(compute_mod, "_compute", FixedResultStubCompute({key: payload}))
    _patch_settings(monkeypatch, tmp_path)

    state = MeetingState(meeting_id=f"mtg-{key}", topic="文档类型写入", deliverable_type=dt)
    state = await produce_node(state)

    assert state.artifact[key] == payload
