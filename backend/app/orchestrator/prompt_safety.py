"""M1.4: 提示词指令注入防护

防止用户输入/RAG 检索结果/文档内容中的恶意指令劫持 LLM。

两层防护：
1. 内容清洗：移除/转义常见的指令注入模式（角色标记、系统指令、控制字符）
2. 分隔符包裹：用明确的边界标记将外部内容与系统指令隔离

参考：
- OWASP LLM Top 10 - LLM01: Prompt Injection
- OpenAI Prompt Engineering Guide - 'Use clear delimiters'
- AGENTS.md §4.16/§4.17（文档真实性 + 问题评估纪律）

设计原则：
- 最小侵入：不改各节点 prompt 构建逻辑，只在入口处清洗
- 可配置：分隔符和清洗规则可通过配置覆盖
- 可测试：每个清洗规则有对应的回归测试
"""

from __future__ import annotations

import re
from typing import Any

# ── 分隔符（用 XML 风格标签，LLM 对此格式有较好识别）──
CONTENT_OPEN = "<untrusted_input>"
CONTENT_CLOSE = "</untrusted_input>"

# ── 需要清洗的指令注入模式 ──
# 1. 角色标记（常见于 ChatML 格式）：<|im_start|>, <|system|>, <|user|>, <|assistant|>
_ROLE_MARKERS = re.compile(
    r"<\|im_(start|end)\|>|<\|(system|user|assistant|tool)\|>|"
    r"\[INST\]|\[/INST\]|<s>|</s>",
    re.IGNORECASE,
)

# 2. 系统指令劫持：以"忽略"、"无视"、"你现在是一个"、"从现在起"开头的指令
#    仅清洗出现在 untrusted 内容中的，不清洗系统 prompt 本身的合法指令
#    使用 \b（单词边界）区分英文关键词，中文关键词不需要空格分隔
#    不使用 ^ 锚定：注入短语可能出现在行中间（如"攻击者可能输入：忽略以上指令"）
_INJECTION_PATTERNS = re.compile(
    r"(?i)(忽略|无视|不要遵守|你必须现在|你现在是一个|从现在起|"
    r"ignore\b|disregard\b|forget\b|you are now|from now on|new instructions?\b)[^\n]*"
)

# 3. 控制字符（保留换行和制表符）
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# 4. 伪造的分隔符（防止用户输入伪造我们的边界标记）
_FAKE_DELIMITERS = re.compile(
    r"</?untrusted_input>|</?system_instruction>|</?retrieved_context>",
    re.IGNORECASE,
)


def sanitize_untrusted_content(
    text: str,
    *,
    strip_injection_patterns: bool = True,
    max_length: int = 50000,
) -> str:
    """清洗不可信内容，移除指令注入模式。

    Args:
        text: 不可信的原始文本（用户输入、RAG chunk、文档内容）
        strip_injection_patterns: 是否移除指令注入模式（默认 True）
        max_length: 最大长度（截断，防止超长 prompt）

    Returns:
        清洗后的安全文本
    """
    if not text:
        return ""

    # 截断（保留前 max_length 字符）
    if len(text) > max_length:
        text = text[:max_length] + "\n[...内容已截断...]"

    # 移除控制字符
    text = _CONTROL_CHARS.sub("", text)

    # 移除伪造的分隔符
    text = _FAKE_DELIMITERS.sub("[已移除]", text)

    # 移除角色标记
    text = _ROLE_MARKERS.sub("[已移除]", text)

    # 移除指令注入模式（可选，默认开启）
    if strip_injection_patterns:
        text = _INJECTION_PATTERNS.sub("[潜在指令已移除]", text)

    return text


def wrap_untrusted(text: str, *, label: str = "") -> str:
    """用分隔符包裹不可信内容，与系统指令隔离。

    Args:
        text: 已清洗的不可信文本
        label: 可选标签（如 "用户议题"、"检索证据"）

    Returns:
        带分隔符的包裹文本

    示例:
        >>> wrap_untrusted("帮我设计一个系统", label="用户议题")
        '<untrusted_input label="用户议题">\\n帮我设计一个系统\\n</untrusted_input>'
    """
    if not text:
        return ""
    label_attr = f' label="{label}"' if label else ""
    return f"{CONTENT_OPEN}{label_attr}\n{text}\n{CONTENT_CLOSE}"


def sanitize_and_wrap(
    text: str,
    *,
    label: str = "",
    strip_injection_patterns: bool = True,
    max_length: int = 50000,
) -> str:
    """一步完成清洗 + 包裹（最常用入口）。"""
    cleaned = sanitize_untrusted_content(
        text,
        strip_injection_patterns=strip_injection_patterns,
        max_length=max_length,
    )
    return wrap_untrusted(cleaned, label=label)


def sanitize_rag_chunks(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """批量清洗 RAG 检索结果中的文本内容。

    Args:
        chunks: RAG 检索返回的 chunk 列表，每个 chunk 是 dict

    Returns:
        清洗后的 chunk 列表（浅拷贝，不修改原数据）
    """
    cleaned: list[dict[str, Any]] = []
    for chunk in chunks:
        new_chunk = dict(chunk)
        # 清洗常见的文本字段
        for field in ("content", "text", "neighbor_context", "context", "summary"):
            if field in new_chunk and isinstance(new_chunk[field], str):
                new_chunk[field] = sanitize_untrusted_content(new_chunk[field])
        cleaned.append(new_chunk)
    return cleaned


def sanitize_doc_summaries(summaries: list[str]) -> list[str]:
    """批量清洗文档摘要列表。"""
    return [sanitize_untrusted_content(s) for s in summaries if s]
