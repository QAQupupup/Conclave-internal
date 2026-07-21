"""中英混合分词：英文字符按空格/标点分词，中文按字符或 jieba 词。

[CON-26 修复] 旧版 retriever.py / store.py 用 `re.split(r"[^a-z0-9\\u4e00-\\u9fa5]+")`，
   中文无空格分界，会把"会议系统设计"切成 6 个单字而不是 3 个有意义的词，
   导致 RAG 关键词匹配召回率低。
   本模块：
   1) 优先用 jieba 切中文（按词）
   2) 英文按空格/标点切
   3) jieba 不可用时退化到单字切分
"""

from __future__ import annotations

import re

# 尝试加载 jieba（可选依赖，缺失时退化）
try:
    import jieba

    # 静默 jieba 的首次加载日志
    jieba.setLogLevel("ERROR")
    _HAS_JIEBA = True
except ImportError:
    _HAS_JIEBA = False


# 中文字符范围
_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]")
# 英文/数字/下划线
_WORD_RE = re.compile(r"[a-zA-Z0-9_]+")


def has_jieba() -> bool:
    """检查是否安装了 jieba"""
    return _HAS_JIEBA


def tokenize(text: str, *, min_length: int = 1) -> list[str]:
    """中英混合分词

    Args:
        text: 原始文本
        min_length: 最小词长（英文），中文不受 min_length 限制

    Returns:
        词列表，已去重（小写化）
    """
    if not text:
        return []

    text_lower = text.lower()
    tokens: list[str] = []

    # 1) 英文部分：按非字母数字字符切
    for match in _WORD_RE.finditer(text_lower):
        word = match.group(0)
        if len(word) >= min_length:
            tokens.append(word)

    # 2) 中文部分：先把文本切成连续的中文片段，逐段 jieba.cut
    if _HAS_JIEBA:
        # 用反向操作：把所有非 CJK 字符替换为分隔符，然后 split
        # 这能正确处理"中文123中文"中的中文片段连续性
        zh_separator = re.compile(r"[^一-鿿぀-ゟ가-힯]+")
        for segment in zh_separator.split(text):
            if not segment:
                continue
            for word in jieba.cut(segment, cut_all=False):
                word = word.strip()
                if word:
                    tokens.append(word)
    else:
        # 退化方案：按字符切（损失语义但至少能召回）
        for ch in text:
            if _CJK_RE.match(ch):
                tokens.append(ch)

    return tokens


def tokenize_query(text: str) -> list[str]:
    """查询分词：英文字长 >= 2，中文不限长

    用于 RAG 召回：长词更可能是关键词。
    """
    return tokenize(text, min_length=2)
