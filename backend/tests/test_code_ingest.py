# 代码摄入安全逻辑单元测试（ADR-016 Phase A）
# 验证真实函数：_parse_repo_name / _sanitize_dir / _inject_token / _redact /
#               _safe_extract_zip / _resolve_dest
# 覆盖正向 + 边界（空/穿越）+ 异常（zip-slip）维度。
from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from app.routers.code import (
    _inject_token,
    _parse_repo_name,
    _redact,
    _resolve_dest,
    _safe_extract_zip,
    _sanitize_dir,
)


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
