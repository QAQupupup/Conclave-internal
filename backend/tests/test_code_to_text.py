# 代码感知预处理测试（ADR-018 Phase B，D5 三路分派）
# 验证真实函数：classify_file / file_to_document / repo_to_documents /
#               _config_summary / _cap / 符号序列化
# 覆盖正向 + 边界（截断/空文件/超大文件）+ 异常（目录缺失/未知扩展名）维度。
from __future__ import annotations

from pathlib import Path

import pytest

from app.rag import code_to_text
from app.rag.code_parser import tree_sitter_available

# tree-sitter 相关用例单独标记（配置/文档路径不依赖 grammar，不 skip）
needs_tree_sitter = pytest.mark.skipif(
    not tree_sitter_available(),
    reason="tree-sitter 语法未安装：符号序列化路径不可用",
)

PY_SOURCE = '''"""应用入口"""
from util import helper


class App:
    """应用类"""

    def run(self):
        helper()
        return 1


def main():
    """主函数"""
    app = App()
    app.run()
'''


# ---------------------------------------------------------------------------
# classify_file：三路分派
# ---------------------------------------------------------------------------


class TestClassifyFile:
    @pytest.mark.parametrize("path", ["a.py", "a.js", "a.mjs", "a.jsx", "a.ts", "a.tsx"])
    def test_symbol_extensions(self, path: str) -> None:
        assert code_to_text.classify_file(path) == code_to_text.CATEGORY_SYMBOL

    @pytest.mark.parametrize("path", ["a.yaml", "a.yml", "a.toml", "a.json", "a.sql", "a.ini"])
    def test_config_extensions(self, path: str) -> None:
        assert code_to_text.classify_file(path) == code_to_text.CATEGORY_CONFIG

    @pytest.mark.parametrize("path", ["a.sh", "a.md", "a.txt"])
    def test_plain_extensions(self, path: str) -> None:
        assert code_to_text.classify_file(path) == code_to_text.CATEGORY_PLAIN

    @pytest.mark.parametrize("path", ["a.go", "a.png", "a.lock", "Makefile", ""])
    def test_unknown_extensions_skipped(self, path: str) -> None:
        """非正向：三路范围外的扩展名（含无扩展名）返回空串 → 跳过。"""
        assert code_to_text.classify_file(path) == ""

    def test_case_insensitive(self) -> None:
        assert code_to_text.classify_file("A.PY") == code_to_text.CATEGORY_SYMBOL
        assert code_to_text.classify_file("B.Md") == code_to_text.CATEGORY_PLAIN


# ---------------------------------------------------------------------------
# ① 符号语言路径
# ---------------------------------------------------------------------------


@needs_tree_sitter
class TestSymbolPath:
    def test_serializes_signatures_docstrings_calls(self, tmp_path: Path) -> None:
        f = tmp_path / "main.py"
        f.write_text(PY_SOURCE, encoding="utf-8")
        doc = code_to_text.file_to_document(f, tmp_path)
        assert doc is not None
        assert doc.category == code_to_text.CATEGORY_SYMBOL
        assert doc.rel_path == "main.py"
        # [文件] 头 + 语言标注
        assert "[文件] main.py（语言: python）" in doc.text
        # 符号签名与 docstring
        assert "class App:" in doc.text
        assert "应用类" in doc.text
        assert "def main():" in doc.text
        assert "主函数" in doc.text
        # 调用摘要（按调用方聚合）
        assert "[调用]" in doc.text
        assert "helper" in doc.text

    def test_symbol_count_marker(self, tmp_path: Path) -> None:
        f = tmp_path / "m.py"
        f.write_text(PY_SOURCE, encoding="utf-8")
        doc = code_to_text.file_to_document(f, tmp_path)
        assert doc is not None
        assert "[符号] 共 3 个" in doc.text  # App / run / main

    def test_no_symbols_falls_back_to_raw_text(self, tmp_path: Path) -> None:
        """边界：纯脚本式模块无符号定义 → 退化原文直入，不丢内容。"""
        f = tmp_path / "script.py"
        f.write_text("x = 1\nprint(x)\n", encoding="utf-8")
        doc = code_to_text.file_to_document(f, tmp_path)
        assert doc is not None
        assert "无符号摘要" in doc.text
        assert "x = 1" in doc.text

    def test_symbols_truncated_with_marker(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """边界：符号数超过上限 → 截断 + 省略标注。"""
        monkeypatch.setattr(code_to_text, "MAX_SYMBOLS_PER_DOC", 1)
        f = tmp_path / "many.py"
        f.write_text(PY_SOURCE, encoding="utf-8")
        doc = code_to_text.file_to_document(f, tmp_path)
        assert doc is not None
        assert "已省略" in doc.text

    def test_jsdoc_flows_into_serialized_text(self, tmp_path: Path) -> None:
        """D5 补 JSDoc 提取：TS 文件的 JSDoc 进入摄入文本。"""
        f = tmp_path / "price.ts"
        f.write_text(
            "/**\n * 计算总价。\n */\nfunction total(n: number): number { return n * 2; }\n",
            encoding="utf-8",
        )
        doc = code_to_text.file_to_document(f, tmp_path)
        assert doc is not None
        assert "计算总价。" in doc.text


def test_symbol_file_without_tree_sitter_degrades(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """非正向降级：grammar 不可用（parse 返回 supported=False）→ 原文直入。

    通过 patch parse_source 模拟 grammar 缺失，不依赖真实 tree-sitter 状态。
    """
    from app.rag.code_parser import ParsedFile

    monkeypatch.setattr(
        code_to_text,
        "parse_source",
        lambda code, lang, rel: ParsedFile(path=rel, language=lang, supported=False, error="grammar_unavailable"),
    )
    f = tmp_path / "a.py"
    f.write_text("def foo():\n    return 1\n", encoding="utf-8")
    doc = code_to_text.file_to_document(f, tmp_path)
    assert doc is not None
    assert "无符号摘要" in doc.text
    assert "def foo" in doc.text


# ---------------------------------------------------------------------------
# ② 配置/数据语言路径
# ---------------------------------------------------------------------------


class TestConfigPath:
    def test_yaml_top_keys(self, tmp_path: Path) -> None:
        f = tmp_path / "docker-compose.yml"
        f.write_text("services:\n  web:\n    image: nginx\nvolumes: {}\n", encoding="utf-8")
        doc = code_to_text.file_to_document(f, tmp_path)
        assert doc is not None
        assert doc.category == code_to_text.CATEGORY_CONFIG
        assert "[结构摘要] 顶级键: services、volumes" in doc.text
        assert "[原文]" in doc.text
        assert "image: nginx" in doc.text

    def test_yaml_invalid_falls_back_to_regex(self, tmp_path: Path) -> None:
        """非正向：非法 YAML（制表符缩进）→ PyYAML 失败退回行首正则。"""
        f = tmp_path / "bad.yaml"
        f.write_text("top_key:\n\tbroken_indent: 1\n", encoding="utf-8")
        doc = code_to_text.file_to_document(f, tmp_path)
        assert doc is not None
        assert "top_key" in doc.text

    def test_json_object_keys(self, tmp_path: Path) -> None:
        f = tmp_path / "package.json"
        f.write_text('{"name": "demo", "scripts": {"build": "vite build"}}', encoding="utf-8")
        doc = code_to_text.file_to_document(f, tmp_path)
        assert doc is not None
        assert "顶级键: name、scripts" in doc.text

    def test_json_array_summary(self, tmp_path: Path) -> None:
        f = tmp_path / "data.json"
        f.write_text('[{"a": 1}, {"b": 2}, {"c": 3}]', encoding="utf-8")
        doc = code_to_text.file_to_document(f, tmp_path)
        assert doc is not None
        assert "JSON 数组（3 项）" in doc.text

    def test_json_invalid_no_summary_but_raw_kept(self, tmp_path: Path) -> None:
        """非正向：非法 JSON → 无结构摘要但原文仍直入。"""
        f = tmp_path / "broken.json"
        f.write_text('{"unclosed": ', encoding="utf-8")
        doc = code_to_text.file_to_document(f, tmp_path)
        assert doc is not None
        assert "[结构摘要]" not in doc.text
        assert '{"unclosed":' in doc.text

    def test_toml_sections(self, tmp_path: Path) -> None:
        f = tmp_path / "pyproject.toml"
        f.write_text("[project]\nname = 'x'\n[tool.ruff]\nline-length = 100\n", encoding="utf-8")
        doc = code_to_text.file_to_document(f, tmp_path)
        assert doc is not None
        assert "小节: project、tool.ruff" in doc.text

    def test_sql_ddl_heads(self, tmp_path: Path) -> None:
        f = tmp_path / "schema.sql"
        f.write_text(
            "CREATE TABLE users (\n  id BIGINT\n);\nCREATE INDEX idx_users_id ON users(id);\n",
            encoding="utf-8",
        )
        doc = code_to_text.file_to_document(f, tmp_path)
        assert doc is not None
        assert "CREATE TABLE users" in doc.text
        assert "CREATE INDEX idx_users_id" in doc.text

    def test_ini_sections(self, tmp_path: Path) -> None:
        f = tmp_path / "app.ini"
        f.write_text("[server]\nport=8000\n[logging]\nlevel=info\n", encoding="utf-8")
        doc = code_to_text.file_to_document(f, tmp_path)
        assert doc is not None
        assert "小节: server、logging" in doc.text


# ---------------------------------------------------------------------------
# ③ 脚本/文档路径
# ---------------------------------------------------------------------------


class TestPlainPath:
    def test_markdown_raw_text(self, tmp_path: Path) -> None:
        f = tmp_path / "README.md"
        f.write_text("# 项目说明\n\n这是一个演示仓库。\n", encoding="utf-8")
        doc = code_to_text.file_to_document(f, tmp_path)
        assert doc is not None
        assert doc.category == code_to_text.CATEGORY_PLAIN
        assert "[文件] README.md（文档）" in doc.text
        assert "这是一个演示仓库。" in doc.text

    def test_shell_raw_text(self, tmp_path: Path) -> None:
        f = tmp_path / "deploy.sh"
        f.write_text("#!/usr/bin/env bash\nset -e\ndocker compose up -d\n", encoding="utf-8")
        doc = code_to_text.file_to_document(f, tmp_path)
        assert doc is not None
        assert "docker compose up -d" in doc.text


# ---------------------------------------------------------------------------
# 跳过与截断（非正向/边界）
# ---------------------------------------------------------------------------


class TestSkipAndLimits:
    def test_unknown_extension_returns_none(self, tmp_path: Path) -> None:
        f = tmp_path / "logo.png"
        f.write_bytes(b"\x89PNG fake")
        assert code_to_text.file_to_document(f, tmp_path) is None

    def test_empty_file_returns_none(self, tmp_path: Path) -> None:
        f = tmp_path / "empty.md"
        f.write_text("   \n", encoding="utf-8")
        assert code_to_text.file_to_document(f, tmp_path) is None

    def test_oversized_file_skipped(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """非正向：超过单文件大小上限 → 跳过（防压缩 bundle 拖垮摄入）。"""
        monkeypatch.setattr(code_to_text, "MAX_FILE_SIZE", 64)
        f = tmp_path / "big.md"
        f.write_text("x" * 200, encoding="utf-8")
        assert code_to_text.file_to_document(f, tmp_path) is None

    def test_text_truncated_with_marker(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """边界：预处理文本超过 MAX_DOC_CHARS → 截断且总长不超限。"""
        monkeypatch.setattr(code_to_text, "MAX_DOC_CHARS", 300)
        f = tmp_path / "long.md"
        f.write_text("段落内容。" * 500, encoding="utf-8")
        doc = code_to_text.file_to_document(f, tmp_path)
        assert doc is not None
        assert len(doc.text) <= 300
        assert "已截断" in doc.text
        assert doc.char_count == len(doc.text)

    def test_cap_short_text_unchanged(self) -> None:
        assert code_to_text._cap("短文本", limit=100) == "短文本"


# ---------------------------------------------------------------------------
# repo_to_documents：仓库级扫描
# ---------------------------------------------------------------------------


class TestRepoToDocuments:
    def _build_repo(self, root: Path) -> None:
        (root / "app").mkdir()
        (root / "app" / "main.py").write_text("def main():\n    return 0\n", encoding="utf-8")
        (root / "README.md").write_text("# 说明\n", encoding="utf-8")
        (root / "config.yaml").write_text("key: value\n", encoding="utf-8")
        # 应被跳过的目录与文件
        (root / ".git" / "objects").mkdir(parents=True)
        (root / ".git" / "objects" / "x.py").write_text("def hidden(): pass\n", encoding="utf-8")
        (root / "node_modules").mkdir()
        (root / "node_modules" / "lib.js").write_text("function lib() {}\n", encoding="utf-8")
        (root / "binary.bin").write_bytes(b"\x00\x01\x02")

    def test_scans_and_dispatches(self, tmp_path: Path) -> None:
        self._build_repo(tmp_path)
        docs = code_to_text.repo_to_documents(tmp_path)
        rels = [d.rel_path for d in docs]
        assert rels == sorted(rels)  # 确定性排序
        assert "app/main.py" in rels
        assert "README.md" in rels
        assert "config.yaml" in rels
        # .git / node_modules / 未知扩展名均被跳过
        assert not any(".git" in r for r in rels)
        assert not any("node_modules" in r for r in rels)
        assert "binary.bin" not in rels
        cats = {d.rel_path: d.category for d in docs}
        assert cats["config.yaml"] == code_to_text.CATEGORY_CONFIG
        assert cats["README.md"] == code_to_text.CATEGORY_PLAIN

    def test_missing_dir_returns_empty(self, tmp_path: Path) -> None:
        """非正向：目录不存在 → 空列表而非抛错。"""
        assert code_to_text.repo_to_documents(tmp_path / "not-exist") == []
