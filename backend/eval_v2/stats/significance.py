"""Statistical significance tests for comparing evaluation results."""

from __future__ import annotations

import math


def fisher_exact_test(
    a_successes: int,
    a_total: int,
    b_successes: int,
    b_total: int,
    two_sided: bool = True,
) -> float:
    """Fisher 精确检验（用于比较两个比例的差异）。

    使用近似实现（超几何分布的 p 值）。
    当 n 较大时使用 chi-squared 近似。

    Args:
        a_successes: A 组成功数
        a_total: A 组总数
        b_successes: B 组成功数
        b_total: B 组总数
        two_sided: 是否双侧检验

    Returns:
        p 值（< 0.05 表示显著差异）
    """
    # 构建 2x2 列联表
    #              成功  失败
    # A 组         a     c
    # B 组         b     d
    a = a_successes
    c = a_total - a_successes
    b = b_successes
    d = b_total - b_successes

    n = a + b + c + d

    # 当样本量足够大时使用 chi-squared 近似
    if n >= 40 and (a + b) * (c + d) * (a + c) * (b + d) > 0:
        expected_min = (min(a + b, c + d, a + c, b + d)) ** 2 / n
        if expected_min >= 5:
            return _chi_squared_test(a, b, c, d, two_sided)

    # 对于小样本，使用超几何分布的精确计算（简化版）
    return _fisher_exact_small(a, b, c, d, two_sided)


def _chi_squared_test(a: int, b: int, c: int, d: int, two_sided: bool) -> float:
    """Chi-squared 检验近似。"""
    n = a + b + c + d
    # 期望频数
    e_a = (a + b) * (a + c) / n
    e_b = (a + b) * (b + d) / n
    e_c = (c + d) * (a + c) / n
    e_d = (c + d) * (b + d) / n

    chi2 = (a - e_a) ** 2 / e_a + (b - e_b) ** 2 / e_b + (c - e_c) ** 2 / e_c + (d - e_d) ** 2 / e_d

    # df=1, chi2 > 3.84 对应 p < 0.05
    # 近似 p 值计算（使用不完整 gamma 函数的简单近似）
    p = _chi2_to_p(chi2, df=1)
    if two_sided:
        return p
    return p / 2


def _chi2_to_p(chi2: float, df: int = 1) -> float:
    """Chi-squared to p-value approximation (df=1)."""
    # 对于 df=1，使用简单近似
    if chi2 <= 0:
        return 1.0
    # 使用正态近似：sqrt(chi2) ~ |Z| for df=1
    z = math.sqrt(chi2)
    # 标准正态分布右尾概率
    return _normal_sf(z) * 2  # two-sided


def _normal_sf(z: float) -> float:
    """标准正态分布生存函数（1 - CDF）近似。

    使用 Abramowitz and Stegun 公式 7.1.26。
    对于 z >= 0 返回 P(Z > z)；对于 z < 0 返回 P(Z < z)（调用者负责取绝对值）。
    """
    p = 0.3275911
    a1, a2, a3, a4, a5 = 0.254829592, -0.284496736, 1.421413741, -1.453152027, 1.061405429
    if z < 0:
        z = -z
    # x = z/sqrt(2), t = 1/(1+p*x), 但 p 已经是按 x=z/sqrt(2) 校正的？
    # 实际上：标准 A&S 公式直接用 t = 1/(1+pz) 对 erf(z/sqrt(2)) 近似
    # 这里直接用 z 传入，t=1/(1+pz)
    t = 1.0 / (1.0 + p * z)
    # y ≈ erf(z/sqrt(2))
    y = 1.0 - (((((a5 * t + a4) * t) + a3) * t + a2) * t + a1) * t * math.exp(-z * z / 2.0)
    # P(Z > z) = 0.5 * (1 - erf(z/sqrt(2))) = 0.5*(1-y)
    return 0.5 * (1.0 - y)


def _fisher_exact_small(a: int, b: int, c: int, d: int, two_sided: bool) -> float:
    """小样本 Fisher 精确检验（使用 scipy 如果可用，否则用近似）。"""
    try:
        from scipy.stats import fisher_exact as scipy_fisher

        _, p = scipy_fisher([[a, c], [b, d]], alternative="two-sided" if two_sided else "greater")
        return p
    except ImportError:
        # 无 scipy 时，使用 chi2 近似作为 fallback
        return _chi_squared_test(a, b, c, d, two_sided)


def mann_whitney_u(x: list[float], y: list[float]) -> float:
    """Mann-Whitney U 检验（比较两个独立样本的分布差异）。

    简化实现：对于大样本使用正态近似。
    """
    if not x or not y:
        return 1.0

    n1, n2 = len(x), len(y)
    combined = [(v, 0) for v in x] + [(v, 1) for v in y]
    combined.sort(key=lambda t: t[0])

    # 计算秩
    ranks = [0.0] * (n1 + n2)
    i = 0
    while i < len(combined):
        j = i
        while j < len(combined) and combined[j][0] == combined[i][0]:
            j += 1
        avg_rank = (i + j + 1) / 2.0  # 1-based rank
        for k in range(i, j):
            ranks[k] = avg_rank
        i = j

    # U 统计量
    rank_sum_x = sum(ranks[k] for k in range(len(combined)) if combined[k][1] == 0)
    u1 = rank_sum_x - n1 * (n1 + 1) / 2
    u2 = n1 * n2 - u1
    u = min(u1, u2)

    # 正态近似
    mu = n1 * n2 / 2
    sigma = math.sqrt(n1 * n2 * (n1 + n2 + 1) / 12)
    if sigma == 0:
        return 1.0
    z = (u - mu) / sigma
    return _normal_sf(abs(z)) * 2  # two-sided
