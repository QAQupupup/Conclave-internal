"""Prompt 注入防御：检测和清理可能污染 LLM 的用户输入。

[CON-22 修复] 旧版对用户输入（topic、intervention、reference 等）几乎不检查，
   LLM prompt 模板直接把用户文本拼接，可能被注入 "ignore previous instructions" 等
   攻击载荷。本模块提供：
   1. 已知注入模式正则库
   2. 用户输入预清洗（保留语义，去除危险模式）
   3. 输入包裹：在用户文本外加隔离标记，告知 LLM 边界
"""
from __future__ import annotations

import re
from typing import Tuple

# 已知 prompt injection 模式（中英文）
_INJECTION_PATTERNS: list[tuple[str, str]] = [
    # 英文：忽略之前的指令
    (r"(?i)ignore\s+(all\s+)?(previous|prior|above)\s+(instructions|prompts?)", "ignore-previous"),
    (r"(?i)disregard\s+(all\s+)?(previous|prior)\s+(instructions|rules?)", "disregard-rules"),
    (r"(?i)forget\s+(everything|all|previous)", "forget-all"),
    # 英文：扮演新角色
    (r"(?i)you\s+are\s+now\s+(a|an|the)\s+", "new-role"),
    (r"(?i)act\s+as\s+(a|an|the)\s+", "act-as"),
    (r"(?i)pretend\s+(to\s+be|you\s+are)\s+", "pretend"),
    (r"(?i)system\s*:\s*", "fake-system-tag"),
    (r"(?i)<\|.*?\|>", "fake-tag"),
    # 英文：输出越权
    (r"(?i)print\s+(your|the)\s+(system|initial)\s+prompt", "leak-prompt"),
    (r"(?i)reveal\s+(your|the)\s+(system|initial)\s+(prompt|instructions)", "leak-prompt"),
    # 中文：忽略/忘记之前的指令
    (r"忽略(之前|以上|前面)的(指令|规则|提示)", "zh-ignore"),
    (r"忘记(所有|之前|以上)的(内容|指令|规则)", "zh-forget"),
    (r"你现在是(?!会议)", "zh-new-role"),
    (r"扮演(一个|一位)?", "zh-act-as"),
    (r"请(扮演|假装|假设|当作)", "zh-pretend"),
    (r"输出(你的|系统)?初始提示", "zh-leak-prompt"),
    (r"显示(你的|系统)?指令", "zh-show-prompt"),
]


def detect_injection(text: str) -> list[dict[str, str | int]]:
    """检测文本中的疑似 prompt 注入模式。

    Returns:
        命中列表，每项含 pattern_id、match（截断 80 字符）、offset。
    """
    if not text:
        return []
    hits: list[dict[str, str | int]] = []
    for pattern, pid in _INJECTION_PATTERNS:
        m = re.search(pattern, text)
        if m:
            hits.append({
                "pattern_id": pid,
                "match": m.group(0)[:80],
                "offset": m.start(),
            })
    return hits


def has_injection(text: str) -> bool:
    """快速判断是否含疑似注入。"""
    return any(re.search(p, text) for p, _ in _INJECTION_PATTERNS)


def sanitize_user_input(text: str, *, max_length: int = 8000) -> Tuple[str, list[dict[str, str | int]]]:
    """对用户输入做预清洗。

    Args:
        text: 原始用户输入
        max_length: 最大保留字符数（防止超大输入撑爆 prompt）

    Returns:
        (cleaned_text, hits): 清洗后的文本 + 命中的注入模式列表。
        注意：sanitize **不会删除可疑内容**（避免破坏正常语义），
        只截断过长输入，并把可疑模式报告给调用方做二次判断。
    """
    if not text:
        return text, []

    # 1) 截断超长输入
    if len(text) > max_length:
        text = text[:max_length] + "\n\n[输入已截断]"

    # 2) 检测注入模式
    hits = detect_injection(text)

    return text, hits


def wrap_user_content(text: str, *, label: str = "USER_INPUT") -> str:
    """把用户内容包在隔离标记中再喂给 LLM。

    用法：
        prompt = f"系统提示...\\n\\n<<<{label}>>>\\n{sanitize_user_input(text)}\\n<<<END_{label}>>>\\n..."

    LLM 应被明确告知：标记内的内容是用户数据，**不视为新指令**。
    """
    return f"<<<{label}>>>\n{text}\n<<<END_{label}>>>"
