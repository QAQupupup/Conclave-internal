# Grader 基础类型：所有评分器的统一返回类型
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class GraderResult:
    """评分结果。

    score: 0.0 - 1.0 之间的得分。
    passed: 是否通过该评分维度。
    detail: 人类可读的说明（英文）。
    unreliable: 该评分是否不可信（例如 LLM judge 多次评分方差过大）。
    """

    score: float  # 0.0 - 1.0
    passed: bool
    detail: str = ""
    unreliable: bool = False
