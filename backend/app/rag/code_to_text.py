# 代码感知预处理（ADR-018 Phase B，D5）：按文件类别三路分派 → LightRAG 摄入文本
#
# ① 符号语言（.py/.js/.ts/.tsx 等）：复用 code_parser 序列化为
#    "符号签名 + docstring/JSDoc + 调用摘要"；
# ② 配置/数据语言（.yaml/.toml/.json/.sql/.ini）：轻量结构摘要 + 原文直入；
# ③ 脚本/文档（.sh/.md/.txt）：原文直入。
#
# 设计要点：
# - 预处理而非改 LightRAG 切块器（D5）：上游保持可升级（D9）。
# - 每篇文档带 [文件] 头（仓库相对路径 + 类别）：让 LightRAG 的实体抽取
#   能把"文件"作为实体、建立跨文件关系（回答"文档 A 与模块 B 什么关系"）。
# - 扩展名不识别 / 文件过大 / 读取失败 / 空文件一律跳过（返回 None），
#   绝不阻断整仓摄入（与 code_parser 的优雅降级哲学一致）。
# - 符号文件在 grammar 缺失或无符号时退化为原文直入，不丢内容。
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from app.logging_config import get_logger
from app.rag.code_parser import language_for_path, parse_source

logger = get_logger("rag.code_to_text")

# ---- 限额（环境变量可调，魔数均注明取值依据） ----
# 单文件大小上限：与 code_parser.MAX_FILE_SIZE 对齐（512KB），跳过压缩 bundle/大文件
MAX_FILE_SIZE = int(os.environ.get("CONCLAVE_CODE_TO_TEXT_MAX_FILE", str(512 * 1024)))
# 单文档预处理文本上限（20K 字符 ≈ 5K token）：控制单篇进入 LLM 抽取的体积，
# 超长截断——LightRAG 固定 token 切块会再切，这里先压一层防止巨型文件拖垮批次
MAX_DOC_CHARS = int(os.environ.get("CONCLAVE_CODE_TO_TEXT_MAX_CHARS", str(20_000)))
# 单文件序列化符号数上限：超大文件只保留前 N 个符号定义，避免单文档爆炸
MAX_SYMBOLS_PER_DOC = int(os.environ.get("CONCLAVE_CODE_TO_TEXT_MAX_SYMBOLS", "200"))
# 单文件调用摘要条数上限（按调用方聚合前的原始条数）
MAX_CALLS_PER_DOC = int(os.environ.get("CONCLAVE_CODE_TO_TEXT_MAX_CALLS", "500"))
# SQL DDL 语句头摘要条数上限
MAX_SQL_DDL_HEADS = 50

# 三路分派的扩展名集合（D5 明文范围；其余扩展名跳过）
SYMBOL_EXTS = {".py", ".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx"}
CONFIG_EXTS = {".yaml", ".yml", ".toml", ".json", ".sql", ".ini"}
PLAIN_EXTS = {".sh", ".md", ".txt"}

# 仓库扫描跳过的目录（VCS/依赖/构建产物/缓存/IDE 配置）
SKIP_DIRS = {
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "dist",
    "build",
    ".next",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".idea",
    ".vscode",
    ".tox",
    "target",
}

CATEGORY_SYMBOL = "symbol"
CATEGORY_CONFIG = "config"
CATEGORY_PLAIN = "plain"

# 结构摘要的轻量正则（不引入额外解析器依赖；YAML 优先用 PyYAML）
_RE_YAML_KEY = re.compile(r"^([A-Za-z0-9_\-\.]+)\s*:", re.MULTILINE)
_RE_TOML_SECTION = re.compile(r"^\[([^\]]+)\]", re.MULTILINE)
_RE_INI_SECTION = re.compile(r"^\[([^\]]+)\]", re.MULTILINE)
_RE_SQL_DDL = re.compile(
    r"^\s*(CREATE|ALTER|DROP)\s+(TABLE|INDEX|VIEW|DATABASE|SCHEMA|TYPE|FUNCTION)[^\n;]*",
    re.IGNORECASE | re.MULTILINE,
)


@dataclass
class FileDocument:
    """单个文件预处理后的摄入文档。

    - rel_path: 仓库相对路径（POSIX 分隔），同时作为 LightRAG 的 file_path
      （引用溯源 + DocStatus 按文件定位的依据）
    - category: symbol | config | plain（三路分派结果）
    - text: 供 LightRAG 摄入的预处理文本（含 [文件] 头）
    """

    rel_path: str
    category: str
    text: str

    @property
    def char_count(self) -> int:
        return len(self.text)


def classify_file(path: str | Path) -> str:
    """按扩展名分派文件类别；不在三路范围内返回空串（调用方跳过）。"""
    suffix = Path(path).suffix.lower()
    if suffix in SYMBOL_EXTS:
        return CATEGORY_SYMBOL
    if suffix in CONFIG_EXTS:
        return CATEGORY_CONFIG
    if suffix in PLAIN_EXTS:
        return CATEGORY_PLAIN
    return ""


def _cap(text: str, limit: int | None = None) -> str:
    """超长文本截断 + 标注原长（保证截断后仍 ≤ limit）。limit 缺省取模块级 MAX_DOC_CHARS。"""
    if limit is None:
        limit = MAX_DOC_CHARS
    if len(text) <= limit:
        return text
    marker = f"\n…（已截断，原文共 {len(text)} 字符）"
    return text[: max(0, limit - len(marker))].rstrip() + marker


def _read_text(path: Path) -> str | None:
    """读取文件文本；过大/读失败返回 None（跳过，不阻断整仓）。"""
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if len(data) > MAX_FILE_SIZE:
        return None
    return data.decode("utf-8", errors="replace")


def _header(rel_path: str, label: str) -> str:
    return f"[文件] {rel_path}（{label}）"


# ---------------------------------------------------------------------------
# ① 符号语言：签名 + docstring/JSDoc + 调用摘要
# ---------------------------------------------------------------------------


def _serialize_symbol_doc(rel_path: str, language: str, code: str) -> str:
    """把符号文件的解析结果序列化为结构化描述文本。

    无符号可抽（纯脚本式模块）时返回空串，调用方退化原文直入。
    """
    parsed = parse_source(code, language, rel_path)
    if not parsed.supported or not parsed.symbols:
        return ""

    lines: list[str] = [f"[符号] 共 {len(parsed.symbols)} 个"]
    for sym in parsed.symbols[:MAX_SYMBOLS_PER_DOC]:
        entry = f"- [{sym.kind}] {sym.signature}"
        desc = sym.docstring or sym.body_head
        if desc:
            # 描述多行时缩进对齐，保持可读性（LLM 抽取友好）
            entry += "\n" + "\n".join(f"  {ln}" for ln in desc.splitlines() if ln.strip())
        lines.append(entry)
    if len(parsed.symbols) > MAX_SYMBOLS_PER_DOC:
        lines.append(f"…（其余 {len(parsed.symbols) - MAX_SYMBOLS_PER_DOC} 个符号已省略）")

    # 调用摘要：按调用方聚合被叫名（去重保序），给出"谁调用谁"的语义线索
    callees_by_caller: dict[str, list[str]] = {}
    for call in parsed.calls[:MAX_CALLS_PER_DOC]:
        bucket = callees_by_caller.setdefault(call.caller_qualified, [])
        if call.callee_name and call.callee_name not in bucket:
            bucket.append(call.callee_name)
    if callees_by_caller:
        lines.append("[调用]")
        for caller, callees in callees_by_caller.items():
            lines.append(f"- {caller} 调用 {'、'.join(callees)}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# ② 配置/数据语言：轻量结构摘要
# ---------------------------------------------------------------------------


def _config_summary(text: str, ext: str) -> str:
    """提取配置/数据文件的轻量结构摘要；无法识别时返回空串（原文仍会直入）。"""
    if ext in (".yaml", ".yml"):
        keys = _yaml_top_keys(text)
        return f"顶级键: {'、'.join(keys)}" if keys else ""
    if ext == ".toml":
        sections = _RE_TOML_SECTION.findall(text)
        return f"小节: {'、'.join(sections[:30])}" if sections else ""
    if ext == ".json":
        return _json_top_summary(text)
    if ext == ".sql":
        heads = _sql_ddl_heads(text)
        return f"DDL 语句头: {'; '.join(heads)}" if heads else ""
    if ext == ".ini":
        sections = _RE_INI_SECTION.findall(text)
        return f"小节: {'、'.join(sections[:30])}" if sections else ""
    return ""


def _yaml_top_keys(text: str) -> list[str]:
    """YAML 顶级键：优先 PyYAML 解析，失败退回行首正则（多文档/锚点等复杂场景兜底）。"""
    try:
        import yaml

        loaded = yaml.safe_load(text)
        if isinstance(loaded, dict):
            return [str(k) for k in list(loaded.keys())[:30]]
    except Exception:
        pass
    return _RE_YAML_KEY.findall(text)[:30]


def _json_top_summary(text: str) -> str:
    """JSON 顶级结构：对象给键名，数组给长度；解析失败返回空串。"""
    try:
        loaded = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return ""
    if isinstance(loaded, dict):
        keys = [str(k) for k in list(loaded.keys())[:30]]
        return f"顶级键: {'、'.join(keys)}" if keys else "空对象"
    if isinstance(loaded, list):
        return f"JSON 数组（{len(loaded)} 项）"
    return ""


def _sql_ddl_heads(text: str) -> list[str]:
    """SQL DDL 语句头（CREATE/ALTER/DROP ...）：每条截 120 字符，最多 N 条。"""
    heads: list[str] = []
    for m in _RE_SQL_DDL.finditer(text):
        head = m.group(0).strip()[:120]
        heads.append(head)
        if len(heads) >= MAX_SQL_DDL_HEADS:
            break
    return heads


# ---------------------------------------------------------------------------
# 分派入口
# ---------------------------------------------------------------------------


def file_to_document(path: Path, repo_root: Path) -> FileDocument | None:
    """预处理单个文件为摄入文档；跳过时返回 None。"""
    try:
        rel = path.relative_to(repo_root).as_posix()
    except ValueError:
        rel = path.as_posix()

    category = classify_file(path)
    if category == "":
        return None
    text = _read_text(path)
    if text is None or not text.strip():
        return None

    if category == CATEGORY_SYMBOL:
        language = language_for_path(path)
        body = _serialize_symbol_doc(rel, language, text)
        if body:
            doc_text = f"{_header(rel, f'语言: {language}')}\n{body}"
        else:
            # grammar 缺失或无符号定义：退化原文直入，不丢内容
            doc_text = f"{_header(rel, f'语言: {language}，无符号摘要')}\n{_cap(text)}"
        return FileDocument(rel_path=rel, category=category, text=_cap(doc_text))

    if category == CATEGORY_CONFIG:
        ext = path.suffix.lower()
        summary = _config_summary(text, ext)
        parts = [_header(rel, "配置")]
        if summary:
            parts.append(f"[结构摘要] {summary}")
        parts.append("[原文]")
        parts.append(_cap(text))
        return FileDocument(rel_path=rel, category=category, text=_cap("\n".join(parts)))

    # ③ 脚本/文档：原文直入
    doc_text = f"{_header(rel, '文档')}\n{_cap(text)}"
    return FileDocument(rel_path=rel, category=category, text=_cap(doc_text))


def repo_to_documents(repo_root: str | Path) -> list[FileDocument]:
    """扫描仓库生成全部摄入文档（按相对路径排序，保证批次确定性）。

    跳过 SKIP_DIRS 与三路范围外的文件；单文件失败只跳过该文件。
    """
    root = Path(repo_root).resolve()
    if not root.is_dir():
        return []
    docs: list[FileDocument] = []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        try:
            doc = file_to_document(p, root)
        except Exception as e:  # 单文件异常不阻断整仓（降级哲学）
            logger.warning("预处理跳过文件 %s: %s: %s", p, type(e).__name__, e)
            continue
        if doc is not None:
            docs.append(doc)
    return docs
