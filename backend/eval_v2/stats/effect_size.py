"""Effect size calculations for comparing evaluation results."""

from __future__ import annotations

import math


def cohens_h(p1: float, p2: float) -> float:
    """Cohen's h 效应量（两个比例之间的差异）。

    h = 2 * arcsin(sqrt(p1)) - 2 * arcsin(sqrt(p2))

    解释：
    - 0.2: 小效应
    - 0.5: 中等效应
    - 0.8: 大效应
    """
    return 2 * (math.asin(math.sqrt(p1)) - math.asin(math.sqrt(p2)))


def cohens_d(mean1: float, mean2: float, sd1: float, sd2: float, n1: int, n2: int) -> float:
    """Cohen's d 效应量（两个均值之间的差异，使用合并标准差）。

    解释：
    - 0.2: 小效应
    - 0.5: 中等效应
    - 0.8: 大效应
    """
    # 合并方差
    pooled_var = ((n1 - 1) * sd1**2 + (n2 - 1) * sd2**2) / (n1 + n2 - 2) if (n1 + n2) > 2 else 0
    pooled_sd = math.sqrt(pooled_var) if pooled_var > 0 else 1.0
    return (mean1 - mean2) / pooled_sd


def cliffs_delta(x: list[float], y: list[float]) -> float:
    """Cliff's delta 非参数效应量。

    取值 [-1, 1]，0 表示无差异，±1 表示完全分离。
    解释：
    - |0.147|: 小效应
    - |0.33|: 中等效应
    - |0.474|: 大效应
    """
    if not x or not y:
        return 0.0
    n1, n2 = len(x), len(y)
    greater = 0
    less = 0
    for xi in x:
        for yi in y:
            if xi > yi:
                greater += 1
            elif xi < yi:
                less += 1
    return (greater - less) / (n1 * n2)


def interpret_cohens_h(h: float) -> str:
    """解释 Cohen's h 效应量。"""
    abs_h = abs(h)
    if abs_h < 0.2:
        return "negligible"
    elif abs_h < 0.5:
        return "small"
    elif abs_h < 0.8:
        return "medium"
    else:
        return "large"
