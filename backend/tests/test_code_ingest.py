# 代码摄入安全逻辑单元测试（ADR-016 Phase A）
# 验证真实函数：_parse_repo_name / _sanitize_dir / _inject_token / _redact /
#               _safe_extract_zip / _resolve_dest / _register_code_in_state /
#               _register_code_to_state
# 覆盖正向 + 边界（空/穿越）+ 异常（zip-slip/登记失败降级）维度。
from __future__ import annotations

import io
import zipfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.models import MeetingState
from app.routers.code import (
    _inject_token,
    _parse_repo_name,
    _redact,
    _register_code_in_state,
    _register_code_to_state,
    _resolve_dest,
    _safe_extract_zip,
    _sanitize_dir,
)
from conclave_core.anchor import get_code_anchor, get_full_anchor


class TestParseRepoName:
    """从 URL 提取仓库名：协议/认证前缀/查询片段/.git 后缀。"""

    @pytest.mark.parametrize(
        "url,expected",
        [
            ("https://gitlab.com/org/repo.git", "repo"),
            ("https://gitlab.com/org/repo", "repo"),
            ("https://gitlab.com/org/sub/repo.git", "repo"),
            ("https://user@gitlab.com/org/repo.git", "repo"),
            ("http://gitlab.com/org/repo.git/", "repo"),
            ("https://gitlab.com/org/repo.git?ref=main", "repo"),
            ("https://gitlab.com/org/repo.git#frag", "repo"),
        ],
    )
    def test_repo_name_extraction(self, url: str, expected: str) -> None:
        assert _parse_repo_name(url) == expected

    @pytest.mark.parametrize("url", ["", "https://", "https:///", "..", "https://host/.."])
    def test_degenerate_url_falls_back_to_repo(self, url: str) -> None:
        # 无法提取到合法名时回退 "repo"，不抛错、不产生越界名
        assert _parse_repo_name(url) == "repo"


class TestSanitizeDir:
    """目录名安全化：拒绝穿越与空名。"""

    @pytest.mark.parametrize("name", ["..", ".", "", "   ", "/"])
    def test_traversal_or_empty_returns_empty(self, name: str) -> None:
        assert _sanitize_dir(name) == ""

    def test_hybrid_traversal_neutralized(self) -> None:
        # "a/../.." → 斜杠被替换为下划线后，".." 不再构成穿越，结果是单一安全组件
        result = _sanitize_dir("a/../..")
        assert "/" not in result
        assert result not in ("", ".", "..")
        assert not result.startswith("..")

    @pytest.mark.parametrize(
        "name,expected",
        [
            ("my-repo", "my-repo"),
            ("a/b", "a_b"),
            ("repo with space", "repo_with_space"),
            ("中文仓库", "中文仓库"),
        ],
    )
    def test_normalizes_special_chars(self, name: str, expected: str) -> None:
        assert _sanitize_dir(name) == expected


class TestInjectToken:
    """HTTPS token 注入：不重复注入、URL 编码特殊字符。"""

    def test_no_token_returns_same_url(self) -> None:
        url = "https://gitlab.com/org/repo.git"
        assert _inject_token(url, None) == url
        assert _inject_token(url, "") == url

    def test_injects_token(self) -> None:
        out = _inject_token("https://gitlab.com/org/repo.git", "secret123")
        assert out == "https://oauth2:secret123@gitlab.com/org/repo.git"

    def test_does_not_double_inject(self) -> None:
        url = "https://user:pass@gitlab.com/org/repo.git"
        assert _inject_token(url, "secret123") == url

    def test_token_special_chars_encoded(self) -> None:
        out = _inject_token("https://gitlab.com/org/repo.git", "a b/c@d")
        # 特殊字符被百分号编码，不会破坏 URL 结构
        assert "a%20b" in out
        assert "@gitlab.com" in out


class TestRedact:
    """错误输出脱敏。"""

    def test_token_removed(self) -> None:
        assert _redact("fatal: unable to access 'https://oauth2:secret123@host/x'", "secret123") == (
            "fatal: unable to access 'https://oauth2:***@host/x'"
        )

    def test_no_token_leaves_text(self) -> None:
        assert _redact("some error", None) == "some error"


class TestSafeExtractZip:
    """zip-slip：越界路径必须被拒绝。"""

    def test_normal_entry_extracted(self, tmp_path: Path) -> None:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("a/main.py", "print(1)")
            zf.writestr("a/", "")
        buf.seek(0)
        with zipfile.ZipFile(buf) as zf:
            count = _safe_extract_zip(zf, tmp_path)
        assert count == 1
        assert (tmp_path / "a" / "main.py").read_text() == "print(1)"

    @pytest.mark.parametrize("evil", ["../evil.txt", "../../etc/passwd", "a/../../evil.txt"])
    def test_zip_slip_rejected(self, tmp_path: Path, evil: str) -> None:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(evil, "x")
        buf.seek(0)
        with zipfile.ZipFile(buf) as zf, pytest.raises(ValueError):
            _safe_extract_zip(zf, tmp_path)
        # 拒绝后不应在目标目录外落盘
        assert not (tmp_path.parent / "evil.txt").exists()


class TestResolveDest:
    """目标目录解析：防穿越 + 空名拒绝。"""

    def test_empty_name_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            _resolve_dest(tmp_path, "")

    @pytest.mark.parametrize("name", ["..", "../x", "a/../../etc"])
    def test_traversal_rejected(self, tmp_path: Path, name: str) -> None:
        with pytest.raises(ValueError):
            _resolve_dest(tmp_path, name)

    def test_normal_name_within_base(self, tmp_path: Path) -> None:
        dest = _resolve_dest(tmp_path, "repo")
        assert dest.parent.resolve() == tmp_path.resolve()


# ---- [P1 修复] MeetingState 登记与代码锚点 ----


def _make_state() -> MeetingState:
    return MeetingState(meeting_id="m-1", topic="测试议题")


def _repo_info(**overrides: object) -> dict:
    info: dict = {
        "name": "demo-repo",
        "path": "demo-repo",
        "source_type": "git",
        "file_count": 42,
        "size_bytes": 1024,
        "indexed": True,
    }
    info.update(overrides)
    return info


class TestRegisterCodeInState:
    """登记纯逻辑：写入 code_repos + 同步 doc_summaries + 去重。"""

    def test_registers_repo_and_summary(self) -> None:
        state = _make_state()
        _register_code_in_state(state, _repo_info())
        assert state.code_repos == [_repo_info()]
        assert len(state.doc_summaries) == 1
        summary = state.doc_summaries[0]
        assert "demo-repo" in summary
        assert "42" in summary
        assert "git" in summary

    def test_same_path_replaces_not_duplicates(self) -> None:
        """非正向边界：重新摄入同路径 → 替换旧记录而非堆积。"""
        state = _make_state()
        _register_code_in_state(state, _repo_info(file_count=1, indexed=False))
        _register_code_in_state(state, _repo_info(file_count=99, indexed=True))
        assert len(state.code_repos) == 1
        assert state.code_repos[0]["file_count"] == 99
        assert state.code_repos[0]["indexed"] is True
        # doc_summaries 同样不堆积
        assert len(state.doc_summaries) == 1
        assert "99" in state.doc_summaries[0]

    def test_different_paths_coexist(self) -> None:
        state = _make_state()
        _register_code_in_state(state, _repo_info(name="a", path="a"))
        _register_code_in_state(state, _repo_info(name="b", path="b"))
        assert [r["path"] for r in state.code_repos] == ["a", "b"]
        assert len(state.doc_summaries) == 2

    def test_missing_name_falls_back_to_path(self) -> None:
        """边界：repo_info 缺 name 时用 path 兜底，不抛 KeyError。"""
        state = _make_state()
        info = _repo_info()
        del info["name"]
        _register_code_in_state(state, info)
        assert state.code_repos[0]["path"] == "demo-repo"
        assert "demo-repo" in state.doc_summaries[0]

    def test_preserves_existing_doc_summaries(self) -> None:
        state = _make_state()
        state.doc_summaries.append("需求文档（3 块）")
        _register_code_in_state(state, _repo_info())
        assert state.doc_summaries[0] == "需求文档（3 块）"
        assert len(state.doc_summaries) == 2


class TestCodeAnchor:
    """代码锚点构造：注入各阶段 prompt 的"已导入代码"感知文本。"""

    def test_empty_repos_returns_empty(self) -> None:
        state = _make_state()
        assert get_code_anchor(state) == ""

    def test_anchor_contains_repo_facts(self) -> None:
        state = _make_state()
        state.code_repos = [_repo_info()]
        anchor = get_code_anchor(state)
        assert "[已导入代码仓库]" in anchor
        assert "demo-repo" in anchor
        assert "42 个文件" in anchor
        assert "已建立代码索引" in anchor
        # 引导取证行为
        assert "fs.list" in anchor

    def test_unindexed_repo_marked(self) -> None:
        state = _make_state()
        state.code_repos = [_repo_info(indexed=False)]
        assert "未建立代码索引" in get_code_anchor(state)

    def test_invalid_entries_skipped(self) -> None:
        """非正向边界：无名无路径的脏条目被跳过，全部无效时返回空串。"""
        state = _make_state()
        state.code_repos = [{"name": "", "path": ""}, {}]
        assert get_code_anchor(state) == ""

    def test_full_anchor_includes_code_anchor(self) -> None:
        state = _make_state()
        state.code_repos = [_repo_info()]
        full = get_full_anchor(state, "intra_team")
        assert "[已导入代码仓库]" in full

    def test_full_anchor_unchanged_without_code(self) -> None:
        """回归：无代码仓库时 get_full_anchor 行为与修复前一致（空串）。"""
        state = _make_state()
        assert get_full_anchor(state, "clarify") == ""


class TestRegisterCodeToState:
    """登记入口：内存态/DB 恢复/降级路径。"""

    async def test_in_memory_state_registered_and_persisted(self) -> None:
        state = _make_state()
        with (
            patch("app.orchestrator.runner.get_state", return_value=state),
            patch("app.routers.code._persist_state_lite", new=AsyncMock()) as mock_persist,
        ):
            ok = await _register_code_to_state("m-1", _repo_info())
        assert ok is True
        assert state.code_repos[0]["path"] == "demo-repo"
        mock_persist.assert_awaited_once_with(state)

    async def test_recovers_from_db_when_not_in_memory(self) -> None:
        """重启场景：内存未命中但 DB 有记录 → 恢复后登记。"""
        state = _make_state()
        with (
            patch("app.orchestrator.runner.get_state", return_value=None),
            patch("app.dao.meeting_dao.get_meeting", new=AsyncMock(return_value={"topic": "测试议题"})),
            patch("app.orchestrator.runner.load_or_create", new=AsyncMock(return_value=state)),
            patch("app.routers.code._persist_state_lite", new=AsyncMock()),
        ):
            ok = await _register_code_to_state("m-1", _repo_info())
        assert ok is True
        assert state.code_repos

    async def test_no_state_no_record_returns_false(self) -> None:
        """非正向：无内存态且 DB 无记录 → 返回 False，不抛异常。"""
        with (
            patch("app.orchestrator.runner.get_state", return_value=None),
            patch("app.dao.meeting_dao.get_meeting", new=AsyncMock(return_value=None)),
        ):
            ok = await _register_code_to_state("m-404", _repo_info())
        assert ok is False

    async def test_persist_failure_degrades_to_false(self) -> None:
        """非正向：持久化失败 → 返回 False（摄入结果不受影响）。"""
        state = _make_state()
        with (
            patch("app.orchestrator.runner.get_state", return_value=state),
            patch(
                "app.routers.code._persist_state_lite",
                new=AsyncMock(side_effect=RuntimeError("db down")),
            ),
        ):
            ok = await _register_code_to_state("m-1", _repo_info())
        assert ok is False
