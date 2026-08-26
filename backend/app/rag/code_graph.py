# 代码知识图谱构图（ADR-016 Phase B）：File/Symbol/Doc 节点 + 关系边
#
# 边语义：
#   DEFINES    file -> symbol           （文件定义符号，恒成立）
#   CALLS      symbol -> symbol          （同文件内、按简单名唯一消歧）
#   INHERITS   class -> class            （同文件内、按简单名唯一消歧）
# 跨文件 import 解析 / 别名消歧 / DEPENDS_ON(package 清单) / REFERENCES(文档→符号) 均留 Phase C。
# 跨文件或歧义调用/继承暂不落边，避免同名错连（ADR-016 D3 风险）。
from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from app.rag.code_parser import ParsedFile, language_for_path, parse_file

# 构图时跳过的目录（避免 node_modules/.git 等巨型无关目录拖慢解析）
_SKIP_DIRS = {
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "dist",
    "build",
    "target",
    ".idea",
    ".vscode",
    "coverage",
    ".mypy_cache",
    ".pytest_cache",
    ".next",
    ".nuxt",
}

# 文档节点扩展名（README/设计文档/注释文件，后续 REFERENCES 边连到符号）
_DOC_EXTENSIONS = {".md", ".markdown", ".rst", ".txt"}

# 单仓构图最大文件数（默认 5000），防极端仓库拖垮构图
MAX_REPO_FILES = int(os.environ.get("CONCLAVE_CODE_GRAPH_MAX_FILES", "5000"))


@dataclass
class CodeNode:
    """图节点：file / symbol / doc。"""

    node_id: str
    kind: str  # file | symbol | doc
    name: str
    file_path: str  # symbol 为其源文件相对路径；file/doc 为自身路径
    language: str = ""
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "node_id": self.node_id,
            "kind": self.kind,
            "name": self.name,
            "file_path": self.file_path,
            "language": self.language,
            "metadata": self.metadata,
        }


@dataclass
class CodeEdge:
    """关系边。"""

    edge_type: str
    src: str
    dst: str
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"edge_type": self.edge_type, "src": self.src, "dst": self.dst, "metadata": self.metadata}


@dataclass
class CodeGraph:
    """构图结果。"""

    nodes: list[CodeNode] = field(default_factory=list)
    edges: list[CodeEdge] = field(default_factory=list)

    def add_node(self, node: CodeNode) -> None:
        self.nodes.append(node)

    def add_edge(self, edge_type: str, src: str, dst: str, **meta) -> None:
        self.edges.append(CodeEdge(edge_type=edge_type, src=src, dst=dst, metadata=meta))

    def node_ids(self) -> set[str]:
        return {n.node_id for n in self.nodes}


def _last_component(name: str) -> str:
    """取限定/点分名的最后一段：os.path.join -> join，A::m -> m。"""
    return name.replace("::", ".").split(".")[-1]


def _resolve_simple(
    simple_index: dict[str, list[tuple[str, str]]], name: str, kinds: set[str] | None = None
) -> str | None:
    """按简单名唯一消歧到同文件符号；歧义/未命中返回 None。"""
    cands = simple_index.get(_last_component(name), [])
    if kinds is not None:
        cands = [(q, k) for q, k in cands if k in kinds]
    return cands[0][0] if len(cands) == 1 else None


# ---------------------------------------------------------------------------
# 纯构图（输入已解析文件，便于无 tree-sitter 的单测）
# ---------------------------------------------------------------------------


def build_graph_from_parsed(parsed_files: Iterable[ParsedFile]) -> CodeGraph:
    """由 ParsedFile 列表组装图（核心逻辑，不依赖 I/O 与 tree-sitter）。

    - 每个受支持文件 → 1 个 File 节点 + N 个 Symbol 节点 + DEFINES 边
    - CALLS / INHERITS 仅在同文件内、简单名唯一命中时落边；否则跳过（Phase C 再消歧）
    """
    graph = CodeGraph()
    seen_edges: set[tuple[str, str, str]] = set()

    def _edge(etype: str, src: str, dst: str, **meta) -> None:
        key = (etype, src, dst)
        if key in seen_edges:
            return
        seen_edges.add(key)
        graph.add_edge(etype, src, dst, **meta)

    for pf in parsed_files:
        if not pf.supported or not pf.path:
            continue

        # File 节点
        graph.add_node(
            CodeNode(
                node_id=pf.path,
                kind="file",
                name=Path(pf.path).name,
                file_path=pf.path,
                language=pf.language,
                metadata={"imports": [i.module for i in pf.imports]},
            )
        )

        # Symbol 节点按简单名建索引（同文件内消歧），索引存 (qualified_name, symbol_kind)
        simple_index: dict[str, list[tuple[str, str]]] = {}
        for sym in pf.symbols:
            graph.add_node(
                CodeNode(
                    node_id=sym.qualified_name,
                    kind="symbol",
                    name=sym.name,
                    file_path=pf.path,
                    language=pf.language,
                    metadata={
                        "symbol_kind": sym.kind,
                        "class_name": sym.class_name,
                        "start_line": sym.start_line,
                        "end_line": sym.end_line,
                        "char_start": sym.char_start,
                        "char_end": sym.char_end,
                        "signature": sym.signature,
                        "docstring": sym.docstring,
                        "body_head": sym.body_head,
                    },
                )
            )
            _edge("DEFINES", pf.path, sym.qualified_name, symbol_kind=sym.kind)
            simple_index.setdefault(_last_component(sym.name), []).append((sym.qualified_name, sym.kind))

        # CALLS：同文件唯一命中才落边（自调用 self-loop 是合法的递归关系，保留）
        for call in pf.calls:
            target = _resolve_simple(simple_index, call.callee_name)
            if target is not None:
                _edge("CALLS", call.caller_qualified, target, line=call.line)

        # INHERITS：同文件唯一命中到 class 落边
        for inh in pf.inherits:
            target = _resolve_simple(simple_index, inh.base_name, kinds={"class"})
            if target is not None and target != inh.class_qualified:
                _edge("INHERITS", inh.class_qualified, target, line=inh.line)

    return graph


# ---------------------------------------------------------------------------
# 文件系统构图（仓级入口）
# ---------------------------------------------------------------------------


def is_doc_file(path: Path) -> bool:
    """判断是否为文档节点（README/设计文档/注释）。"""
    return path.suffix.lower() in _DOC_EXTENSIONS


def build_graph(repo_root: Path) -> CodeGraph:
    """扫描仓库、解析、构图（真实 I/O 入口）。

    跳过 _SKIP_DIRS 目录与 _DOC_EXTENSIONS 之外的未知文件；
    超 MAX_REPO_FILES 停止增量（防巨型仓库拖垮构图）。
    """
    repo_root = repo_root.resolve()
    parsed: list[ParsedFile] = []
    doc_nodes: list[CodeNode] = []
    file_count = 0

    for path in sorted(repo_root.rglob("*")):
        if any(part in _SKIP_DIRS for part in path.relative_to(repo_root).parts):
            continue
        if not path.is_file():
            continue
        file_count += 1
        if file_count > MAX_REPO_FILES:
            break

        if language_for_path(path):
            parsed.append(parse_file(path, repo_root))
        elif is_doc_file(path):
            rel = path.relative_to(repo_root).as_posix()
            doc_nodes.append(CodeNode(node_id=rel, kind="doc", name=path.name, file_path=rel))

    graph = build_graph_from_parsed(parsed)
    for dn in doc_nodes:
        graph.add_node(dn)
    return graph
