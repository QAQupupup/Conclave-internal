# Type B: 字段非空检查评分器
from __future__ import annotations

from typing import Any

from eval.graders.base import GraderResult


class FieldCheckGrader:
    """字段非空检查评分器。

    检查 data 中指定字段是否非空。空字符串、None、空列表/空字典均视为空。
    score = 非空字段数 / 总字段数；全部非空才 passed=True。
    """

    def grade(self, data: dict, required_fields: list[str]) -> GraderResult:
        if not required_fields:
            return GraderResult(score=1.0, passed=True, detail="no required fields")

        passed_count = 0
        empty_fields: list[str] = []
        for field in required_fields:
            value = data.get(field) if isinstance(data, dict) else None
            if self._is_non_empty(value):
                passed_count += 1
            else:
                empty_fields.append(field)

        total = len(required_fields)
        score = passed_count / total
        passed = passed_count == total
        detail = f"{passed_count}/{total} fields non-empty"
        if empty_fields:
            detail += f"; empty: {', '.join(empty_fields)}"
        return GraderResult(score=score, passed=passed, detail=detail)

    @staticmethod
    def _is_non_empty(value: Any) -> bool:
        if value is None:
            return False
        if isinstance(value, str) and value.strip() == "":
            return False
        if isinstance(value, (list, dict)) and len(value) == 0:
            return False
        return True
