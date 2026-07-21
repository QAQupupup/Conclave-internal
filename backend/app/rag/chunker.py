# Markdown 按标题切块：以 # / ## 切分，保留 char_start/char_end
# Chunk 支持结构化扩展：metadata / claims / relations，为图 RAG 铺路
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Chunk:
    """单个文档块

    邻居链：prev_id / next_id 指向同一文档中相邻的 chunk，
    用于检索时扩展上下文窗口（看证据的上下文）。

    结构化字段（为图 RAG 铺路）：
    - metadata: 标题层级、文档来源、创建时间等
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
        }

    def summary(self, max_len: int = 200) -> str:
        """生成摘要：取前 max_len 字符 + 省略号，用于 prompt 注入。

        配合惰性读取：prompt 只注入摘要，需要全文时按 char_range 展开。
        """
        if len(self.text) <= max_len:
            return self.text
        return self.text[:max_len].rstrip() + "…"


# 匹配 markdown 标题行（# 或 ## 开头）
_HEADING_RE = re.compile(r"^(#{1,2})\s+(.*)$", re.MULTILINE)


def chunk_markdown(text: str, doc_id: str) -> list[Chunk]:
    """按 # / ## 标题切分 markdown 文本

    切分策略：每个标题作为新块的起点，块内保留正文。
    标题之前的引导文本作为首个无标题块。
    每个块记录在原文中的字符区间 [char_start, char_end)。
    """
    chunks: list[Chunk] = []
    # 找到所有标题位置
    matches = list(_HEADING_RE.finditer(text))

    if not matches:
        # 无标题，整篇一个块
        if text.strip():
            chunks.append(
                Chunk(
                    chunk_id=f"{doc_id}-0",
                    doc_id=doc_id,
                    section="intro",
                    text=text.strip(),
                    char_start=0,
                    char_end=len(text),
                    source=f"{doc_id}:intro",
                )
            )
        return chunks

    # 标题之前的引导段
    first_start = matches[0].start()
    if first_start > 0 and text[:first_start].strip():
        guide = text[:first_start].strip()
        chunks.append(
            Chunk(
                chunk_id=f"{doc_id}-intro",
                doc_id=doc_id,
                section="intro",
                text=guide,
                char_start=0,
                char_end=first_start,
                source=f"{doc_id}:intro",
            )
        )

    # 按标题切块
    for idx, m in enumerate(matches):
        level = len(m.group(1))
        section = m.group(2).strip() or f"section-{idx}"
        start = m.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        if body:
            chunks.append(
                Chunk(
                    chunk_id=f"{doc_id}-{idx}",
                    doc_id=doc_id,
                    section=section,
                    text=body,
                    char_start=start,
                    char_end=end,
                    source=f"{doc_id}:{section}",
                    metadata={
                        "heading_level": level,
                        "section_index": idx,
                        "doc_id": doc_id,
                    },
                )
            )
    # 建立邻居链：prev_id / next_id 串联同一文档的所有 chunk
    for i, chunk in enumerate(chunks):
        if i > 0:
            chunk.prev_id = chunks[i - 1].chunk_id
        if i < len(chunks) - 1:
            chunk.next_id = chunks[i + 1].chunk_id
    return chunks
