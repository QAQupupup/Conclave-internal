# 代码解析（ADR-016 Phase B）：tree-sitter 多语言 AST 抽取符号 / import / 调用 / 继承
#
# 设计要点：
# - tree-sitter 容错解析（代码不完整也能出 AST），首批语言 Python + JavaScript + TypeScript(+TSX)
# - grammar 懒加载 + 优雅降级：某语言 grammar 缺失/版本不匹配时返回 supported=False，
#   由调用方跳过该文件，绝不阻断整仓摄入（对应项目 StubLLM / Cython→py 的降级惯例）
# - 符号限定名 file::class::method（ADR-016 D3），缓解同名符号错连
# - 只做"结构抽取"，不做跨文件 import 解析 / 别名消歧（属 Phase C）
from __future__ import annotations

import importlib
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# 单文件解析大小上限（默认 512KB）：跳过压缩 bundle / 超大豆文件
MAX_FILE_SIZE = int(os.environ.get("CONCLAVE_CODE_PARSE_MAX_FILE", str(512 * 1024)))

# 符号正文头部截取长度（无 docstring 时用于 chunk 文本，避免把整个函数体塞进索引）
BODY_HEAD_CHARS = 400

# language → (grammar 模块名, language 构造器属性)
_GRAMMAR_MODULES: dict[str, tuple[str, str]] = {
    "python": ("tree_sitter_python", "language"),
    "javascript": ("tree_sitter_javascript", "language"),
    "typescript": ("tree_sitter_typescript", "language_typescript"),
    "tsx": ("tree_sitter_typescript", "language_tsx"),
}

# 扩展名 → 语言
_EXT_TO_LANG: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
}

# Python / JS 共用的结构节点类型识别（按语言分派）
_PY_CLASS = "class_definition"
_PY_FUNC = "function_definition"
_PY_CALL = "call"
_PY_IMPORT = "import_statement"
_PY_IMPORT_FROM = "import_from_statement"

_JS_CLASS = "class_declaration"
_JS_FUNC = {"function_declaration", "generator_function_declaration"}
_JS_METHOD = "method_definition"
_JS_TYPE = {"interface_declaration", "type_alias_declaration"}
_JS_CALL = "call_expression"
_JS_IMPORT = "import_statement"

# JS/TS 基类名节点类型（tree-sitter-javascript 0.25 / typescript 0.23 语法）
# 说明：TS 的 extends 用 type_identifier / nested_type_identifier / member_expression，
# JS 的 extends 用 identifier / member_expression。
_JS_BASE_TYPES = {
    "identifier",
    "type_identifier",
    "member_expression",
    "nested_identifier",
    "nested_type_identifier",
}

# 基类名抽取时跳过的子树：type_arguments / type_parameters
# （`Base<T>` 中 T 是类型实参，不是基类；旧 grammar 的 generic_type 也靠跳过 type_arguments 兜底）
_SKIP_BASE_SUBTREES = {"type_arguments", "type_parameters"}


@dataclass
class Symbol:
    """一个代码符号（函数/方法/类/接口/类型别名）。"""

    name: str
    kind: str  # function | method | class | type
    qualified_name: str  # 限定名 file::A::m
    class_name: str  # 所在类的限定名（"" 表示模块级）
    start_line: int  # 1-based
    end_line: int  # 1-based 闭区间
    char_start: int
    char_end: int
    text: str  # 符号源码全文（docstring/body 懒读用）
    signature: str  # 定义首行（def/class/function 声明）
    docstring: str  # Python 文档字符串 / JS/TS 紧邻声明的 JSDoc（ADR-018 D5）
    body_head: str = ""  # 正文头部（无 docstring 时用作检索摘要）


@dataclass
class ImportRef:
    """一条 import（模块名 + 别名 + 行号），跨文件解析在 Phase C。"""

    module: str
    alias: str | None
    line: int


@dataclass
class CallRef:
    """一条调用（呼叫方符号限定名 → 被叫名）。被叫名是原始文本，同名消歧属 Phase C。"""

    caller_qualified: str
    callee_name: str
    line: int


@dataclass
class InheritRef:
    """一条继承（子类限定名 → 基类名）。"""

    class_qualified: str
    base_name: str
    line: int


@dataclass
class ParsedFile:
    """单个源码文件的解析结果。

    supported=False 表示被跳过（扩展名不支持 / grammar 缺失 / 过大 / 读失败），
    调用方据此决定是否继续构图。
    """

    path: str  # 仓库相对路径（POSIX 分隔）
    language: str  # "" 表示无法识别语言
    supported: bool = True
    error: str = ""
    symbols: list[Symbol] = field(default_factory=list)
    imports: list[ImportRef] = field(default_factory=list)
    calls: list[CallRef] = field(default_factory=list)
    inherits: list[InheritRef] = field(default_factory=list)


# ---------------------------------------------------------------------------
# grammar 懒加载与缓存
# ---------------------------------------------------------------------------

_lang_cache: dict[str, Any] = {}
_lang_checked = False


def _get_languages() -> dict[str, Any]:
    """懒加载各语言 grammar，返回 language -> tree_sitter.Language（或 None）。"""
    global _lang_checked
    if _lang_checked:
        return _lang_cache
    _lang_checked = True
    try:
        from tree_sitter import Language
    except Exception:  # tree-sitter 未安装
        for lang in _GRAMMAR_MODULES:
            _lang_cache[lang] = None
        return _lang_cache
    for lang, (mod_name, attr) in _GRAMMAR_MODULES.items():
        try:
            mod = importlib.import_module(mod_name)
            _lang_cache[lang] = Language(getattr(mod, attr)())
        except Exception:  # grammar 缺失或版本不匹配 → 该语言不可用
            _lang_cache[lang] = None
    return _lang_cache


def language_for_path(path: str | Path) -> str:
    """按扩展名返回语言名；无法识别返回空串。"""
    suffix = Path(path).suffix.lower()
    return _EXT_TO_LANG.get(suffix, "")


def tree_sitter_available() -> bool:
    """tree-sitter 是否可用（供调用方做降级判断与测试 skip）。"""
    return any(v is not None for v in _get_languages().values())


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------


def _norm_path(path: str | Path) -> str:
    return Path(path).as_posix()


def _field_text(node: Any, field: str) -> str:
    child = node.child_by_field_name(field)
    if child is None:
        return ""
    return str(child.text.decode("utf-8", errors="replace"))


def _iter_all(node: Any):
    """递归遍历子树（含自身）。"""
    yield node
    for c in node.children:
        yield from _iter_all(c)


def _collect_js_bases(heritage: Any) -> list[str]:
    """从 JS/TS class_heritage 子树抽取基类/接口名。

    - 命中基类名节点类型即记录并停止下钻（避免同名嵌套标识符重复）
    - 跳过 type_arguments / type_parameters（`Base<T>` 不把 T 当基类）
    """
    names: list[str] = []

    def _rec(node: Any) -> None:
        t = node.type
        if t in _JS_BASE_TYPES:
            names.append(node.text.decode("utf-8", errors="replace"))
            return
        if t in _SKIP_BASE_SUBTREES:
            return
        for c in node.children:
            _rec(c)

    _rec(heritage)
    return names


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------


def parse_source(code: str, language: str, file_path: str = "") -> ParsedFile:
    """解析源码文本，返回 ParsedFile（含符号 / import / 调用 / 继承）。

    Args:
        code: 源码全文
        language: language_for_path 的返回值（python/javascript/typescript/tsx）
        file_path: 展示用的仓库相对路径（用于限定名前缀）
    """
    lang_obj = _get_languages().get(language)
    if lang_obj is None:
        return ParsedFile(path=_norm_path(file_path), language=language, supported=False, error="grammar_unavailable")

    from tree_sitter import Parser

    src_bytes = code.encode("utf-8", errors="replace")
    parser = Parser(lang_obj)
    tree = parser.parse(src_bytes)
    root = tree.root_node

    base = _norm_path(file_path) or "<module>"
    module_qname = f"{base}::<module>"

    symbols: list[Symbol] = []
    imports: list[ImportRef] = []
    calls: list[CallRef] = []
    inherits: list[InheritRef] = []
    scope_stack: list[str] = []

    def dec(b: bytes) -> str:
        return b.decode("utf-8", errors="replace")

    def char_off(byte_off: int) -> int:
        return len(src_bytes[:byte_off].decode("utf-8", errors="replace"))

    def make_symbol(node: Any, kind: str, class_qname: str) -> Symbol:
        start_line = node.start_point.row + 1
        end_line = node.end_point.row + 1
        # end_point 落在下一行首（column==0）时，结束行回退一行
        if node.end_point.column == 0 and node.end_point.row > node.start_point.row:
            end_line = node.end_point.row
        cs = char_off(node.start_byte)
        ce = char_off(node.end_byte)
        text = code[cs:ce]
        name = _field_text(node, "name")
        qname = f"{class_qname}::{name}" if class_qname else f"{base}::{name}"
        signature = text[: text.find("\n")].strip() if text else ""
        docstring = _py_docstring(node, text) if language == "python" else _js_doc_comment(node)
        # body_head：签名行之后的正文头部（无 docstring 时用作检索摘要）
        rest = text[len(signature) :].strip().strip("\n") if signature else text.strip()
        if docstring:
            rest = rest[len(docstring) :].strip().strip("\n")
        body_head = rest[:BODY_HEAD_CHARS]
        return Symbol(
            name=name,
            kind=kind,
            qualified_name=qname,
            class_name=class_qname,
            start_line=start_line,
            end_line=end_line,
            char_start=cs,
            char_end=ce,
            text=text,
            signature=signature,
            docstring=docstring,
            body_head=body_head,
        )

    def record_call(node: Any) -> None:
        fn = node.child_by_field_name("function")
        if fn is None:
            return
        caller = scope_stack[-1] if scope_stack else module_qname
        calls.append(CallRef(caller_qualified=caller, callee_name=dec(fn.text), line=node.start_point.row + 1))

    def record_inherits_py(node: Any, sym: Symbol) -> None:
        super_node = node.child_by_field_name("superclasses")
        if super_node is None:
            return
        for c in _iter_all(super_node):
            if c.type in ("identifier", "attribute", "dotted_name"):
                inherits.append(
                    InheritRef(class_qualified=sym.qualified_name, base_name=dec(c.text), line=node.start_point.row + 1)
                )

    def record_inherits_js(node: Any, sym: Symbol) -> None:
        heritage = node.child_by_field_name("class_heritage")
        if heritage is None:
            # tree-sitter-javascript 0.25 / typescript 0.23：class_heritage 不再是命名 field，
            # 改为按 named child 定位
            for c in node.named_children:
                if c.type == "class_heritage":
                    heritage = c
                    break
        if heritage is None:
            return
        for base in _collect_js_bases(heritage):
            inherits.append(
                InheritRef(class_qualified=sym.qualified_name, base_name=base, line=node.start_point.row + 1)
            )

    def record_import_py(node: Any) -> None:
        for c in node.children:
            if c.type == "dotted_name":
                imports.append(ImportRef(module=dec(c.text), alias=None, line=node.start_point.row + 1))
            elif c.type == "aliased_import":
                name_node = c.child_by_field_name("name")
                module = dec(name_node.text) if name_node is not None else dec(c.text)
                imports.append(ImportRef(module=module, alias=dec(c.text), line=node.start_point.row + 1))

    def record_import_from_py(node: Any) -> None:
        module = ""
        mn = node.child_by_field_name("module_name")
        if mn is not None:
            module = dec(mn.text)
        else:
            for c in node.children:
                if c.type == "dotted_name":
                    module = dec(c.text)
                    break
        if module:
            imports.append(ImportRef(module=module, alias=None, line=node.start_point.row + 1))

    def record_import_js(node: Any) -> None:
        src_node = node.child_by_field_name("source")
        if src_node is None:
            return
        module = dec(src_node.text).strip("\"'")
        imports.append(ImportRef(module=module, alias=None, line=node.start_point.row + 1))

    def walk(node: Any, class_qname: str = "") -> None:
        t = node.type
        if language == "python":
            if t == _PY_CLASS:
                sym = make_symbol(node, "class", class_qname)
                symbols.append(sym)
                scope_stack.append(sym.qualified_name)
                record_inherits_py(node, sym)
                for c in node.children:
                    walk(c, sym.qualified_name)
                scope_stack.pop()
                return
            if t == _PY_FUNC:
                kind = "method" if class_qname else "function"
                sym = make_symbol(node, kind, class_qname)
                symbols.append(sym)
                scope_stack.append(sym.qualified_name)
                for c in node.children:
                    walk(c, class_qname)
                scope_stack.pop()
                return
            if t == _PY_CALL:
                record_call(node)
            elif t == _PY_IMPORT:
                record_import_py(node)
            elif t == _PY_IMPORT_FROM:
                record_import_from_py(node)
        else:  # javascript / typescript / tsx
            if t == _JS_CLASS:
                sym = make_symbol(node, "class", class_qname)
                symbols.append(sym)
                scope_stack.append(sym.qualified_name)
                record_inherits_js(node, sym)
                for c in node.children:
                    walk(c, sym.qualified_name)
                scope_stack.pop()
                return
            if t in _JS_FUNC:
                kind = "method" if class_qname else "function"
                sym = make_symbol(node, kind, class_qname)
                symbols.append(sym)
                scope_stack.append(sym.qualified_name)
                for c in node.children:
                    walk(c, class_qname)
                scope_stack.pop()
                return
            if t == _JS_METHOD:
                sym = make_symbol(node, "method", class_qname)
                symbols.append(sym)
                scope_stack.append(sym.qualified_name)
                for c in node.children:
                    walk(c, class_qname)
                scope_stack.pop()
                return
            if t in _JS_TYPE:
                # 接口/类型别名不进入调用栈（其成员解析暂略）
                sym = make_symbol(node, "type", class_qname)
                symbols.append(sym)
                for c in node.children:
                    walk(c, class_qname)
                return
            if t == _JS_CALL:
                record_call(node)
            elif t == _JS_IMPORT:
                record_import_js(node)

        # 其余节点继续递归（含 decorated_definition 包裹、nested 调用等）
        for c in node.children:
            walk(c, class_qname)

    walk(root)
    return ParsedFile(
        path=_norm_path(file_path),
        language=language,
        supported=True,
        symbols=symbols,
        imports=imports,
        calls=calls,
        inherits=inherits,
    )


def parse_file(path: Path, repo_root: Path) -> ParsedFile:
    """读取并解析单个文件；扩展名不支持/过大/读失败时返回 supported=False。"""
    try:
        rel = path.relative_to(repo_root).as_posix()
    except ValueError:
        rel = path.as_posix()

    lang = language_for_path(path)
    if lang == "":
        return ParsedFile(path=rel, language="", supported=False, error="unsupported_extension")

    try:
        data = path.read_bytes()
    except OSError as e:
        return ParsedFile(path=rel, language=lang, supported=False, error=f"read_error:{e}")

    if len(data) > MAX_FILE_SIZE:
        return ParsedFile(path=rel, language=lang, supported=False, error="too_large")

    return parse_source(data.decode("utf-8", errors="replace"), lang, rel)


# ---------------------------------------------------------------------------
# 文档字符串 / 签名提取
# ---------------------------------------------------------------------------


def _py_docstring(node: Any, text: str) -> str:
    """提取 Python 函数/类体的首个字符串文档；无则返回空串。"""
    body = node.child_by_field_name("body")
    if body is None:
        return ""
    # body 下第一个 expression_statement -> string
    for stmt in body.children:
        if stmt.type == "expression_statement":
            for child in stmt.children:
                if child.type == "string":
                    s = child.text.decode("utf-8", errors="replace")
                    return str(s.strip("\"'").strip())
    return ""


def _clean_jsdoc(raw: str) -> str:
    """清洗 JSDoc 注释块：去掉 /** */ 边界与每行前导 *，保留正文。"""
    lines: list[str] = []
    for line in raw.splitlines():
        s = line.strip()
        if s.startswith("/**"):
            s = s[3:]
        if s.endswith("*/"):
            s = s[:-2]
        s = s.lstrip("*").strip()
        if s:
            lines.append(s)
    return "\n".join(lines)


def _js_doc_comment(node: Any) -> str:
    """提取紧邻声明节点之前的 JSDoc 注释（/** ... */）；无则返回空串（ADR-018 D5）。

    - 只认"紧邻"：声明与注释之间隔了其他节点（如另一个声明）则不提取，
      避免把无关注释误当文档。
    - ``export function foo`` 的注释位于 export_statement 之前，需上提一层查找。
    - 普通 ``//`` 行注释与非 /** 开头的块注释不算 JSDoc，直接返回空串。
    """
    target = node
    parent = node.parent
    if parent is not None and parent.type == "export_statement":
        target = parent
    sib = target.prev_sibling
    if sib is None or sib.type != "comment":
        return ""
    raw = str(sib.text.decode("utf-8", errors="replace"))
    if not raw.startswith("/**"):
        return ""
    return _clean_jsdoc(raw)
