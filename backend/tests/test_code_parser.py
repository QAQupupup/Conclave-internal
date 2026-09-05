# 代码解析器测试（ADR-016 Phase B）
# 验证真实 parse_source / parse_file / language_for_path，覆盖多语言 + 边界 + 异常维度。
from __future__ import annotations

import pytest

from app.rag.code_parser import (
    language_for_path,
    parse_source,
    tree_sitter_available,
)

pytestmark = pytest.mark.skipif(
    not tree_sitter_available(),
    reason="tree-sitter 语法未安装：本地可 `pip install tree-sitter tree-sitter-python tree-sitter-javascript tree-sitter-typescript`，或走 Docker CI",
)

PY_CODE = '''"""模块 docstring"""
import os
from collections import Counter

class Base:
    def run(self):
        return 1

class Child(Base):
    """子类文档"""
    def helper(self, x):
        return x * 2
    def process(self):
        self.helper(3)

def top_level(a, b):
    """顶层函数"""
    os.path.join(str(a), str(b))
    return Counter()

c = Child()
c.process()
'''

TS_CODE = """import type { T } from './types'
import { helper } from './util'

class Base {}
class Child extends Base {
  run(a: T): number { return helper(a); }
}
export function top(a: number): number { return a + 1; }
top(5);
"""


# ---- Python ----


class TestPythonSymbols:
    def test_symbols_typed_and_qualified(self) -> None:
        pf = parse_source(PY_CODE, "python", "sample.py")
        assert pf.supported is True
        names = {(s.name, s.kind) for s in pf.symbols}
        assert ("Base", "class") in names
        assert ("Child", "class") in names
        assert ("run", "method") in names
        assert ("helper", "method") in names
        assert ("process", "method") in names
        assert ("top_level", "function") in names
        by = {s.name: s for s in pf.symbols}
        assert by["helper"].qualified_name == "sample.py::Child::helper"
        assert by["top_level"].qualified_name == "sample.py::top_level"
        assert by["helper"].class_name == "sample.py::Child"

    def test_imports(self) -> None:
        pf = parse_source(PY_CODE, "python", "sample.py")
        mods = {i.module for i in pf.imports}
        assert "os" in mods
        assert "collections" in mods

    def test_calls(self) -> None:
        pf = parse_source(PY_CODE, "python", "sample.py")
        callees = [c.callee_name for c in pf.calls]
        assert any("helper" in c for c in callees)  # self.helper(3)
        assert any("os.path.join" in c for c in callees)

    def test_inherits_and_docstring(self) -> None:
        pf = parse_source(PY_CODE, "python", "sample.py")
        assert any(i.base_name == "Base" for i in pf.inherits)
        by = {s.name: s for s in pf.symbols}
        assert "子类文档" in by["Child"].docstring
        assert "顶层函数" in by["top_level"].docstring


class TestCharOffsets:
    def test_offsets_align_with_text(self) -> None:
        pf = parse_source(PY_CODE, "python", "sample.py")
        for s in pf.symbols:
            assert PY_CODE[s.char_start : s.char_end] == s.text

    def test_multibyte_prefix_offsets(self) -> None:
        # 中文注释出现在符号之前：char 偏移必须与字节偏移区分，且行号正确
        code = "# 中文注释\n# 更多中文\n\ndef foo():\n    return 1\n"
        pf = parse_source(code, "python", "cn.py")
        foo = next(s for s in pf.symbols if s.name == "foo")
        assert code[foo.char_start : foo.char_end] == foo.text
        assert "def foo" in foo.text
        assert foo.start_line == 4


class TestDegradation:
    def test_empty_source(self) -> None:
        pf = parse_source("", "python", "empty.py")
        assert pf.supported is True
        assert pf.symbols == []

    def test_syntax_error_still_parses(self) -> None:
        # tree-sitter 容错：残缺代码也能抽出符号
        code = "def broken(:\n   x = )\nclass A:\n    def ok(self):\n        pass\n"
        pf = parse_source(code, "python", "broken.py")
        assert pf.supported is True
        assert any(s.name == "ok" for s in pf.symbols)

    def test_unsupported_language(self) -> None:
        pf = parse_source("x=1", "ruby", "x.rb")
        assert pf.supported is False
        assert pf.error == "grammar_unavailable"


# ---- JavaScript / TypeScript ----


class TestTypeScript:
    def test_symbols_and_imports(self) -> None:
        pf = parse_source(TS_CODE, "typescript", "src/main.ts")
        assert pf.supported is True
        kinds = {(s.name, s.kind) for s in pf.symbols}
        assert ("Base", "class") in kinds
        assert ("Child", "class") in kinds
        assert ("run", "method") in kinds
        assert ("top", "function") in kinds
        mods = {i.module for i in pf.imports}
        assert "./types" in mods
        assert "./util" in mods

    def test_inherits_and_call(self) -> None:
        pf = parse_source(TS_CODE, "typescript", "src/main.ts")
        assert any(i.base_name == "Base" for i in pf.inherits)
        assert any("helper" in c.callee_name for c in pf.calls)


class TestJsTsInheritance:
    """回归 JS/TS 继承抽取：class_heritage 在 0.25/0.23 grammar 中不再是命名 field。"""

    def test_js_simple_and_member_extends(self) -> None:
        code = "class Base {}\nclass Child extends Base {}\nclass Sub extends pkg.Widget {}\n"
        pf = parse_source(code, "javascript", "a.js")
        bases = [i.base_name for i in pf.inherits]
        assert "Base" in bases
        assert "pkg.Widget" in bases

    def test_ts_member_extends(self) -> None:
        pf = parse_source("class C extends A.B {}\n", "typescript", "a.ts")
        assert any(i.base_name == "A.B" for i in pf.inherits)

    def test_ts_generic_extends_skips_type_arg(self) -> None:
        # Base<T> 只记录 Base，不把类型实参 T 误当基类
        pf = parse_source("class G extends Base<T> {}\n", "typescript", "a.ts")
        bases = [i.base_name for i in pf.inherits]
        assert "Base" in bases
        assert "T" not in bases


class TestLanguageDetection:
    @pytest.mark.parametrize(
        "path,expected",
        [
            ("a.py", "python"),
            ("a.ts", "typescript"),
            ("a.tsx", "tsx"),
            ("a.js", "javascript"),
            ("a.mjs", "javascript"),
            ("a.cpp", ""),
            ("a.go", ""),
        ],
    )
    def test_extension_mapping(self, path: str, expected: str) -> None:
        assert language_for_path(path) == expected


class TestJsDocExtraction:
    """ADR-018 D5：JS/TS 紧邻声明的 JSDoc 提取到 Symbol.docstring。"""

    def test_jsdoc_before_function(self) -> None:
        code = "/**\n * 计算总价。\n * @param n 数量\n */\nfunction total(n: number): number { return n * 2; }\n"
        pf = parse_source(code, "typescript", "price.ts")
        by = {s.name: s for s in pf.symbols}
        assert "total" in by
        assert "计算总价。" in by["total"].docstring
        assert "@param n 数量" in by["total"].docstring

    def test_jsdoc_before_export_statement(self) -> None:
        """export function 的 JSDoc 位于 export_statement 之前，需上提一层。"""
        code = "/** 导出工具函数 */\nexport function util(): void {}\n"
        pf = parse_source(code, "typescript", "u.ts")
        by = {s.name: s for s in pf.symbols}
        assert "util" in by
        assert "导出工具函数" in by["util"].docstring

    def test_plain_line_comment_not_jsdoc(self) -> None:
        """非正向：// 行注释不是 JSDoc，不得误提取。"""
        code = "// 普通注释\nfunction plain(): void {}\n"
        pf = parse_source(code, "javascript", "p.js")
        by = {s.name: s for s in pf.symbols}
        assert by["plain"].docstring == ""

    def test_non_adjacent_comment_not_extracted(self) -> None:
        """非正向：注释与声明之间隔了其他声明 → 不属于该符号。"""
        code = "/** 属于 first */\nfunction first(): void {}\nfunction second(): void {}\n"
        pf = parse_source(code, "javascript", "n.js")
        by = {s.name: s for s in pf.symbols}
        assert "属于 first" in by["first"].docstring
        assert by["second"].docstring == ""

    def test_block_comment_without_jsdoc_marker_ignored(self) -> None:
        """非正向：/* ... */（非 /** 开头）不算 JSDoc。"""
        code = "/* 普通块注释 */\nfunction plain(): void {}\n"
        pf = parse_source(code, "javascript", "b.js")
        by = {s.name: s for s in pf.symbols}
        assert by["plain"].docstring == ""

    def test_python_docstring_unaffected(self) -> None:
        """回归：Python 仍走 ast docstring 路径，不受 JSDoc 逻辑影响。"""
        code = 'def f():\n    """中文文档"""\n    return 1\n'
        pf = parse_source(code, "python", "a.py")
        assert pf.symbols[0].docstring == "中文文档"
