"""Wilson score interval for binomial proportions."""

from __future__ import annotations

import math


def wilson_interval(
    successes: int,
    n: int,
    confidence: float = 0.95,
) -> tuple[float, float]:
    """计算 Wilson 置信区间。

    Args:
        successes: 成功数
        n: 总样本数
        confidence: 置信水平（默认 0.95）

    Returns:
        (lower_bound, upper_bound) 都在 [0, 1] 范围内
    """
    if n == 0:
        return (0.0, 0.0)

    # z-score for confidence level
    z = _z_score(confidence)

    p_hat = successes / n
    denom = 1 + z**2 / n
    center = (p_hat + z**2 / (2 * n)) / denom
    margin = (z * math.sqrt(p_hat * (1 - p_hat) / n + z**2 / (4 * n**2))) / denom

    lower = max(0.0, center - margin)
    upper = min(1.0, center + margin)
    return (lower, upper)


def required_sample_size(
    margin_of_error: float = 0.10,
    confidence: float = 0.95,
    expected_proportion: float = 0.5,
) -> int:
    """计算所需样本量以达到指定边际误差。

    Args:
        margin_of_error: 目标边际误差（如 0.10 = 10个百分点）
        confidence: 置信水平
        expected_proportion: 预期比例（0.5 给出最保守估计）

    Returns:
        所需最小样本量
    """
    z = _z_score(confidence)
    p = expected_proportion
    n = (z**2 * p * (1 - p)) / (margin_of_error**2)
    return math.ceil(n)


def ci_width(ci: tuple[float, float]) -> float:
    """置信区间宽度（百分点）。"""
    return (ci[1] - ci[0]) * 100


def _z_score(confidence: float) -> float:
    """获取标准正态分布的 z-score。"""
    # 常见置信水平对应的 z 值
    z_table = {
        0.90: 1.645,
        0.95: 1.96,
        0.98: 2.326,
        0.99: 2.576,
    }
    return z_table.get(round(confidence, 2), 1.96)
