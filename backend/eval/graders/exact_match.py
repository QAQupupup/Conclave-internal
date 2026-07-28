# Type A: 精确匹配评分器
from __future__ import annotations

from typing import Any

from eval.graders.base import GraderResult


class ExactMatchGrader:
    """精确匹配评分器。

    - 当 expected 为标量时：要求 actual 与 expected 完全相等。
    - 当 expected 为列表时：要求 expected 是 actual 的子集（actual 包含全部期望项）。
      部分命中时按命中比例给分，但 passed=False。
    """

    def grade(self, expected: Any, actual: Any) -> GraderResult:
        # 标量匹配
        if not isinstance(expected, list):
            if expected == actual:
                return GraderResult(score=1.0, passed=True, detail="exact match")
            return GraderResult(
                score=0.0,
                passed=False,
                detail=f"expected {expected!r}, got {actual!r}",
            )

        # 列表子集匹配
        if not isinstance(actual, list):
            actual_list: list[Any] = [actual] if actual is not None else []
        else:
            actual_list = list(actual)

        if not expected:
            return GraderResult(score=1.0, passed=True, detail="empty expected list")

        matched = sum(1 for item in expected if item in actual_list)
        score = matched / len(expected)
        passed = matched == len(expected)
        missing = [item for item in expected if item not in actual_list]
        detail = f"matched {matched}/{len(expected)}"
        if missing:
            detail += f"; missing: {missing!r}"
        return GraderResult(score=score, passed=passed, detail=detail)
