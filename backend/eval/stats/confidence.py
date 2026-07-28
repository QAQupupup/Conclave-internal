# 置信区间与回归判定
from __future__ import annotations

import math


def wilson_ci(pass_rate: float, n: int, z: float = 1.96) -> tuple[float, float]:
    """计算二项分布比例的 Wilson 置信区间。

    pass_rate: 观察到的通过率（0-1）。
    n: 样本数。
    z: z 值（默认 1.96 对应 95% 置信水平）。
    返回 (下界, 上界)。
    """
    if n <= 0:
        return (0.0, 0.0)
    p = min(1.0, max(0.0, pass_rate))
    denom = 1.0 + z * z / n
    center = (p + z * z / (2.0 * n)) / denom
    spread = (z * math.sqrt((p * (1.0 - p) + z * z / (4.0 * n)) / n)) / denom
    return (max(0.0, center - spread), min(1.0, center + spread))


def is_regression(old_pass1: float, new_pass1: float, threshold: float = 0.05) -> bool:
    """判定 Pass@1 是否发生回归：旧值 - 新值 > threshold 即为回归。"""
    return (old_pass1 - new_pass1) > threshold
