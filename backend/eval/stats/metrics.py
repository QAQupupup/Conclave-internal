# 指标计算：Pass@k、阶段通过率、平均分、方差、百分位数
from __future__ import annotations

import statistics
from typing import Any

# 阶段通过判定的默认阈值（stage score >= 该值视为该阶段通过）
STAGE_PASS_THRESHOLD = 0.6


def _extract_passed(item: Any) -> bool:
    """从结果项中提取 passed 标志（兼容 bool 与含 passed 属性的对象）。"""
    if isinstance(item, bool):
        return item
    return bool(getattr(item, "passed", False))


def calculate_pass_at_k(results: list, k: int) -> float:
    """计算 Pass@k。

    results 为按用例顺序排列的每次运行结果（bool 或含 ``passed`` 属性的对象）。
    - k == 1：直接返回通过比例。
    - k > 1：将 results 按 k 个一组分块，每组只要任一次通过即算该用例通过，
      Pass@k = 通过用例数 / 用例数。
    """
    flags = [_extract_passed(r) for r in results]
    if not flags:
        return 0.0
    if k <= 1:
        return sum(1 for f in flags if f) / len(flags)
    passed_cases = 0
    total_cases = 0
    for i in range(0, len(flags), k):
        chunk = flags[i : i + k]
        total_cases += 1
        if any(chunk):
            passed_cases += 1
    return passed_cases / total_cases if total_cases else 0.0


def calculate_stage_pass_rate(results: list, stage: str, threshold: float = STAGE_PASS_THRESHOLD) -> float:
    """计算指定阶段的通过率。

    results 为 CaseResult 列表，取每个结果的 ``stage_scores[stage]``，
    得分 >= threshold 视为该阶段通过。
    """
    relevant = [r for r in results if hasattr(r, "stage_scores") and stage in r.stage_scores]
    if not relevant:
        return 0.0
    passed = sum(1 for r in relevant if r.stage_scores[stage] >= threshold)
    return passed / len(relevant)


def calculate_avg_score(results: list) -> float:
    """计算所有阶段得分的平均值。"""
    all_scores: list[float] = []
    for r in results:
        if hasattr(r, "stage_scores"):
            all_scores.extend(float(v) for v in r.stage_scores.values())
    if not all_scores:
        return 0.0
    return statistics.mean(all_scores)


def calculate_score_std(results: list) -> float:
    """计算所有阶段得分的总体标准差。"""
    all_scores: list[float] = []
    for r in results:
        if hasattr(r, "stage_scores"):
            all_scores.extend(float(v) for v in r.stage_scores.values())
    if len(all_scores) < 2:
        return 0.0
    return statistics.pstdev(all_scores)


def calculate_percentile(values: list, p: int) -> float:
    """计算百分位数（线性插值法），p 为 0-100 之间的整数（如 50、95）。"""
    if not values:
        return 0.0
    nums = sorted(float(v) for v in values)
    n = len(nums)
    if n == 1:
        return nums[0]
    rank = (p / 100.0) * (n - 1)
    lower = int(rank)
    upper = min(lower + 1, n - 1)
    frac = rank - lower
    return nums[lower] + frac * (nums[upper] - nums[lower])
