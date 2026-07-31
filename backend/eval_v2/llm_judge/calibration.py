"""Judge calibration - Cohen's kappa, self-consistency, reliability checks."""

from __future__ import annotations

import math

from eval_v2.models.judgment import CoTJudgment, KappaResult


def cohens_kappa(judgments_a: list[int], judgments_b: list[int]) -> KappaResult:
    """计算 Cohen's kappa（两个评分者间一致性）。

    使用简化版：将评分二值化（≥3=pass，<3=fail）后计算 kappa。

    Args:
        judgments_a: 评分者A的 likert 分数列表
        judgments_b: 评分者B的 likert 分数列表（相同样本）

    Returns:
        KappaResult with kappa value and metadata
    """
    n = min(len(judgments_a), len(judgments_b))
    if n < 2:
        return KappaResult(kappa=0.0, agreement_rate=0.0, n_samples=n, is_reliable=False)

    # 二值化
    a_binary = [1 if s >= 3 else 0 for s in judgments_a[:n]]
    b_binary = [1 if s >= 3 else 0 for s in judgments_b[:n]]

    # 观察一致率 Po
    agree = sum(1 for i in range(n) if a_binary[i] == b_binary[i])
    po = agree / n

    # 期望一致率 Pe
    a_pos = sum(a_binary) / n
    b_pos = sum(b_binary) / n
    a_neg = 1 - a_pos
    b_neg = 1 - b_pos
    pe = a_pos * b_pos + a_neg * b_neg

    # Kappa
    if pe == 1.0:
        kappa = 1.0 if po == 1.0 else 0.0
    else:
        kappa = (po - pe) / (1 - pe)

    kappa = max(-1.0, min(1.0, kappa))

    return KappaResult(
        kappa=kappa,
        agreement_rate=po,
        n_samples=n,
        is_reliable=kappa >= 0.6 and n >= 10,
        judge_a="",
        judge_b="",
    )


def self_consistency(judgments: list[CoTJudgment]) -> float:
    """计算同一 Judge 多次评分的自一致性。

    使用 1 - CV（变异系数）来衡量一致性。
    CV = std / mean，返回 1 - CV（越接近1越一致）。
    """
    if not judgments:
        return 0.0
    scores = [j.likert_score for j in judgments]
    if len(scores) == 1:
        return 1.0
    mean = sum(scores) / len(scores)
    if mean == 0:
        return 0.0
    variance = sum((s - mean) ** 2 for s in scores) / len(scores)
    std = math.sqrt(variance)
    cv = std / mean
    return max(0.0, min(1.0, 1.0 - cv))


def median_likert(judgments: list[CoTJudgment]) -> tuple[int, float, float]:
    """计算多次评分的中位数 likert、均值、标准差。"""
    if not judgments:
        return 3, 3.0, 0.0
    scores = sorted(j.likert_score for j in judgments)
    n = len(scores)
    if n % 2 == 1:
        median = scores[n // 2]
    else:
        median = (scores[n // 2 - 1] + scores[n // 2]) / 2
        median = int(round(median))
    mean = sum(scores) / n
    if n > 1:
        variance = sum((s - mean) ** 2 for s in scores) / (n - 1)
        std = math.sqrt(variance)
    else:
        std = 0.0
    return median, mean, std


def aggregate_reasoning(judgments: list[CoTJudgment]) -> list[str]:
    """聚合多次评分的 reasoning。"""
    return [j.reasoning for j in judgments if j.reasoning]
