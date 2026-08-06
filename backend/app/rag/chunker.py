# Markdown 结构感知切块：围栏感知状态机 + 全层级标题 + 大小控制
# Chunk 支持结构化扩展：metadata / claims / relations，为图 RAG 铺路
#
# 设计要点（docs/design/knowledge-rag-orchestration-review.md §3.7）：
# 1. 围栏感知：``` / ~~~ 代码围栏内的行不参与标题匹配——旧实现用全文正则，
#    md 内嵌代码的 `# 注释` / `#include` 会被误当成标题切开，
#    导致装饰器与函数体被拆进两个 chunk。
# 2. 全层级标题：# ~ #### 均触发切分，metadata 携带完整标题路径。
# 3. 大小控制：超过 MAX_CHUNK_SIZE 的章节在段落边界二次切分 + 10% overlap；
#    小于 MIN_CHUNK_SIZE 的碎块并入前块，避免无语义碎片。
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# 切分参数（注释说明取值理由）
MAX_CHUNK_SIZE = 1200  # bge-m3 友好区间，兼顾语义完整与嵌入精度
OVERLAP_SIZE = 120  # 10% overlap，缓解边界语义断裂
MIN_CHUNK_SIZE = 200  # 小于此的碎块语义不足以独立检索，并入前块

_HEADING_RE = re.compile(r"^(#{1,4})\s+(.*)$")
_FENCE_RE = re.compile(r"^\s*(```|~~~)")


@dataclass
class Chunk:
    """单个文档块

    邻居链：prev_id / next_id 指向同一文档中相邻的 chunk，
    用于检索时扩展上下文窗口（看证据的上下文）。

    结构化字段（为图 RAG 铺路）：
    - metadata: 标题层级、标题路径、文档来源、创建时间等
    - claims: 从该 chunk 提取的声明（预留，迭代三填充）
    - relations: 与其他 chunk 的关系（预留，迭代三填充）
    """

    chunk_id: str
    doc_id: str
    section: str  # 标题文本（不含 # 号）
    text: str
    char_start: int
    char_end: int
    source: str = ""  # doc:section 引用串
    prev_id: str = ""  # 前一个 chunk 的 ID（邻居链）
    next_id: str = ""  # 后一个 chunk 的 ID（邻居链）
    metadata: dict[str, Any] = field(default_factory=dict)
    claims: list[str] = field(default_factory=list)
    relations: list[dict[str, str]] = field(default_factory=list)
    # [Wave 1] 多租户隔离：chunk 所属租户 ID，用于 Qdrant payload 过滤
    tenant_id: int | None = None
    # 会议作用域：chunk 归属的会议 ID，Qdrant 共享 collection 下的隔离边界
    # （所有会议共用 conclave_chunks，仅靠 tenant_id 过滤会跨会议串扰）
    meeting_id: str = ""

    def to_dict(self) -> dict:
        return {
            "chunk_id": self.chunk_id,
            "doc_id": self.doc_id,
            "section": self.section,
            "text": self.text,
            "char_start": self.char_start,
            "char_end": self.char_end,
            "source": self.source,
            "prev_id": self.prev_id,
            "next_id": self.next_id,
            "metadata": self.metadata,
            "claims": self.claims,
            "relations": self.relations,
            "tenant_id": self.tenant_id,
            "meeting_id": self.meeting_id,
        }

    def summary(self, max_len: int = 200) -> str:
        """生成摘要：取前 max_len 字符 + 省略号，用于 prompt 注入。

        配合惰性读取：prompt 只注入摘要，需要全文时按 char_range 展开。
        """
        if len(self.text) <= max_len:
            return self.text
        return self.text[:max_len].rstrip() + "…"


# ---------------------------------------------------------------------------
# 围栏感知标题扫描
# ---------------------------------------------------------------------------


def _find_headings(text: str) -> list[tuple[int, int, str]]:
    """逐行状态机扫描标题，跳过 ``` / ~~~ 代码围栏内的行。

    Returns:
        list of (char_offset, level, title)
    """
    headings: list[tuple[int, int, str]] = []
    in_fence = False
    fence_marker = ""
    pos = 0
    for line in text.split("\n"):
        fence_match = _FENCE_RE.match(line)
        if fence_match:
            marker = fence_match.group(1)
            if not in_fence:
                in_fence = True
                fence_marker = marker
            elif marker == fence_marker:
                # 同标记闭合（``` 配 ```，~~~ 配 ~~~）
                in_fence = False
        elif not in_fence:
            m = _HEADING_RE.match(line)
            if m:
                headings.append((pos, len(m.group(1)), m.group(2).strip()))
        pos += len(line) + 1
    return headings


# ---------------------------------------------------------------------------
# 段落边界二次切分
# ---------------------------------------------------------------------------


def _split_long_section(body: str, start: int) -> list[tuple[int, int]]:
    """将超长章节在段落边界（空行）切分为多个子区间（绝对坐标）。

    子区间带 OVERLAP_SIZE 字符重叠（不超出本章节范围），
    尽量在段落边界切，段落本身超长则硬切。
    """
    end = start + len(body)
    if len(body) <= MAX_CHUNK_SIZE:
        return [(start, end)]

    # 段落边界候选（相对 body 的空行位置）
    boundaries = [m.end() for m in re.finditer(r"\n\s*\n", body)]
    spans: list[tuple[int, int]] = []
    cursor = 0  # 相对 body
    while cursor < len(body):
        target = cursor + MAX_CHUNK_SIZE
        if target >= len(body):
            spans.append((start + cursor, end))
            break
        # 在 target 之前找最近的段落边界（至少推进 MIN_CHUNK_SIZE）
        cut = None
        for b in boundaries:
            if cursor + MIN_CHUNK_SIZE <= b <= target:
                cut = b
            elif b > target:
                break
        if cut is None:
            cut = target  # 无段落边界，硬切
        spans.append((start + cursor, start + cut))
        # 下一段带 overlap 回退，但不越过本段起点
        cursor = max(cut - OVERLAP_SIZE, cursor + 1)
    return spans


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------


def chunk_markdown(text: str, doc_id: str) -> list[Chunk]:
    """按标题层级切分 markdown 文本（围栏感知 + 大小控制）

    切分策略：
    - 标题（# ~ ####）作为新块起点，围栏内的伪标题行忽略
    - 标题之前的引导文本作为首个无标题块
    - 超长块在段落边界二次切分 + 10% overlap
    - 碎块（< MIN_CHUNK_SIZE）并入前块
    - 每个块记录原文区间 [char_start, char_end) 与标题路径
    """
    if not text.strip():
        return []

    headings = _find_headings(text)

    # 原始章节列表：(section_title, level, heading_path, start, end)
    sections: list[tuple[str, int, list[str], int, int]] = []
    # 标题路径栈：维护 (level, title)，遇到同级或更高级标题时弹出
    path_stack: list[tuple[int, str]] = []

    def _path_for(level: int, title: str) -> list[str]:
        while path_stack and path_stack[-1][0] >= level:
            path_stack.pop()
        path_stack.append((level, title))
        return [t for _, t in path_stack]

    if not headings:
        sections.append(("intro", 0, ["intro"], 0, len(text)))
    else:
        # 引导段
        if headings[0][0] > 0 and text[: headings[0][0]].strip():
            sections.append(("intro", 0, ["intro"], 0, headings[0][0]))
        for idx, (hpos, level, title) in enumerate(headings):
            sec_end = headings[idx + 1][0] if idx + 1 < len(headings) else len(text)
            path = _path_for(level, title or f"section-{idx}")
            sections.append((title or f"section-{idx}", level, path, hpos, sec_end))

    # 二次切分 + 构建 chunk（暂存中间结构）
    raw_chunks: list[dict[str, Any]] = []
    for section_title, level, path, start, end in sections:
        body = text[start:end].strip()
        if not body:
            continue
        # strip 后正文起点前移，修正绝对坐标
        stripped_offset = len(text[start:end]) - len(text[start:end].lstrip())
        abs_start = start + stripped_offset
        abs_end = abs_start + len(body)
        spans = _split_long_section(text[abs_start:abs_end], abs_start)
        for part_idx, (span_start, span_end) in enumerate(spans):
            raw_chunks.append(
                {
                    "section": section_title,
                    "level": level,
                    "path": path,
                    "text": text[span_start:span_end].strip(),
                    "char_start": span_start,
                    "char_end": span_end,
                    "part_index": part_idx,
                }
            )

    # 碎块合并：不足 MIN_CHUNK_SIZE 的块并入前块。
    # 关键约束：仅在属于「同一标题章节」时才合并（即超长章节被二次切分后的尾段碎片），
    # 绝不在不同标题之间合并——否则会丢失标题维度的语义切分，破坏 RAG 检索与可观测性。
    merged: list[dict[str, Any]] = []
    for rc in raw_chunks:
        if (
            merged
            and rc["section"] == merged[-1]["section"]
            and len(rc["text"]) < MIN_CHUNK_SIZE
            and len(merged[-1]["text"]) + len(rc["text"]) <= MAX_CHUNK_SIZE * 2
        ):
            prev = merged[-1]
            prev["text"] = prev["text"] + "\n\n" + rc["text"]
            prev["char_end"] = rc["char_end"]
        else:
            merged.append(rc)

    # 构建 Chunk 对象（重新编号 + 邻居链）
    chunks: list[Chunk] = []
    for i, rc in enumerate(merged):
        chunk_id = f"{doc_id}-{i}"
        chunks.append(
            Chunk(
                chunk_id=chunk_id,
                doc_id=doc_id,
                section=rc["section"],
                text=rc["text"],
                char_start=rc["char_start"],
                char_end=rc["char_end"],
                source=f"{doc_id}:{rc['section']}",
                metadata={
                    "heading_level": rc["level"],
                    "heading_path": rc["path"],
                    "section_index": i,
                    "part_index": rc["part_index"],
                    "doc_id": doc_id,
                },
            )
        )
    for i, chunk in enumerate(chunks):
        if i > 0:
            chunk.prev_id = chunks[i - 1].chunk_id
        if i < len(chunks) - 1:
            chunk.next_id = chunks[i + 1].chunk_id
    return chunks
