# 一致性自检：置信度相关纯函数
from __future__ import annotations

_CONFIDENCE_RANK: dict[str, int] = {"high": 0, "low": 1, "fallback": 2}


def worst_confidence(a: str, b: str) -> str:
    """返回两个置信度中较差的一个"""
    return a if _CONFIDENCE_RANK.get(a, 0) >= _CONFIDENCE_RANK.get(b, 0) else b
